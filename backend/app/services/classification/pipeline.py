"""Knowledge-Driven Multi-Agent Classification Loop + CustomsBrokerAgent supervision."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.core.config import get_settings
from backend.app.db.models import (
    ClassificationResult,
    CorrectionDelta,
    GuardrailState,
    KnowledgeHistory,
    OpinionReport,
    ProductCase,
)
from backend.app.services.knowledge.graph import get_kg


@dataclass
class ClassificationOutput:
    recommended_hs: str
    final_hs: str
    confidence: float
    review_tier: str
    status: str
    gir_applied: list[str]
    exclusion_checks: list[dict[str, Any]]
    local_hits: list[dict[str, Any]]
    global_hits: list[dict[str, Any]]
    routing_mode: str
    contention_score: float
    trajectory: list[dict[str, Any]]
    metric_flags: list[str]
    opinion: dict[str, Any]
    delta: dict[str, Any]
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class HypothesisAgent:
    def propose(self, description: str, search: dict[str, Any], warnings: list[dict]) -> dict[str, Any]:
        local = search.get("local") or []
        if local:
            top = local[0]["code"]
        else:
            top = "9999.99.9999"
        alts = [h["code"] for h in local[1:3]]
        if warnings:
            # Prefer historically corrected code when available
            for w in warnings:
                if w.get("corrected_code"):
                    top = w["corrected_code"]
                    break
        return {
            "agent": "HypothesisAgent",
            "proposed": top,
            "alternatives": alts,
            "rationale": "Local GraphRAG ranking with K_history pre-emptive warnings",
        }


class RegulationCritic:
    def critique(self, proposal: dict[str, Any], search: dict[str, Any]) -> dict[str, Any]:
        flags = []
        exclusion_checks = []
        for hit in search.get("global") or []:
            if hit.get("reason") == "legal_note":
                exclusion_checks.append({"note": hit.get("title"), "code": hit.get("code"), "ok": True})
            if hit.get("reason") == "chapter_contention":
                flags.append("chapter_contention")
                exclusion_checks.append(
                    {"note": "contending chapter candidate", "code": hit.get("code"), "ok": True}
                )
        verdict = "PASS"
        if proposal["proposed"].startswith("9999"):
            verdict = "BLOCK"
            flags.append("unknown_code")
        return {
            "agent": "RegulationCritic",
            "verdict": verdict,
            "flags": flags,
            "exclusion_checks": exclusion_checks,
            "gir": ["GIR1", "GIR6"] + (["GIR3"] if "chapter_contention" in flags else []),
        }


class MetricGuardrail:
    def check(self, db: Session, hs_code: str, gir: list[str]) -> list[str]:
        flags: list[str] = []
        chapter = int(hs_code[:2]) if hs_code[:2].isdigit() else 0
        recent = (
            db.query(ClassificationResult)
            .order_by(ClassificationResult.id.desc())
            .limit(50)
            .all()
        )
        if recent:
            same = sum(1 for r in recent if r.recommended_hs[:2] == hs_code[:2])
            share = same / len(recent)
            guard = db.query(GuardrailState).filter(GuardrailState.chapter == chapter).first()
            threshold = guard.mode_collapse_threshold if guard else 0.35
            if share > threshold and len(recent) >= 10:
                flags.append("mode_collapse_risk")
        if "GIR3" not in gir and "GIR1" in gir and len(gir) <= 1:
            flags.append("gir_avoidance_risk")
        return flags


class CustomsBrokerAgent:
    """Supervisory layer: final review, opinion report, closed-loop feedback."""

    def __init__(self, theta_high: float = 0.75) -> None:
        self.theta_high = theta_high
        self.kg = get_kg()

    def _confidence(
        self,
        gir: list[str],
        contention: float,
        history_match: float,
        critic_verdict: str,
    ) -> float:
        score = 0.35
        score += min(len(gir), 3) * 0.12
        score += history_match * 0.25
        score -= contention * 0.2
        if critic_verdict == "BLOCK":
            score -= 0.4
        return max(0.05, min(0.98, score))

    def review(
        self,
        db: Session,
        case: ProductCase,
        proposal: dict[str, Any],
        critic: dict[str, Any],
        search: dict[str, Any],
        metric_flags: list[str],
        closed_loop: bool = True,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        hs = proposal["proposed"]
        chapter = int(hs[:2]) if hs[:2].isdigit() else 0
        history = (
            db.query(KnowledgeHistory)
            .filter(KnowledgeHistory.chapter == chapter)
            .order_by(KnowledgeHistory.id.desc())
            .limit(5)
            .all()
        )
        history_match = 0.0
        similar = []
        for h in history:
            similar.append(h.payload)
            if h.payload.get("corrected_code") == hs:
                history_match = 0.9
            elif h.payload.get("original_code") == hs:
                history_match = max(history_match, 0.3)

        contention = 1.0 if "chapter_contention" in critic.get("flags", []) else 0.2
        if metric_flags:
            contention = max(contention, 0.5)

        conf = self._confidence(critic.get("gir", []), contention, history_match, critic["verdict"])
        tier = "lightweight" if conf >= self.theta_high and "mode_collapse_risk" not in metric_flags else "deep"

        overridden = False
        reason = "approved"
        corrected = hs

        # Simulate expert correction on hard / deep cases using GT or tariff optimization
        if tier == "deep" and case.ground_truth_hs and case.ground_truth_hs != hs:
            overridden = True
            corrected = case.ground_truth_hs
            reason = "gir_interpretation"
        elif tier == "deep":
            # Tariff optimization path: prefer lower rate among close alternatives
            alts = [hs] + proposal.get("alternatives", [])
            rates = [(c, self.kg.tariff_rate(c)) for c in alts if c in self.kg.by_code]
            if rates:
                best = min(rates, key=lambda x: x[1])
                if best[0] != hs and best[1] + 0.5 < self.kg.tariff_rate(hs):
                    overridden = True
                    corrected = best[0]
                    reason = "tariff_optimization"

        if not closed_loop:
            # Open-loop ablation: still reviews but does not persist learning (caller skips)
            pass

        original_rate = self.kg.tariff_rate(hs)
        corrected_rate = self.kg.tariff_rate(corrected)
        delta = {
            "original_code": hs,
            "corrected_code": corrected,
            "overridden": overridden,
            "reason": reason,
            "tariff_impact": {
                "original_rate": original_rate,
                "corrected_rate": corrected_rate,
                "fta_eligible": False,
            },
            "chapter": int(corrected[:2]) if corrected[:2].isdigit() else chapter,
            "gir_applied": critic.get("gir", []),
            "similar_cases": [s.get("id") for s in similar if isinstance(s, dict)],
        }

        grade = "High" if conf >= 0.75 else ("Medium" if conf >= 0.45 else "Low")
        opinion = {
            "product_summary": case.description,
            "candidate_codes": [hs] + proposal.get("alternatives", []),
            "gir_rationale": f"Applied {', '.join(critic.get('gir', []))}: essential character and heading terms reviewed.",
            "exclusion_summary": "; ".join(
                e.get("note", "") for e in critic.get("exclusion_checks", [])
            )
            or "No exclusion rule violation detected.",
            "tariff_info": delta["tariff_impact"],
            "similar_cases": similar[:3],
            "broker_opinion": (
                f"{'Corrected' if overridden else 'Approved'} HS {corrected}. "
                f"Review tier={tier}. Reason={reason}."
            ),
            "confidence_grade": grade,
            "auto_approved": not overridden and tier == "lightweight",
        }

        review_meta = {
            "confidence": conf,
            "review_tier": tier,
            "status": "corrected" if overridden else ("blocked" if critic["verdict"] == "BLOCK" else "auto_approved"),
            "final_hs": corrected,
            "contention_score": contention,
        }
        return review_meta, opinion, delta


class ClassificationPipeline:
    def __init__(self) -> None:
        settings = get_settings()
        self.kg = get_kg()
        self.hypothesis = HypothesisAgent()
        self.critic = RegulationCritic()
        self.guardrail = MetricGuardrail()
        self.broker = CustomsBrokerAgent(theta_high=settings.theta_high)

    def _warnings(self, db: Session, description: str) -> list[dict]:
        # crude category from keywords
        category = "general"
        desc = description.lower()
        for kw, cat in [
            ("cream", "cosmetic"),
            ("serum", "cosmetic"),
            ("supplement", "food"),
            ("phone", "electronics"),
            ("shirt", "apparel"),
            ("bottle", "plastic"),
            ("medical", "medical"),
        ]:
            if kw in desc:
                category = cat
                break
        rows = (
            db.query(KnowledgeHistory)
            .filter(KnowledgeHistory.product_category == category)
            .order_by(KnowledgeHistory.id.desc())
            .limit(5)
            .all()
        )
        return [r.payload for r in rows]

    def _route(self, description: str) -> str:
        # Adaptive routing: simple queries -> local_only
        tokens = set(re.findall(r"[a-zA-Z가-힣0-9]+", description.lower()))
        contention_cues = {"or", "and", "kit", "set", "multi", "복합", "겸용", "세트"}
        if tokens & contention_cues or len(tokens) > 12:
            return "dual"
        return "local_only" if len(tokens) <= 6 else "dual"

    def classify(
        self,
        db: Session,
        case: ProductCase,
        closed_loop: bool = True,
        force_routing: Optional[str] = None,
    ) -> ClassificationOutput:
        routing = force_routing or self._route(case.description)
        search = self.kg.dual_channel_search(case.description, routing=routing)
        warnings = self._warnings(db, case.description) if closed_loop else []
        proposal = self.hypothesis.propose(case.description, search, warnings)
        critic = self.critic.critique(proposal, search)
        metric_flags = self.guardrail.check(db, proposal["proposed"], critic.get("gir", []))
        review, opinion, delta = self.broker.review(
            db, case, proposal, critic, search, metric_flags, closed_loop=closed_loop
        )

        trajectory = [
            {"step": "retrieve", "routing": routing, "local_n": len(search["local"]), "global_n": len(search["global"])},
            {"step": "hypothesize", **proposal},
            {"step": "critique", **critic},
            {"step": "guardrail", "flags": metric_flags},
            {"step": "broker_review", **review, "reason": delta["reason"]},
        ]

        result = ClassificationResult(
            case_id=case.id,
            session_id=str(uuid.uuid4()),
            recommended_hs=proposal["proposed"],
            final_hs=review["final_hs"],
            confidence=review["confidence"],
            review_tier=review["review_tier"],
            status=review["status"],
            gir_applied=critic.get("gir", []),
            exclusion_checks=critic.get("exclusion_checks", []),
            local_hits=search["local"],
            global_hits=search["global"],
            routing_mode=routing,
            contention_score=review["contention_score"],
            trajectory=trajectory,
            metric_flags=metric_flags,
        )
        db.add(result)
        db.flush()

        op = OpinionReport(
            classification_id=result.id,
            product_summary=opinion["product_summary"],
            candidate_codes=opinion["candidate_codes"],
            gir_rationale=opinion["gir_rationale"],
            exclusion_summary=opinion["exclusion_summary"],
            tariff_info=opinion["tariff_info"],
            similar_cases=opinion["similar_cases"],
            broker_opinion=opinion["broker_opinion"],
            confidence_grade=opinion["confidence_grade"],
            auto_approved=opinion["auto_approved"],
        )
        db.add(op)

        corr = CorrectionDelta(
            classification_id=result.id,
            original_code=delta["original_code"],
            corrected_code=delta["corrected_code"],
            overridden=delta["overridden"],
            reason=delta["reason"],
            tariff_impact=delta["tariff_impact"],
            chapter=delta["chapter"],
            gir_applied=delta["gir_applied"],
            similar_cases=delta["similar_cases"],
            incorporated=closed_loop,
        )
        db.add(corr)

        if closed_loop and delta["overridden"]:
            category = "general"
            dlow = case.description.lower()
            for kw, cat in [
                ("cream", "cosmetic"),
                ("serum", "cosmetic"),
                ("lotion", "cosmetic"),
                ("supplement", "food"),
                ("phone", "electronics"),
                ("shirt", "apparel"),
                ("bottle", "plastic"),
                ("medical", "medical"),
            ]:
                if kw in dlow:
                    category = cat
                    break
            kh = KnowledgeHistory(
                key=f"{delta['chapter']}:{category}:{delta['reason']}",
                chapter=delta["chapter"],
                product_category=category,
                violation_type=delta["reason"],
                payload={**delta, "id": f"delta-{result.id}", "case_id": case.external_id},
                source="broker_correction",
            )
            db.add(kh)
            guard = db.query(GuardrailState).filter(GuardrailState.chapter == delta["chapter"]).first()
            if not guard:
                guard = GuardrailState(
                    chapter=delta["chapter"],
                    expected_share=0.1,
                    correction_count=0,
                    mode_collapse_threshold=0.35,
                )
                db.add(guard)
                db.flush()
            count = int(guard.correction_count or 0) + 1
            guard.correction_count = count
            # Reality anchor: more corrections -> lower collapse threshold (more deep reviews)
            guard.mode_collapse_threshold = max(0.15, 0.35 - 0.02 * count)

        db.commit()
        db.refresh(result)

        return ClassificationOutput(
            recommended_hs=result.recommended_hs,
            final_hs=result.final_hs,
            confidence=result.confidence,
            review_tier=result.review_tier,
            status=result.status,
            gir_applied=result.gir_applied,
            exclusion_checks=result.exclusion_checks,
            local_hits=result.local_hits,
            global_hits=result.global_hits,
            routing_mode=result.routing_mode,
            contention_score=result.contention_score,
            trajectory=result.trajectory,
            metric_flags=result.metric_flags,
            opinion=opinion,
            delta=delta,
            session_id=result.session_id,
        )
