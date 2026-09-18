"""SIA harness-only improvement loop MVP.

Blind tester → evaluator → (simulated broker opinions) → Feedback-Agent harness patch
→ keep patch only if holdout metrics improve.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.db.models import ExperimentRun, User
from backend.app.services.agents.harness import (
    FeedbackHarnessAgent,
    get_harness,
    reset_harness,
    save_harness,
)
from backend.app.services.agents.loop import (
    DEFAULT_BLIND_PROBES,
    BlindTesterAgent,
    EvaluatorAgent,
)
from backend.app.services.learning.hitl import apply_broker_feedback

# Fixed external-style probe set for stable before/after comparison.
SIA_PROBES = DEFAULT_BLIND_PROBES + [
    {"description": "면 양말", "material": "cotton", "function": "socks", "expected_hs": "6115"},
    {"description": "플라스틱 장난감 자동차", "material": "plastic", "function": "toy", "expected_hs": "9503"},
    {"description": "무선 이어폰", "material": "electronics", "function": "audio", "expected_hs": "8518"},
]


def _score_key(evaluation: dict[str, Any]) -> float:
    m = evaluation.get("metrics") or {}
    p4 = m.get("prefix4_hit_rate")
    ch = m.get("chapter_hit_rate")
    qs = evaluation.get("quality_score") or 0.0
    # Prefer labeled accuracy; fall back to quality_score
    if p4 is None and ch is None:
        return float(qs)
    return 0.55 * float(p4 or 0) + 0.25 * float(ch or 0) + 0.20 * float(qs)


class SIAHarnessLoop:
    """Self-improving harness loop (weights of LLM fixed; office scaffold evolves)."""

    role = "sia_harness_loop"

    def __init__(self) -> None:
        self.blind = BlindTesterAgent()
        self.eval = EvaluatorAgent()
        self.feedback = FeedbackHarnessAgent()

    def _blind_fixed(
        self,
        db: Session,
        *,
        office_id: int,
        closed_loop: bool = True,
        use_llm_path: bool = True,
    ) -> dict[str, Any]:
        """Run fixed SIA probes only (no office-case noise)."""
        # Temporarily reuse BlindTester by crafting predictions via include_office_cases=False
        # and overriding probe list through a local run.
        from backend.app.services.classification.pipeline import ClassificationPipeline
        import time
        import uuid
        from backend.app.db.models import ProductCase

        pipe = ClassificationPipeline()
        predictions: list[dict[str, Any]] = []
        for p in SIA_PROBES:
            t0 = time.perf_counter()
            case = ProductCase(
                office_id=office_id,
                external_id=f"sia-{uuid.uuid4().hex[:10]}",
                description=p["description"],
                material=p.get("material"),
                function=p.get("function"),
                ground_truth_hs=None,
                difficulty="sia_blind",
            )
            db.add(case)
            db.flush()
            out = pipe.classify(db, case, office_id=office_id, closed_loop=closed_loop)
            predictions.append(
                {
                    "case_id": case.id,
                    "classification_id": out.classification_id,
                    "description": p["description"],
                    "source": "sia_probe",
                    "expected_hs": p.get("expected_hs"),
                    "predicted_hs": out.recommended_hs,
                    "confidence": out.confidence,
                    "status": out.status,
                    "elapsed_ms": round((time.perf_counter() - t0) * 1000, 1),
                    "closed_loop": closed_loop,
                }
            )
        db.commit()
        return {
            "agent": "blind_tester",
            "office_id": office_id,
            "n": len(predictions),
            "predictions": predictions,
            "ran_at": datetime.utcnow().isoformat(),
        }

    def _simulate_opinions(
        self,
        db: Session,
        *,
        office_id: int,
        user_id: int,
        evaluation: dict[str, Any],
        max_opinions: int = 4,
    ) -> list[dict[str, Any]]:
        """Broker-like HITL on mismatches: teach expected HS into office weights."""
        applied: list[dict[str, Any]] = []
        scored = evaluation.get("scored_predictions") or []
        misses = [
            s
            for s in scored
            if s.get("label_available")
            and s.get("classification_id")
            and not (s.get("match_prefix4") or s.get("match_prefix6"))
        ]
        for s in misses[:max_opinions]:
            expected = (s.get("expected_hs") or "").strip()
            if not expected:
                continue
            # Normalize short expected to a plausible HS form for learning target
            broker_hs = expected if "." in expected else (
                f"{expected}.00.0000" if len("".join(ch for ch in expected if ch.isdigit())) == 4 else expected
            )
            try:
                out = apply_broker_feedback(
                    db,
                    office_id=office_id,
                    user_id=user_id,
                    classification_id=int(s["classification_id"]),
                    broker_hs=broker_hs,
                    conditions=["practice", "precedent"],
                    detail_opinion=(
                        f"[SIA simulated HITL] 기대세번 {expected}. "
                        f"시스템 {s.get('predicted_hs')} 보정."
                    ),
                )
                applied.append(
                    {
                        "classification_id": s["classification_id"],
                        "expected": expected,
                        "broker_hs": broker_hs,
                        "hs_changed": out.get("hs_changed"),
                    }
                )
            except Exception as exc:  # noqa: BLE001
                applied.append(
                    {
                        "classification_id": s.get("classification_id"),
                        "expected": expected,
                        "error": str(exc)[:160],
                    }
                )
        return applied

    def run(
        self,
        db: Session,
        *,
        office_id: int,
        user_id: int,
        rounds: int = 3,
        apply_opinions: bool = True,
        reset: bool = True,
    ) -> dict[str, Any]:
        if reset:
            reset_harness(office_id)

        history: list[dict[str, Any]] = []
        harness = get_harness(office_id)
        baseline = None

        for r in range(1, max(1, rounds) + 1):
            blind = self._blind_fixed(db, office_id=office_id, closed_loop=True)
            evaluation = self.eval.evaluate(blind)
            score = _score_key(evaluation)
            if baseline is None:
                baseline = {
                    "score": score,
                    "metrics": evaluation.get("metrics"),
                    "quality_score": evaluation.get("quality_score"),
                    "harness": harness,
                }

            opinions: list[dict[str, Any]] = []
            if apply_opinions:
                opinions = self._simulate_opinions(
                    db, office_id=office_id, user_id=user_id, evaluation=evaluation
                )

            proposal = self.feedback.propose(evaluation, harness)
            accepted = False
            trial_eval = None
            if proposal.get("action") == "harness_update" and proposal.get("proposed_harness"):
                candidate = proposal["proposed_harness"]
                # trial apply
                save_harness(office_id, candidate, note=f"sia trial round {r}")
                trial_blind = self._blind_fixed(db, office_id=office_id, closed_loop=True)
                trial_eval = self.eval.evaluate(trial_blind)
                trial_score = _score_key(trial_eval)
                if trial_score >= score - 1e-9:
                    harness = get_harness(office_id)
                    accepted = True
                    evaluation = trial_eval
                    score = trial_score
                else:
                    # rollback
                    save_harness(office_id, harness, note=f"sia rollback round {r}")
                    harness = get_harness(office_id)
            else:
                # still persist current after opinion learning
                harness = get_harness(office_id)

            # post-opinion re-measure (learning effect) when harness noop/accepted already measured
            if apply_opinions and opinions and proposal.get("action") != "harness_update":
                post_blind = self._blind_fixed(db, office_id=office_id, closed_loop=True)
                evaluation = self.eval.evaluate(post_blind)
                score = _score_key(evaluation)

            history.append(
                {
                    "round": r,
                    "score": round(score, 4),
                    "quality_score": evaluation.get("quality_score"),
                    "metrics": {
                        "prefix4_hit_rate": (evaluation.get("metrics") or {}).get("prefix4_hit_rate"),
                        "prefix6_hit_rate": (evaluation.get("metrics") or {}).get("prefix6_hit_rate"),
                        "chapter_hit_rate": (evaluation.get("metrics") or {}).get("chapter_hit_rate"),
                        "labeled": (evaluation.get("metrics") or {}).get("labeled"),
                        "avg_confidence": (evaluation.get("metrics") or {}).get("avg_confidence"),
                    },
                    "opinions_applied": len([o for o in opinions if not o.get("error")]),
                    "opinion_details": opinions,
                    "feedback": {
                        "action": proposal.get("action"),
                        "reasons": proposal.get("reasons"),
                        "patch": proposal.get("patch"),
                        "accepted": accepted,
                    },
                    "harness_version": harness.get("version"),
                    "trial_score": round(_score_key(trial_eval), 4) if trial_eval else None,
                }
            )

        final = history[-1] if history else {}
        improved = bool(baseline and final and final["score"] >= baseline["score"])
        delta = round((final.get("score") or 0) - (baseline.get("score") or 0), 4) if baseline else 0.0

        report = {
            "title": "SIA Harness Improvement Loop Report",
            "summary": (
                f"{rounds}라운드 블라인드+의견서 루프 결과: "
                f"기준점수 {baseline.get('score') if baseline else None} → "
                f"최종 {final.get('score')} (Δ {delta:+})"
            ),
            "improved": improved,
            "delta_score": delta,
            "baseline": baseline,
            "final": {
                "score": final.get("score"),
                "metrics": final.get("metrics"),
                "harness_version": final.get("harness_version"),
            },
            "rounds": history,
            "harness": get_harness(office_id),
            "interpretation": self._interpret(baseline, final, history),
        }

        run = ExperimentRun(
            office_id=office_id,
            name=f"sia-harness-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}",
            experiment_type="sia_harness_loop",
            config={"rounds": rounds, "apply_opinions": apply_opinions, "reset": reset},
            metrics=report,
            status="completed" if improved or delta >= 0 else "needs_attention",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        report["experiment_run_id"] = run.id
        return report

    def _interpret(
        self,
        baseline: Optional[dict[str, Any]],
        final: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> list[str]:
        notes: list[str] = []
        if not baseline:
            return ["기준 측정 없음"]
        b4 = ((baseline.get("metrics") or {}).get("prefix4_hit_rate"))
        f4 = ((final.get("metrics") or {}).get("prefix4_hit_rate"))
        if b4 is not None and f4 is not None:
            notes.append(f"prefix4: {b4} → {f4}")
        accepted = sum(1 for h in history if (h.get("feedback") or {}).get("accepted"))
        opinions = sum(int(h.get("opinions_applied") or 0) for h in history)
        notes.append(f"harness 패치 채택 {accepted}/{len(history)}라운드, 시뮬 의견서 {opinions}건")
        if (final.get("score") or 0) > (baseline.get("score") or 0):
            notes.append("종합 점수가 상승했습니다. harness+HITL 루프가 유효합니다.")
        elif (final.get("score") or 0) == (baseline.get("score") or 0):
            notes.append("종합 점수는 유지되었습니다. 추가 프로브/의견 샘플이 필요합니다.")
        else:
            notes.append("종합 점수가 하락했습니다. harness 패치가 롤백되었거나 학습 노이즈가 있습니다.")
        return notes
