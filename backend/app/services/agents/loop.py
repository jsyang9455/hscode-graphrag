"""Runtime multi-agent loop: blind tester → evaluator → supervisor."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.db.models import (
    BrokerOpinionFeedback,
    ClassificationResult,
    ExperimentRun,
    KnowledgeHistory,
    ProductCase,
    WorkDocument,
)
from backend.app.services.classification.pipeline import ClassificationPipeline
from backend.app.services.learning.adaptive import after_office_learning, rebuild_office_model
from backend.app.services.metrics.eval import compute_metrics


# Stable synthetic probes for blind external-style testing when office data is sparse.
DEFAULT_BLIND_PROBES = [
    {"description": "히알루론산 수분 크림", "material": "cream", "function": "skin care", "expected_hs": "3304.99"},
    {"description": "면 티셔츠", "material": "cotton", "function": "clothing", "expected_hs": "6109"},
    {"description": "스테인리스 보온병 500ml", "material": "stainless steel", "function": "drinkware", "expected_hs": "9617"},
    {"description": "노트북 컴퓨터", "material": "electronics", "function": "computing", "expected_hs": "8471.30"},
    {"description": "가죽 지갑", "material": "leather", "function": "accessory", "expected_hs": "4202"},
]


class BlindTesterAgent:
    """Acts like an external user: submits classify requests without seeing ground truth."""

    role = "blind_tester"

    def run(
        self,
        db: Session,
        *,
        office_id: int,
        closed_loop: bool = True,
        include_office_cases: bool = True,
        limit: int = 12,
    ) -> dict[str, Any]:
        pipe = ClassificationPipeline()
        probes: list[dict[str, Any]] = []

        if include_office_cases:
            cases = (
                db.query(ProductCase)
                .filter(ProductCase.office_id == office_id)
                .order_by(ProductCase.id.desc())
                .limit(limit)
                .all()
            )
            for case in cases:
                expected = case.ground_truth_hs
                if not expected:
                    # fall back to latest broker-confirmed final_hs
                    clf = (
                        db.query(ClassificationResult)
                        .filter(ClassificationResult.case_id == case.id)
                        .order_by(ClassificationResult.id.desc())
                        .first()
                    )
                    if clf and clf.status in {"broker_confirmed", "corrected"} and clf.final_hs:
                        expected = clf.final_hs
                probes.append(
                    {
                        "source": "office_case",
                        "case_id": case.id,
                        "description": case.description,
                        "material": case.material,
                        "function": case.function,
                        "expected_hs": expected,
                    }
                )

        # Always include canonical blind probes (external tester set)
        for p in DEFAULT_BLIND_PROBES:
            probes.append({**p, "source": "blind_default", "case_id": None})

        # de-dupe by description
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for p in probes:
            key = (p.get("description") or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(p)
            if len(unique) >= limit:
                break

        predictions: list[dict[str, Any]] = []
        for p in unique:
            t0 = time.perf_counter()
            case = ProductCase(
                office_id=office_id,
                external_id=f"blind-{uuid.uuid4().hex[:10]}",
                description=p["description"],
                material=p.get("material"),
                function=p.get("function"),
                ground_truth_hs=None,  # blind: do not expose GT to pipeline persistence as truth for scoring path
                difficulty="blind_test",
            )
            db.add(case)
            db.flush()
            out = pipe.classify(db, case, office_id=office_id, closed_loop=closed_loop)
            elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
            predictions.append(
                {
                    "case_id": case.id,
                    "classification_id": out.classification_id,
                    "description": p["description"],
                    "source": p["source"],
                    "expected_hs": p.get("expected_hs"),
                    "predicted_hs": out.recommended_hs,
                    "confidence": out.confidence,
                    "status": out.status,
                    "elapsed_ms": elapsed_ms,
                    "closed_loop": closed_loop,
                }
            )

        db.commit()
        return {
            "agent": self.role,
            "office_id": office_id,
            "n": len(predictions),
            "predictions": predictions,
            "ran_at": datetime.utcnow().isoformat(),
        }


class EvaluatorAgent:
    """Scores blind-tester outputs for accuracy, stability, and calibration."""

    role = "evaluator"

    def evaluate(self, blind_result: dict[str, Any], office_metrics: dict[str, Any] | None = None) -> dict[str, Any]:
        preds = blind_result.get("predictions") or []
        scored = []
        prefix4 = prefix6 = exact = 0
        labeled = 0
        conf_sum = 0.0
        latency = []

        for p in preds:
            exp = (p.get("expected_hs") or "").strip()
            pred = (p.get("predicted_hs") or "").strip()
            conf_sum += float(p.get("confidence") or 0)
            latency.append(float(p.get("elapsed_ms") or 0))
            row = {**p, "label_available": bool(exp)}
            if exp and pred:
                labeled += 1
                e_digits = "".join(ch for ch in exp if ch.isdigit())
                p_digits = "".join(ch for ch in pred if ch.isdigit())
                row["match_chapter"] = e_digits[:2] == p_digits[:2] if len(e_digits) >= 2 and len(p_digits) >= 2 else False
                row["match_prefix4"] = e_digits[:4] == p_digits[:4] if len(e_digits) >= 4 and len(p_digits) >= 4 else False
                row["match_prefix6"] = e_digits[:6] == p_digits[:6] if len(e_digits) >= 6 and len(p_digits) >= 6 else False
                row["match_exact"] = exp == pred or (len(e_digits) >= 6 and e_digits[:6] == p_digits[:6] and exp.replace(".", "")[:6] == pred.replace(".", "")[:6])
                if row["match_prefix4"]:
                    prefix4 += 1
                if row["match_prefix6"]:
                    prefix6 += 1
                if row["match_exact"] or row["match_prefix6"]:
                    exact += 1
            scored.append(row)

        n = len(preds)
        metrics = {
            "n": n,
            "labeled": labeled,
            "chapter_hit_rate": round(sum(1 for s in scored if s.get("match_chapter")) / labeled, 4) if labeled else None,
            "prefix4_hit_rate": round(prefix4 / labeled, 4) if labeled else None,
            "prefix6_hit_rate": round(prefix6 / labeled, 4) if labeled else None,
            "top1_proxy": round(exact / labeled, 4) if labeled else None,
            "avg_confidence": round(conf_sum / n, 4) if n else 0.0,
            "avg_latency_ms": round(sum(latency) / len(latency), 1) if latency else 0.0,
            "p95_latency_ms": round(sorted(latency)[max(0, int(len(latency) * 0.95) - 1)], 1) if latency else 0.0,
            "office_metrics": office_metrics or {},
        }

        # Stability / quality gates
        gates = {
            "has_predictions": n >= 3,
            "prefix4_ok": (metrics["prefix4_hit_rate"] is None) or metrics["prefix4_hit_rate"] >= 0.5,
            "latency_ok": metrics["avg_latency_ms"] < 8000,
            "confidence_ok": 0.15 <= metrics["avg_confidence"] <= 0.95,
        }
        score = 0.0
        weights = {"has_predictions": 0.15, "prefix4_ok": 0.45, "latency_ok": 0.2, "confidence_ok": 0.2}
        for k, w in weights.items():
            if gates[k]:
                score += w
        if metrics["prefix4_hit_rate"] is not None:
            score = min(1.0, score * 0.55 + metrics["prefix4_hit_rate"] * 0.45)

        return {
            "agent": self.role,
            "metrics": metrics,
            "gates": gates,
            "quality_score": round(score, 4),
            "passed": score >= 0.55 and gates["has_predictions"] and gates["latency_ok"],
            "scored_predictions": scored,
            "ran_at": datetime.utcnow().isoformat(),
        }


class SupervisorAgent:
    """Receives evaluator report, remediates (relearn), and records experiment runs."""

    role = "supervisor"

    def __init__(self) -> None:
        self.blind = BlindTesterAgent()
        self.eval = EvaluatorAgent()

    def run_cycle(
        self,
        db: Session,
        *,
        office_id: int,
        auto_remediate: bool = True,
        limit: int = 10,
    ) -> dict[str, Any]:
        # 1) Ensure model is warm
        model_before = rebuild_office_model(db, office_id)

        # 2) Blind external-style test
        blind = self.blind.run(db, office_id=office_id, closed_loop=True, limit=limit)

        # 3) Evaluate
        office_metrics = compute_metrics(db, office_id=office_id)
        evaluation = self.eval.evaluate(blind, office_metrics=office_metrics)

        remediations: list[dict[str, Any]] = []
        model_after: Optional[dict[str, Any]] = None

        # 4) Remediate if unstable / underperforming
        if auto_remediate and not evaluation["passed"]:
            remediations.append(
                {
                    "action": "rebuild_office_model",
                    "reason": "evaluator quality gate failed",
                    "quality_score": evaluation["quality_score"],
                }
            )
            model_after = after_office_learning(db, office_id=office_id, run_probe=True)
            # re-blind after remediation (smaller set)
            blind2 = self.blind.run(db, office_id=office_id, closed_loop=True, limit=min(6, limit))
            evaluation2 = self.eval.evaluate(blind2, office_metrics=compute_metrics(db, office_id=office_id))
            remediations.append(
                {
                    "action": "retest_after_relearn",
                    "before_score": evaluation["quality_score"],
                    "after_score": evaluation2["quality_score"],
                    "improved": evaluation2["quality_score"] >= evaluation["quality_score"],
                }
            )
            evaluation = evaluation2
            blind = blind2
        else:
            model_after = model_before

        plan = self._design_plan(evaluation, model_after or model_before, remediations)

        run = ExperimentRun(
            office_id=office_id,
            name=f"blind-eval-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
            experiment_type="blind_supervisor_cycle",
            config={
                "limit": limit,
                "auto_remediate": auto_remediate,
                "model_before": {
                    "weight_rows": model_before.get("weight_rows"),
                    "phrase_overlay": model_before.get("phrase_overlay"),
                },
            },
            metrics={
                "evaluation": {
                    "quality_score": evaluation["quality_score"],
                    "passed": evaluation["passed"],
                    "metrics": evaluation["metrics"],
                    "gates": evaluation["gates"],
                },
                "blind_n": blind.get("n"),
                "remediations": remediations,
                "plan": plan,
            },
            status="completed" if evaluation["passed"] else "needs_attention",
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        return {
            "agent": self.role,
            "experiment_run_id": run.id,
            "status": run.status,
            "blind": {"n": blind.get("n"), "predictions": blind.get("predictions")},
            "evaluation": evaluation,
            "remediations": remediations,
            "model": model_after,
            "plan": plan,
            "learning_stats": {
                "broker_feedbacks": db.query(BrokerOpinionFeedback)
                .filter(BrokerOpinionFeedback.office_id == office_id)
                .count(),
                "learned_docs": db.query(WorkDocument)
                .filter(WorkDocument.office_id == office_id, WorkDocument.status == "learned")
                .count(),
                "knowledge_history": db.query(KnowledgeHistory)
                .filter(KnowledgeHistory.office_id == office_id)
                .count(),
            },
        }

    def _design_plan(
        self,
        evaluation: dict[str, Any],
        model: dict[str, Any],
        remediations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        metrics = evaluation.get("metrics") or {}
        actions: list[str] = []
        if not evaluation.get("passed"):
            actions.append("의견서·업무자료 추가 학습 후 재검증")
            if (metrics.get("prefix4_hit_rate") or 0) < 0.5:
                actions.append("핵심 상품군 블라인드 프로브에 대한 관세사 확정 HS 보강")
            if not metrics.get("latency_ok", True) and metrics.get("avg_latency_ms", 0) > 8000:
                actions.append("검색 캐시·적재 상태 점검")
        if (model.get("weight_rows") or 0) < 5:
            actions.append("사무실 학습 샘플이 부족합니다. 업무자료/의견서를 더 반영하세요.")
        if not actions:
            actions.append("현재 품질 게이트 통과 — 주기적 블라인드 검증 유지")

        return {
            "summary": "안정성·성능 점검 결과 기반 운영 계획",
            "quality_score": evaluation.get("quality_score"),
            "passed": evaluation.get("passed"),
            "actions": actions,
            "top_patterns": (model.get("top_patterns") or [])[:5],
            "remediation_count": len(remediations),
        }
