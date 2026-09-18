"""Persist analyzed broker work documents into office GraphRAG learning stores."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.db.models import GuardrailState, ProductCase, WorkDocument
from backend.app.services.classification.pipeline import ClassificationPipeline
from backend.app.services.learning.adaptive import (
    after_office_learning,
    apply_pattern_learning,
    extract_features,
    upsert_knowledge_history,
)


def save_work_document_learning(
    db: Session,
    *,
    doc: WorkDocument,
    office_id: int,
    run_classify: bool = True,
    closed_loop: bool = True,
) -> dict[str, Any]:
    fields = {**(doc.analysis or {}), **(doc.edited_fields or {})}
    description = (fields.get("product_description") or doc.raw_text[:400] or doc.filename).strip()
    material = fields.get("material")
    usage = fields.get("usage")
    suggested_hs = (fields.get("suggested_hs") or "").strip() or None
    opinion = fields.get("broker_opinion_excerpt") or ""
    keywords = fields.get("keywords") or []
    features = extract_features(
        description=description,
        material=material,
        usage=usage,
        opinion=opinion,
        max_features=16,
    )
    if keywords:
        features = list(dict.fromkeys([*(str(k).lower() for k in keywords[:8]), *features]))[:16]

    digits = re.sub(r"\D", "", suggested_hs or "")
    chapter = int(digits[:2]) if len(digits) >= 2 else 0

    # 1) Idempotent knowledge history (re-save updates same workdoc key)
    hist = upsert_knowledge_history(
        db,
        office_id=office_id,
        key=f"workdoc:{doc.id}:{suggested_hs or 'na'}",
        chapter=chapter,
        product_category=(features[0] if features else "general"),
        payload={
            "id": f"wd-{doc.id}",
            "document_id": doc.id,
            "filename": doc.filename,
            "doc_type": doc.doc_type,
            "description": description,
            "material": material,
            "usage": usage,
            "corrected_code": suggested_hs,
            "broker_opinion": opinion,
            "keywords": features,
            "source": "work_document",
        },
        source="work_document",
    )
    db.flush()

    # 2) Online adaptive pattern learning toward suggested HS
    weight_updates: list[dict[str, Any]] = []
    if suggested_hs:
        weight_updates = apply_pattern_learning(
            db,
            office_id=office_id,
            features=features,
            target_hs=suggested_hs,
            wrong_hs=None,
            source="work_document",
        )
        guard = (
            db.query(GuardrailState)
            .filter(GuardrailState.office_id == office_id, GuardrailState.chapter == chapter)
            .first()
        )
        if guard:
            guard.correction_count = int(guard.correction_count or 0) + 1
            guard.updated_at = datetime.utcnow()
        elif chapter:
            db.add(
                GuardrailState(
                    office_id=office_id,
                    chapter=chapter,
                    correction_count=1,
                )
            )

    classification_id: Optional[int] = None
    classify_out: Optional[dict[str, Any]] = None
    if run_classify:
        case = ProductCase(
            office_id=office_id,
            external_id=f"workdoc-{doc.id}-{uuid.uuid4().hex[:6]}",
            description=description,
            material=material,
            function=usage,
            ground_truth_hs=suggested_hs,
            difficulty="workdoc",
        )
        db.add(case)
        db.flush()
        pipe = ClassificationPipeline()
        out = pipe.classify(db, case, office_id=office_id, closed_loop=closed_loop)
        classification_id = out.classification_id
        doc.classification_id = classification_id
        classify_out = {
            "classification_id": out.classification_id,
            "recommended_hs": out.recommended_hs,
            "confidence": out.confidence,
            "broker_brief": (out.opinion or {}).get("broker_brief"),
        }

    artifact = {
        "knowledge_history_id": hist.id,
        "weight_updates": weight_updates,
        "suggested_hs": suggested_hs,
        "features": features[:16],
        "classification": classify_out,
    }
    doc.learning_artifact = artifact
    doc.status = "learned"
    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)

    # 3) Immediate office GraphRAG rebuild
    model = after_office_learning(db, office_id=office_id, run_probe=True)
    artifact["office_model"] = {
        "weight_rows": model.get("weight_rows"),
        "phrase_overlay": model.get("phrase_overlay"),
        "probe": model.get("probe"),
        "top_patterns": model.get("top_patterns", [])[:5],
    }
    doc.learning_artifact = artifact
    db.commit()

    return {
        "document_id": doc.id,
        "status": doc.status,
        "learning_artifact": artifact,
        "classification_id": classification_id,
        "office_model": artifact["office_model"],
    }
