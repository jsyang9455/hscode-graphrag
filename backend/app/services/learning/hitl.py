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
)
from backend.app.services.knowledge.graph import get_kg
from backend.app.services.learning.adaptive import (
    after_office_learning,
    apply_pattern_learning,
    extract_features,
)


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
    features = extract_features(
        description=desc,
        material=case.material if case else None,
        usage=case.function if case else None,
        opinion=detail_opinion,
        conditions=conditions,
        max_features=16,
    )
    tokens = features[:12] if features else _tokens(desc)[:12]

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

    # 6) Online adaptive pattern learning → GraphRAG office model
    weight_updates = apply_pattern_learning(
        db,
        office_id=office_id,
        features=features or tokens,
        target_hs=broker_hs,
        wrong_hs=system_hs if hs_changed else None,
        source="broker_hitl",
    )

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
        "features": features[:16],
    }
    fb.applied_to_learning = True
    fb.learning_artifact = learning_artifact

    db.commit()
    db.refresh(fb)

    # Immediate model rebuild + light probe so GraphRAG uses new patterns now
    model = after_office_learning(db, office_id=office_id, run_probe=True)
    learning_artifact["office_model"] = {
        "weight_rows": model.get("weight_rows"),
        "phrase_overlay": model.get("phrase_overlay"),
        "probe": model.get("probe"),
        "top_patterns": model.get("top_patterns", [])[:5],
    }
    fb.learning_artifact = learning_artifact
    db.commit()

    return {
        "feedback_id": fb.id,
        "system_hs": system_hs,
        "broker_hs": broker_hs,
        "hs_changed": hs_changed,
        "conditions": conditions,
        "applied_to_learning": True,
        "learning_artifact": learning_artifact,
        "office_model": learning_artifact["office_model"],
    }
