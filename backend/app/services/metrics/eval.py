"""Evaluation metrics for empirical experiments (ESA, CIR, RVR, Top-1, etc.)."""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import ClassificationResult, CorrectionDelta, ProductCase


def compute_metrics(db: Session, session_prefix: str | None = None, office_id: int | None = None) -> dict[str, Any]:
    q = db.query(ClassificationResult)
    if office_id is not None:
        q = q.filter(ClassificationResult.office_id == office_id)
    results = q.all()
    if not results:
        return {
            "n": 0,
            "top1": 0.0,
            "esa": 0.0,
            "rvr": 0.0,
            "cir": 0.0,
            "escalation_rate": 0.0,
            "avg_confidence": 0.0,
            "mode_collapse_flags": 0,
        }

    cases = {c.id: c for c in db.query(ProductCase).all()}
    deltas = {d.classification_id: d for d in db.query(CorrectionDelta).all()}

    n = len(results)
    top1_hits = 0
    esa_hits = 0
    violations = 0
    deep = 0
    conf_sum = 0.0
    mode_flags = 0

    for r in results:
        case = cases.get(r.case_id)
        conf_sum += r.confidence
        if r.review_tier == "deep":
            deep += 1
        if "mode_collapse_risk" in (r.metric_flags or []):
            mode_flags += 1
        if case and case.ground_truth_hs:
            if r.final_hs == case.ground_truth_hs:
                top1_hits += 1
            if r.recommended_hs == case.ground_truth_hs:
                esa_hits += 1
            if r.recommended_hs != case.ground_truth_hs:
                violations += 1

    # CIR: among overridden deltas, fraction later auto-approved on similar category
    overridden = [d for d in deltas.values() if d.overridden]
    incorporated_success = 0
    for d in overridden:
        later = [
            r
            for r in results
            if r.id > d.classification_id and r.status == "auto_approved" and r.final_hs == d.corrected_code
        ]
        if later:
            incorporated_success += 1
    cir = incorporated_success / len(overridden) if overridden else 0.0

    return {
        "n": n,
        "top1": round(top1_hits / n, 4) if n else 0.0,
        "esa": round(esa_hits / n, 4) if n else 0.0,
        "rvr": round(violations / n, 4) if n else 0.0,
        "cir": round(cir, 4),
        "escalation_rate": round(deep / n, 4) if n else 0.0,
        "avg_confidence": round(conf_sum / n, 4) if n else 0.0,
        "mode_collapse_flags": mode_flags,
        "override_rate": round(len(overridden) / n, 4) if n else 0.0,
        "chapter_distribution": dict(
            Counter(r.final_hs[:2] for r in results)
        ),
    }
