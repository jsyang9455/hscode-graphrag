"""Apply broker HITL opinions into per-office GraphRAG learning stores."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import (
    BrokerOpinionFeedback,
    ClassificationResult,
    CorrectionDelta,
    GuardrailState,
    KnowledgeHistory,
    OpinionReport,
    ProductCase,
    TenantKeywordWeight,
)
from backend.app.services.knowledge.graph import get_kg


CONDITION_LABELS = {
    "hs_accurate": "HS코드 정확",
    "tariff_benefit": "관세율 혜택/최적화",
    "gir_interpretation": "GIR 해석 차이",
    "practice": "실무 관행",
    "precedent": "유사 판례/이력",
    "exclusion_note": "배제·포함 주석",
}


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[a-zA-Z가-힣]{2,}", text.lower())]


def apply_broker_feedback(
    db: Session,
    *,
    office_id: int,
    user_id: int,
    classification_id: int,
    broker_hs: str,
    conditions: list[str],
    detail_opinion: str,
) -> dict[str, Any]:
    clf = (
        db.query(ClassificationResult)
        .filter(
            ClassificationResult.id == classification_id,
            ClassificationResult.office_id == office_id,
        )
        .first()
    )
    if not clf:
        raise ValueError("classification not found for office")

    existing = (
        db.query(BrokerOpinionFeedback)
        .filter(BrokerOpinionFeedback.classification_id == classification_id)
        .first()
    )
    if existing:
        raise ValueError("broker feedback already submitted")

    system_hs = clf.recommended_hs
    broker_hs = broker_hs.strip()
    hs_changed = system_hs != broker_hs
    primary_reason = conditions[0] if conditions else ("tariff_benefit" if hs_changed else "hs_accurate")

    case = db.query(ProductCase).filter(ProductCase.id == clf.case_id).first()
    desc = case.description if case else ""
    tokens = _tokens(desc)[:12]

    # 1) Persist HITL feedback
    fb = BrokerOpinionFeedback(
        office_id=office_id,
        classification_id=classification_id,
        user_id=user_id,
        system_hs=system_hs,
        broker_hs=broker_hs,
        hs_changed=hs_changed,
        conditions=conditions,
        detail_opinion=detail_opinion,
        applied_to_learning=False,
    )
    db.add(fb)

    # 2) Update classification final outcome
    clf.final_hs = broker_hs
    clf.status = "corrected" if hs_changed else "broker_confirmed"

    # 3) Update opinion report
    op = db.query(OpinionReport).filter(OpinionReport.classification_id == classification_id).first()
    if op:
        op.review_status = "broker_reviewed"
        op.auto_approved = False
        labels = [CONDITION_LABELS.get(c, c) for c in conditions]
        op.broker_opinion = (
            f"[관세사 검토] 시스템 {system_hs} → 확정 {broker_hs}. "
            f"조건: {', '.join(labels)}. 상세: {detail_opinion[:500]}"
        )

    # 4) Correction delta (office scoped)
    kg = get_kg()
    chapter = int(re.sub(r"\D", "", broker_hs)[:2] or "0")
    delta = db.query(CorrectionDelta).filter(CorrectionDelta.classification_id == classification_id).first()
    if not delta:
        delta = CorrectionDelta(
            office_id=office_id,
            classification_id=classification_id,
            original_code=system_hs,
            corrected_code=broker_hs,
            overridden=hs_changed,
            reason=primary_reason,
            tariff_impact={
                "original_rate": kg.tariff_rate(system_hs),
                "corrected_rate": kg.tariff_rate(broker_hs),
                "fta_eligible": "tariff_benefit" in conditions,
            },
            chapter=chapter,
            gir_applied=clf.gir_applied or [],
            similar_cases=[],
            incorporated=True,
        )
        db.add(delta)
    else:
        delta.office_id = office_id
        delta.original_code = system_hs
        delta.corrected_code = broker_hs
        delta.overridden = hs_changed
        delta.reason = primary_reason
        delta.incorporated = True

    # 5) K_history (office scoped learning memory)
    category = tokens[0] if tokens else "general"
    kh = KnowledgeHistory(
        office_id=office_id,
        key=f"{office_id}:{chapter}:{category}:{primary_reason}",
        chapter=chapter,
        product_category=category,
        violation_type=primary_reason,
        payload={
            "original_code": system_hs,
            "corrected_code": broker_hs,
            "overridden": hs_changed,
            "reason": primary_reason,
            "conditions": conditions,
            "detail_opinion": detail_opinion,
            "tokens": tokens,
            "id": f"broker-fb-{classification_id}",
        },
        source="broker_hitl",
    )
    db.add(kh)

    # 6) Tenant keyword weights — GraphRAG local search boost
    weight_updates = []
    for tok in tokens:
        row = (
            db.query(TenantKeywordWeight)
            .filter(
                TenantKeywordWeight.office_id == office_id,
                TenantKeywordWeight.keyword == tok,
                TenantKeywordWeight.hs_code == broker_hs,
            )
            .first()
        )
        if row:
            row.weight = min(5.0, float(row.weight) + 0.35)
            row.evidence_count += 1
            row.updated_at = datetime.utcnow()
        else:
            row = TenantKeywordWeight(
                office_id=office_id,
                keyword=tok,
                hs_code=broker_hs,
                weight=1.5 if hs_changed else 1.2,
                evidence_count=1,
            )
            db.add(row)
        weight_updates.append({"keyword": tok, "hs_code": broker_hs, "weight": row.weight})

    # If system was wrong, gently down-weight system mapping for same tokens
    if hs_changed:
        for tok in tokens[:6]:
            bad = (
                db.query(TenantKeywordWeight)
                .filter(
                    TenantKeywordWeight.office_id == office_id,
                    TenantKeywordWeight.keyword == tok,
                    TenantKeywordWeight.hs_code == system_hs,
                )
                .first()
            )
            if bad:
                bad.weight = max(0.2, float(bad.weight) - 0.25)
                bad.updated_at = datetime.utcnow()

    # 7) K_guard reality anchor (office+chapter)
    guard = (
        db.query(GuardrailState)
        .filter(GuardrailState.office_id == office_id, GuardrailState.chapter == chapter)
        .first()
    )
    if not guard:
        guard = GuardrailState(
            office_id=office_id,
            chapter=chapter,
            expected_share=0.1,
            correction_count=0,
            mode_collapse_threshold=0.35,
        )
        db.add(guard)
        db.flush()
    if hs_changed:
        guard.correction_count = int(guard.correction_count or 0) + 1
        guard.mode_collapse_threshold = max(0.15, 0.35 - 0.02 * guard.correction_count)
        guard.updated_at = datetime.utcnow()

    learning_artifact = {
        "k_history_key": kh.key,
        "weight_updates": weight_updates[:20],
        "guard_chapter": chapter,
        "guard_corrections": guard.correction_count,
        "conditions": conditions,
    }
    fb.applied_to_learning = True
    fb.learning_artifact = learning_artifact

    db.commit()
    db.refresh(fb)

    # refresh in-memory office weights
    kg.refresh_office_weights(db, office_id)

    return {
        "feedback_id": fb.id,
        "system_hs": system_hs,
        "broker_hs": broker_hs,
        "hs_changed": hs_changed,
        "conditions": conditions,
        "applied_to_learning": True,
        "learning_artifact": learning_artifact,
    }
