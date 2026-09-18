"""Online adaptive pattern learning for office-scoped GraphRAG.

When broker opinions or work documents arrive, features are mined and
TenantKeywordWeight / KnowledgeHistory are updated with evidence-weighted
online updates. The in-memory KG is refreshed immediately so the next
classify call uses the new office model.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.db.models import (
    BrokerOpinionFeedback,
    ClassificationResult,
    KnowledgeHistory,
    ProductCase,
    TenantKeywordWeight,
    WorkDocument,
)
from backend.app.services.knowledge.graph import get_kg

TOKEN_RE = re.compile(r"[A-Za-z가-힣]{2,}")
STOP = {
    "and",
    "the",
    "for",
    "with",
    "from",
    "this",
    "that",
    "material",
    "usage",
    "function",
    "제품",
    "상품",
    "물품",
    "입니다",
    "있음",
    "없음",
    "관련",
}


def tokenize(text: str) -> list[str]:
    toks = [t.lower() for t in TOKEN_RE.findall(text or "") if t.lower() not in STOP]
    return toks


def extract_features(
    *,
    description: str = "",
    material: str | None = None,
    usage: str | None = None,
    opinion: str = "",
    conditions: list[str] | None = None,
    max_features: int = 20,
) -> list[str]:
    """Mine unigrams + bigrams that represent office-specific patterns."""
    parts = [description or "", material or "", usage or "", opinion or ""]
    if conditions:
        parts.extend(conditions)
    blob = " ".join(parts)
    unigrams = tokenize(blob)
    bigrams: list[str] = []
    for a, b in zip(unigrams, unigrams[1:]):
        if a == b:
            continue
        bigrams.append(f"{a} {b}")
    # Prefer longer phrases first, then frequent unigrams
    ranked = list(dict.fromkeys(bigrams + unigrams))
    return ranked[:max_features]


def upsert_weight(
    db: Session,
    *,
    office_id: int,
    keyword: str,
    hs_code: str,
    delta: float,
    base_if_new: float = 1.25,
    max_weight: float = 5.0,
    min_weight: float = 0.15,
) -> TenantKeywordWeight:
    row = (
        db.query(TenantKeywordWeight)
        .filter(
            TenantKeywordWeight.office_id == office_id,
            TenantKeywordWeight.keyword == keyword,
            TenantKeywordWeight.hs_code == hs_code,
        )
        .first()
    )
    if row:
        # Evidence-weighted online update (diminishing returns)
        evidence = max(1, int(row.evidence_count or 1))
        step = delta / math.sqrt(evidence)
        row.weight = max(min_weight, min(max_weight, float(row.weight) + step))
        row.evidence_count = evidence + 1
        row.updated_at = datetime.utcnow()
    else:
        row = TenantKeywordWeight(
            office_id=office_id,
            keyword=keyword,
            hs_code=hs_code,
            weight=min(max_weight, max(min_weight, base_if_new)),
            evidence_count=1,
        )
        db.add(row)
    return row


def apply_pattern_learning(
    db: Session,
    *,
    office_id: int,
    features: list[str],
    target_hs: str,
    wrong_hs: str | None = None,
    source: str = "adaptive",
) -> list[dict[str, Any]]:
    """Online adaptive update toward target_hs (and soft-penalize wrong_hs)."""
    updates: list[dict[str, Any]] = []
    target_hs = (target_hs or "").strip()
    if not target_hs or not features:
        return updates

    for i, feat in enumerate(features):
        # Earlier / longer features get slightly larger steps
        boost = 0.42 if " " in feat else 0.32
        boost *= 1.0 if i < 8 else 0.7
        row = upsert_weight(
            db,
            office_id=office_id,
            keyword=feat,
            hs_code=target_hs,
            delta=boost,
            base_if_new=1.45 if " " in feat else 1.25,
        )
        updates.append(
            {
                "keyword": feat,
                "hs_code": target_hs,
                "weight": round(float(row.weight), 3),
                "evidence_count": row.evidence_count,
                "source": source,
            }
        )

    if wrong_hs and wrong_hs != target_hs:
        for feat in features[:8]:
            bad = (
                db.query(TenantKeywordWeight)
                .filter(
                    TenantKeywordWeight.office_id == office_id,
                    TenantKeywordWeight.keyword == feat,
                    TenantKeywordWeight.hs_code == wrong_hs,
                )
                .first()
            )
            if bad:
                bad.weight = max(0.15, float(bad.weight) - 0.28)
                bad.updated_at = datetime.utcnow()
                updates.append(
                    {
                        "keyword": feat,
                        "hs_code": wrong_hs,
                        "weight": round(float(bad.weight), 3),
                        "evidence_count": bad.evidence_count,
                        "source": f"{source}:down",
                    }
                )
    return updates


def upsert_knowledge_history(
    db: Session,
    *,
    office_id: int,
    key: str,
    chapter: int,
    product_category: str,
    payload: dict[str, Any],
    source: str,
    violation_type: str | None = None,
) -> KnowledgeHistory:
    row = (
        db.query(KnowledgeHistory)
        .filter(KnowledgeHistory.office_id == office_id, KnowledgeHistory.key == key)
        .first()
    )
    if row:
        row.chapter = chapter
        row.product_category = product_category
        row.payload = payload
        row.source = source
        row.violation_type = violation_type
    else:
        row = KnowledgeHistory(
            office_id=office_id,
            key=key,
            chapter=chapter,
            product_category=product_category,
            violation_type=violation_type,
            payload=payload,
            source=source,
        )
        db.add(row)
    return row


def rebuild_office_model(db: Session, office_id: int) -> dict[str, Any]:
    """Rebuild in-memory office GraphRAG overlay from persisted weights + histories."""
    kg = get_kg()
    kg.refresh_office_weights(db, office_id)
    overlay = kg.build_office_phrase_overlay(office_id)

    weights = (
        db.query(TenantKeywordWeight)
        .filter(TenantKeywordWeight.office_id == office_id)
        .order_by(TenantKeywordWeight.evidence_count.desc())
        .limit(200)
        .all()
    )
    hist_n = db.query(KnowledgeHistory).filter(KnowledgeHistory.office_id == office_id).count()
    fb_n = db.query(BrokerOpinionFeedback).filter(BrokerOpinionFeedback.office_id == office_id).count()
    doc_n = (
        db.query(WorkDocument)
        .filter(WorkDocument.office_id == office_id, WorkDocument.status == "learned")
        .count()
    )

    affinity: dict[str, Counter] = defaultdict(Counter)
    for w in weights:
        affinity[w.hs_code][w.keyword] += int(w.evidence_count or 1)

    top_patterns = []
    for hs, ctr in sorted(affinity.items(), key=lambda kv: sum(kv[1].values()), reverse=True)[:12]:
        top_patterns.append(
            {
                "hs": hs,
                "features": [k for k, _ in ctr.most_common(5)],
                "evidence": int(sum(ctr.values())),
            }
        )

    return {
        "office_id": office_id,
        "weight_rows": len(weights),
        "knowledge_history": hist_n,
        "broker_feedbacks": fb_n,
        "learned_documents": doc_n,
        "phrase_overlay": len(overlay),
        "top_patterns": top_patterns,
        "rebuilt_at": datetime.utcnow().isoformat(),
    }


def reclassify_probe_cases(
    db: Session,
    *,
    office_id: int,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Non-persisting probe: dual-channel search against recent office cases."""
    kg = get_kg()
    kg.refresh_office_weights(db, office_id)
    rows = (
        db.query(ClassificationResult)
        .filter(ClassificationResult.office_id == office_id)
        .order_by(ClassificationResult.id.desc())
        .limit(40)
        .all()
    )
    probes: list[dict[str, Any]] = []
    seen_desc: set[str] = set()
    for r in rows:
        if len(probes) >= limit:
            break
        case = db.query(ProductCase).filter(ProductCase.id == r.case_id).first()
        if not case:
            continue
        key = (case.description or "")[:120]
        if key in seen_desc:
            continue
        seen_desc.add(key)
        expected = case.ground_truth_hs or r.final_hs or r.recommended_hs
        search = kg.dual_channel_search(case.description or "", routing="dual", office_id=office_id)
        predicted = (search.get("local") or [{}])[0].get("code")
        probes.append(
            {
                "case_id": case.id,
                "description": (case.description or "")[:160],
                "expected": expected,
                "predicted": predicted,
                "match": bool(
                    expected
                    and predicted
                    and "".join(ch for ch in expected if ch.isdigit())[:6]
                    == "".join(ch for ch in predicted if ch.isdigit())[:6]
                ),
                "confidence": None,
            }
        )
    return probes


def after_office_learning(
    db: Session,
    *,
    office_id: int,
    run_probe: bool = True,
) -> dict[str, Any]:
    model = rebuild_office_model(db, office_id)
    probes = reclassify_probe_cases(db, office_id=office_id, limit=5) if run_probe else []
    hit = sum(1 for p in probes if p.get("match"))
    model["probe"] = {
        "n": len(probes),
        "prefix6_hit_rate": round(hit / len(probes), 4) if probes else None,
        "samples": probes,
    }
    return model
