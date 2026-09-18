"""Evaluation metrics for empirical experiments (ESA, CIR, RVR, Top-1, etc.).

Paper-oriented aggregates include Wilson 95% CIs, prefix hit rates,
confidence histograms, and daily time series suitable for figures/tables.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import (
    BrokerOpinionFeedback,
    ClassificationResult,
    CorrectionDelta,
    ExperimentRun,
    ProductCase,
    TenantKeywordWeight,
)


def _digits(code: str | None) -> str:
    return "".join(ch for ch in (code or "") if ch.isdigit())


def _prefix_match(a: str | None, b: str | None, n: int) -> bool:
    da, db = _digits(a), _digits(b)
    if len(da) < n or len(db) < n:
        return False
    return da[:n] == db[:n]


def wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple[float | None, float | None]:
    """Wilson score interval for a binomial proportion (paper-friendly 95% CI)."""
    if n <= 0:
        return None, None
    p = hits / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    lo = max(0.0, (centre - margin) / denom)
    hi = min(1.0, (centre + margin) / denom)
    return round(lo, 4), round(hi, 4)


def _rate_block(hits: int, n: int) -> dict[str, Any]:
    rate = round(hits / n, 4) if n else None
    lo, hi = wilson_ci(hits, n) if n else (None, None)
    return {"hits": hits, "n": n, "rate": rate, "ci95": [lo, hi]}


def _day_key(dt: datetime | None) -> str:
    if not dt:
        return "unknown"
    return dt.strftime("%Y-%m-%d")


def compute_metrics(db: Session, session_prefix: str | None = None, office_id: int | None = None) -> dict[str, Any]:
    q = db.query(ClassificationResult)
    if office_id is not None:
        q = q.filter(ClassificationResult.office_id == office_id)
    results = q.order_by(ClassificationResult.created_at.asc()).all()

    empty = {
        "n": 0,
        "top1": 0.0,
        "esa": 0.0,
        "rvr": 0.0,
        "cir": 0.0,
        "escalation_rate": 0.0,
        "avg_confidence": 0.0,
        "mode_collapse_flags": 0,
        "override_rate": 0.0,
        "chapter_distribution": {},
        "paper": {
            "definitions": _metric_definitions(),
            "accuracy": {},
            "operations": {},
            "distributions": {
                "confidence_histogram": [],
                "chapter_top": [],
                "status": [],
                "review_tier": [],
            },
            "timeseries": {"daily": []},
            "learning": {},
            "experiments": [],
            "generated_at": datetime.utcnow().isoformat() + "Z",
        },
    }
    if not results:
        empty["paper"]["learning"] = _learning_block(db, office_id)
        empty["paper"]["experiments"] = _experiment_block(db, office_id)
        return empty

    case_ids = {r.case_id for r in results}
    cases = {
        c.id: c
        for c in db.query(ProductCase).filter(ProductCase.id.in_(case_ids)).all()
    } if case_ids else {}
    class_ids = [r.id for r in results]
    deltas = {
        d.classification_id: d
        for d in db.query(CorrectionDelta)
        .filter(CorrectionDelta.classification_id.in_(class_ids))
        .all()
    } if class_ids else {}

    n = len(results)
    top1_hits = esa_hits = violations = 0
    p4_hits = p6_hits = ch_hits = 0
    labeled = 0
    deep = 0
    conf_sum = 0.0
    mode_flags = 0
    status_c: Counter[str] = Counter()
    tier_c: Counter[str] = Counter()
    chapter_c: Counter[str] = Counter()
    conf_bins = [0] * 5  # 0-.2 .2-.4 .4-.6 .6-.8 .8-1
    daily: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "conf_sum": 0.0, "labeled": 0, "top1": 0, "deep": 0}
    )

    for r in results:
        case = cases.get(r.case_id)
        conf = float(r.confidence or 0.0)
        conf_sum += conf
        status_c[r.status or "unknown"] += 1
        tier_c[r.review_tier or "unknown"] += 1
        chapter_c[(r.final_hs or "")[:2] or "??"] += 1
        bin_i = min(4, max(0, int(conf * 5) if conf < 1.0 else 4))
        conf_bins[bin_i] += 1
        if r.review_tier == "deep":
            deep += 1
        if "mode_collapse_risk" in (r.metric_flags or []):
            mode_flags += 1

        day = _day_key(r.created_at)
        daily[day]["n"] += 1
        daily[day]["conf_sum"] += conf
        if r.review_tier == "deep":
            daily[day]["deep"] += 1

        gt = case.ground_truth_hs if case else None
        if gt:
            labeled += 1
            daily[day]["labeled"] += 1
            if r.final_hs == gt:
                top1_hits += 1
                daily[day]["top1"] += 1
            if r.recommended_hs == gt:
                esa_hits += 1
            else:
                violations += 1
            if _prefix_match(r.final_hs, gt, 4):
                p4_hits += 1
            if _prefix_match(r.final_hs, gt, 6):
                p6_hits += 1
            if _prefix_match(r.final_hs, gt, 2):
                ch_hits += 1

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

    timeseries = []
    for day in sorted(k for k in daily if k != "unknown"):
        row = daily[day]
        ln = row["labeled"] or 0
        timeseries.append(
            {
                "date": day,
                "n": row["n"],
                "avg_confidence": round(row["conf_sum"] / row["n"], 4) if row["n"] else 0.0,
                "escalation_rate": round(row["deep"] / row["n"], 4) if row["n"] else 0.0,
                "top1": round(row["top1"] / ln, 4) if ln else None,
                "labeled": ln,
            }
        )

    chapter_top = []
    for ch, cnt in chapter_c.most_common(12):
        chapter_top.append({"chapter": ch, "count": cnt, "share": round(cnt / n, 4)})

    hist_labels = ["0.0–0.2", "0.2–0.4", "0.4–0.6", "0.6–0.8", "0.8–1.0"]
    confidence_histogram = [
        {"bin": hist_labels[i], "count": conf_bins[i], "share": round(conf_bins[i] / n, 4)}
        for i in range(5)
    ]

    paper = {
        "definitions": _metric_definitions(),
        "accuracy": {
            "n_total": n,
            "n_labeled": labeled,
            "top1": _rate_block(top1_hits, labeled),
            "prefix4": _rate_block(p4_hits, labeled),
            "prefix6": _rate_block(p6_hits, labeled),
            "chapter": _rate_block(ch_hits, labeled),
            "esa": _rate_block(esa_hits, labeled),
            "rvr": _rate_block(violations, labeled),
            "cir": {
                "rate": round(cir, 4),
                "n_overrides": len(overridden),
                "incorporated": incorporated_success,
            },
        },
        "operations": {
            "escalation_rate": round(deep / n, 4),
            "override_rate": round(len(overridden) / n, 4),
            "avg_confidence": round(conf_sum / n, 4),
            "mode_collapse_flags": mode_flags,
            "pending_broker": status_c.get("pending_broker", 0),
            "auto_approved": status_c.get("auto_approved", 0),
            "corrected": status_c.get("corrected", 0),
        },
        "distributions": {
            "confidence_histogram": confidence_histogram,
            "chapter_top": chapter_top,
            "status": [{"key": k, "count": v, "share": round(v / n, 4)} for k, v in status_c.most_common()],
            "review_tier": [{"key": k, "count": v, "share": round(v / n, 4)} for k, v in tier_c.most_common()],
        },
        "timeseries": {"daily": timeseries[-30:]},
        "learning": _learning_block(db, office_id),
        "experiments": _experiment_block(db, office_id),
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    return {
        "n": n,
        "top1": round(top1_hits / labeled, 4) if labeled else 0.0,
        "esa": round(esa_hits / labeled, 4) if labeled else 0.0,
        "rvr": round(violations / labeled, 4) if labeled else 0.0,
        "cir": round(cir, 4),
        "escalation_rate": round(deep / n, 4),
        "avg_confidence": round(conf_sum / n, 4),
        "mode_collapse_flags": mode_flags,
        "override_rate": round(len(overridden) / n, 4),
        "chapter_distribution": dict(chapter_c),
        "n_labeled": labeled,
        "prefix4": round(p4_hits / labeled, 4) if labeled else 0.0,
        "prefix6": round(p6_hits / labeled, 4) if labeled else 0.0,
        "chapter_hit": round(ch_hits / labeled, 4) if labeled else 0.0,
        "paper": paper,
    }


def _metric_definitions() -> dict[str, str]:
    return {
        "Top-1": "최종 HS가 정답(ground truth)과 완전 일치하는 비율",
        "Prefix-4 / Prefix-6": "4자리(호)·6자리(소호) 접두 일치율 — HS 계층 정확도",
        "Chapter": "류(2자리) 일치율",
        "ESA": "시스템 최초 추천(recommended)이 정답과 일치하는 비율 (Early Suggestion Accuracy)",
        "RVR": "추천이 정답과 불일치한 비율 (Recommendation Violation Rate)",
        "CIR": "관세사 수정 이후 동일 코드가 자동승인으로 재현된 비율 (Correction Incorporation Rate)",
        "Escalation": "deep review tier 비율",
        "CI95": "Wilson score 95% 신뢰구간 (이항 비율)",
    }


def _learning_block(db: Session, office_id: int | None) -> dict[str, Any]:
    wq = db.query(TenantKeywordWeight)
    fq = db.query(BrokerOpinionFeedback)
    if office_id is not None:
        wq = wq.filter(TenantKeywordWeight.office_id == office_id)
        fq = fq.filter(BrokerOpinionFeedback.office_id == office_id)
    weights = wq.order_by(TenantKeywordWeight.weight.desc()).limit(40).all()
    feedbacks = fq.all()
    n_fb = len(feedbacks)
    changed = sum(1 for f in feedbacks if f.hs_changed)
    wvals = [float(w.weight) for w in weights]
    return {
        "weight_pairs": len(weights),
        "avg_weight": round(sum(wvals) / len(wvals), 4) if wvals else 0.0,
        "max_weight": round(max(wvals), 4) if wvals else 0.0,
        "feedback_n": n_fb,
        "hs_change_rate": round(changed / n_fb, 4) if n_fb else 0.0,
        "top_weights": [
            {
                "keyword": w.keyword,
                "hs_code": w.hs_code,
                "weight": round(float(w.weight), 4),
                "evidence_count": w.evidence_count,
            }
            for w in weights[:12]
        ],
    }


def _experiment_block(db: Session, office_id: int | None) -> list[dict[str, Any]]:
    q = db.query(ExperimentRun)
    if office_id is not None:
        q = q.filter((ExperimentRun.office_id == office_id) | (ExperimentRun.office_id.is_(None)))
    rows = q.order_by(ExperimentRun.id.desc()).limit(8).all()
    out = []
    for r in rows:
        m = r.metrics or {}
        ev = m.get("evaluation") or m.get("final") or {}
        metrics = ev.get("metrics") if isinstance(ev, dict) else {}
        if not isinstance(metrics, dict):
            metrics = {}
        out.append(
            {
                "id": r.id,
                "name": r.name,
                "type": r.experiment_type,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "quality_score": ev.get("quality_score") if isinstance(ev, dict) else None,
                "prefix4_hit_rate": metrics.get("prefix4_hit_rate"),
                "delta_score": m.get("delta_score") or (m.get("summary") or {}).get("delta_score"),
                "improved": m.get("improved"),
            }
        )
    return out
