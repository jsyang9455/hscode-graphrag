"""Knowledge-Driven Multi-Agent Classification Loop (office-scoped)."""

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
    KnowledgeHistory,
    OpinionReport,
    ProductCase,
)
from backend.app.services.classification.rationale import build_broker_brief
from backend.app.services.classification.llm_recommend import co_recommend
from backend.app.services.knowledge.graph import get_kg


@dataclass
class ClassificationOutput:
    classification_id: int
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
        top = local[0]["code"] if local else "9999.99"
        top_score = float(local[0].get("score") or 0) if local else 0.0
        alts = [h["code"] for h in local[1:3]]
        local_codes = [h.get("code") for h in local[:5] if h.get("code")]
        desc = (description or "").lower()
        desc_tokens = set(re.findall(r"[a-zA-Z가-힣]{2,}", desc))
        # Generic tokens that should not alone trigger HITL override
        weak = {"상품", "제품", "물품", "테스트", "일반", "용도", "재질", "material", "usage", "function"}
        applied_warning = None
        for w in warnings:
            corrected = w.get("corrected_code")
            if not corrected:
                continue
            kws = [str(k).lower() for k in (w.get("keywords") or []) if str(k).strip()]
            strong_kws = [k for k in kws if len(k) >= 3 and k not in weak]
            wdesc = (w.get("description") or "").lower()
            w_tokens = {t for t in re.findall(r"[a-zA-Z가-힣]{2,}", wdesc) if t not in weak}
            keyword_hit = any(k in desc for k in strong_kws if len(k) >= 3)
            overlap = len(desc_tokens & w_tokens)
            related = keyword_hit or overlap >= 3
            if not related:
                continue
            # Strong office-learned local hit should not be overridden by weak/unrelated history
            in_local = any(
                corrected == c or (c and corrected[:4] == c[:4]) for c in local_codes
            )
            if top_score >= 40 and not in_local and not keyword_hit:
                continue
            if top_score >= 80 and local and local[0]["code"] != corrected and not keyword_hit:
                # learned GraphRAG rank is decisive unless history keyword clearly matches
                continue
            top = corrected
            applied_warning = w.get("id") or corrected
            break
        return {
            "agent": "HypothesisAgent",
            "proposed": top,
            "alternatives": alts,
            "rationale": "Office-scoped Local GraphRAG + related K_history warnings"
            if applied_warning
            else "Office-scoped Local GraphRAG",
            "warning_applied": applied_warning,
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
                exclusion_checks.append({"note": "contending chapter candidate", "code": hit.get("code"), "ok": True})
        verdict = "BLOCK" if str(proposal["proposed"]).startswith("9999") else "PASS"
        if verdict == "BLOCK":
            flags.append("unknown_code")
        return {
            "agent": "RegulationCritic",
            "verdict": verdict,
            "flags": flags,
            "exclusion_checks": exclusion_checks,
            "gir": ["GIR1", "GIR6"] + (["GIR3"] if "chapter_contention" in flags else []),
        }


class MetricGuardrail:
    def check(self, db: Session, office_id: int, hs_code: str, gir: list[str]) -> list[str]:
        flags: list[str] = []
        recent = (
            db.query(ClassificationResult)
            .filter(ClassificationResult.office_id == office_id)
            .order_by(ClassificationResult.id.desc())
            .limit(50)
            .all()
        )
        threshold = 0.35
        digits = re.sub(r"\D", "", hs_code or "")
        chapter = int(digits[:2]) if len(digits) >= 2 else 0
        if chapter:
            from backend.app.db.models import GuardrailState

            guard = (
                db.query(GuardrailState)
                .filter(GuardrailState.office_id == office_id, GuardrailState.chapter == chapter)
                .first()
            )
            if guard and guard.mode_collapse_threshold:
                threshold = float(guard.mode_collapse_threshold)
        if recent and len(recent) >= 10:
            same = sum(1 for r in recent if (r.recommended_hs or "")[:2] == (hs_code or "")[:2])
            if same / len(recent) > threshold:
                flags.append("mode_collapse_risk")
        if "GIR3" not in gir and len(gir) <= 1:
            flags.append("gir_avoidance_risk")
        return flags


class CustomsBrokerAgentDraft:
    """Creates system draft opinion; final judgment awaits human broker HITL."""

    def __init__(self, theta_high: float = 0.75) -> None:
        self.theta_high = theta_high
        self.kg = get_kg()

    def draft(
        self,
        db: Session,
        office_id: int,
        case: ProductCase,
        proposal: dict[str, Any],
        critic: dict[str, Any],
        metric_flags: list[str],
        search: Optional[dict[str, Any]] = None,
        routing_mode: str = "dual",
        fusion: Optional[dict[str, Any]] = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        hs = proposal["proposed"]
        digits = re.sub(r"\D", "", hs)
        chapter = int(digits[:2]) if len(digits) >= 2 else 0
        history = (
            db.query(KnowledgeHistory)
            .filter(KnowledgeHistory.office_id == office_id, KnowledgeHistory.chapter == chapter)
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
        contention = 1.0 if "chapter_contention" in critic.get("flags", []) else 0.2
        if metric_flags:
            contention = max(contention, 0.5)
        conf = 0.35 + min(len(critic.get("gir", [])), 3) * 0.12 + history_match * 0.25 - contention * 0.2
        if critic["verdict"] == "BLOCK":
            conf -= 0.4
        boost = float((fusion or {}).get("confidence_boost") or 0.0)
        conf = max(0.05, min(0.98, conf + boost))
        tier = "lightweight" if conf >= self.theta_high and "mode_collapse_risk" not in metric_flags else "deep"
        grade = "High" if conf >= 0.75 else ("Medium" if conf >= 0.45 else "Low")
        rate = self.kg.tariff_rate(hs)
        search = search or {"local": [], "global": []}
        brief = build_broker_brief(
            description=case.description,
            material=case.material,
            usage=case.function,
            recommended_hs=hs,
            alternatives=proposal.get("alternatives", []),
            local_hits=search.get("local") or [],
            global_hits=search.get("global") or [],
            gir=critic.get("gir", []),
            exclusion_checks=critic.get("exclusion_checks", []),
            confidence=conf,
            confidence_grade=grade,
            review_tier=tier,
            metric_flags=metric_flags,
            routing_mode=routing_mode,
            fusion=fusion,
        )
        delta = {
            "original_code": hs,
            "corrected_code": hs,
            "overridden": False,
            "reason": "pending_broker_review",
            "tariff_impact": {"original_rate": rate, "corrected_rate": rate, "fta_eligible": False},
            "chapter": chapter,
            "gir_applied": critic.get("gir", []),
            "similar_cases": [s.get("id") for s in similar if isinstance(s, dict)],
        }
        opinion = {
            "product_summary": brief.get("product_understanding") or case.description,
            "candidate_codes": [hs] + proposal.get("alternatives", []),
            "gir_rationale": brief.get("recommended", {}).get("gir_basis")
            or f"적용 GIR: {', '.join(critic.get('gir', []))}",
            "exclusion_summary": brief.get("exclusion_summary")
            or "; ".join(e.get("note", "") for e in critic.get("exclusion_checks", []))
            or "배제 규칙 위반 미검출",
            "tariff_info": delta["tariff_impact"],
            "similar_cases": similar[:3],
            "broker_opinion": brief.get("narrative_ko")
            or "시스템 초안 — 관세사 HITL 검토 대기",
            "confidence_grade": grade,
            "auto_approved": False,
            "review_status": "pending_broker",
            "broker_brief": brief,
            "selection_rationale": brief.get("recommended", {}).get("why_selected", ""),
            "fusion": brief.get("fusion") or {},
        }
        meta = {
            "confidence": conf,
            "review_tier": tier,
            "status": "pending_broker" if critic["verdict"] != "BLOCK" else "blocked",
            "final_hs": hs,
            "contention_score": contention,
        }
        return meta, opinion, delta


class ClassificationPipeline:
    def __init__(self) -> None:
        settings = get_settings()
        self.kg = get_kg()
        self.hypothesis = HypothesisAgent()
        self.critic = RegulationCritic()
        self.guardrail = MetricGuardrail()
        self.broker_draft = CustomsBrokerAgentDraft(theta_high=settings.theta_high)

    def _warnings(self, db: Session, office_id: int, description: str) -> list[dict]:
        tokens = re.findall(r"[a-zA-Z가-힣]{2,}", description.lower())
        category = tokens[0] if tokens else "general"
        rows = (
            db.query(KnowledgeHistory)
            .filter(KnowledgeHistory.office_id == office_id, KnowledgeHistory.product_category == category)
            .order_by(KnowledgeHistory.id.desc())
            .limit(5)
            .all()
        )
        if not rows:
            rows = (
                db.query(KnowledgeHistory)
                .filter(KnowledgeHistory.office_id == office_id)
                .order_by(KnowledgeHistory.id.desc())
                .limit(5)
                .all()
            )
        return [r.payload for r in rows]

    def _route(self, description: str) -> str:
        tokens = set(re.findall(r"[a-zA-Z가-힣0-9]+", description.lower()))
        if tokens & {"or", "and", "kit", "set", "복합", "세트"} or len(tokens) > 12:
            return "dual"
        return "local_only" if len(tokens) <= 6 else "dual"

    def classify(
        self,
        db: Session,
        case: ProductCase,
        office_id: int,
        closed_loop: bool = True,
        force_routing: Optional[str] = None,
    ) -> ClassificationOutput:
        if not self.kg.loaded:
            self.kg.load_from_db(db)
        self.kg.refresh_office_weights(db, office_id)

        routing = force_routing or self._route(case.description)
        search = self.kg.dual_channel_search(case.description, routing=routing, office_id=office_id)
        warnings = self._warnings(db, office_id, case.description) if closed_loop else []
        proposal = self.hypothesis.propose(case.description, search, warnings)

        # GraphRAG first, then GPT co-search/merge for higher accuracy
        fusion = co_recommend(
            description=case.description,
            material=case.material,
            usage=case.function,
            search=search,
            proposal=proposal,
        )
        proposal = {
            **proposal,
            "proposed": fusion.get("proposed") or proposal.get("proposed"),
            "alternatives": fusion.get("alternatives") or proposal.get("alternatives") or [],
            "fusion": fusion.get("fusion"),
            "gpt_recommend": (fusion.get("gpt") or {}),
        }

        critic = self.critic.critique(proposal, search)
        metric_flags = self.guardrail.check(db, office_id, proposal["proposed"], critic.get("gir", []))
        review, opinion, delta = self.broker_draft.draft(
            db,
            office_id,
            case,
            proposal,
            critic,
            metric_flags,
            search=search,
            routing_mode=routing,
            fusion=fusion,
        )

        trajectory = [
            {"step": "retrieve", "routing": routing, "local_n": len(search["local"]), "global_n": len(search["global"])},
            {"step": "hypothesize", **{k: v for k, v in proposal.items() if k != "gpt_recommend"}},
            {
                "step": "gpt_co_recommend",
                "fusion": fusion.get("fusion"),
                "gpt_hs": (fusion.get("gpt") or {}).get("recommended_hs"),
                "gpt_confidence": (fusion.get("gpt") or {}).get("confidence"),
                "model": (fusion.get("gpt") or {}).get("model") or get_settings().openai_model,
            },
            {"step": "critique", **critic},
            {"step": "guardrail", "flags": metric_flags},
            {"step": "system_draft", **review},
        ]

        result = ClassificationResult(
            office_id=office_id,
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

        db.add(
            OpinionReport(
                office_id=office_id,
                classification_id=result.id,
                product_summary=opinion["product_summary"],
                candidate_codes=opinion["candidate_codes"],
                gir_rationale=opinion["gir_rationale"],
                exclusion_summary=opinion["exclusion_summary"],
                tariff_info=opinion["tariff_info"],
                similar_cases=opinion["similar_cases"],
                broker_opinion=opinion["broker_opinion"],
                confidence_grade=opinion["confidence_grade"],
                auto_approved=False,
                review_status="pending_broker",
            )
        )
        db.add(
            CorrectionDelta(
                office_id=office_id,
                classification_id=result.id,
                original_code=delta["original_code"],
                corrected_code=delta["corrected_code"],
                overridden=False,
                reason=delta["reason"],
                tariff_impact=delta["tariff_impact"],
                chapter=delta["chapter"],
                gir_applied=delta["gir_applied"],
                similar_cases=delta["similar_cases"],
                incorporated=False,
            )
        )
        db.commit()
        db.refresh(result)

        return ClassificationOutput(
            classification_id=result.id,
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
