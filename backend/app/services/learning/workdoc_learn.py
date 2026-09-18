"""Persist analyzed broker work documents into office GraphRAG learning stores."""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.app.db.models import (
    GuardrailState,
    KnowledgeHistory,
    ProductCase,
    TenantKeywordWeight,
    WorkDocument,
)
from backend.app.services.classification.pipeline import ClassificationPipeline
from backend.app.services.knowledge.graph import get_kg


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"[A-Za-z가-힣]{2,}", (text or "").lower())][:12]


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
    keywords = fields.get("keywords") or _tokens(description)

    digits = re.sub(r"\D", "", suggested_hs or "")
    chapter = int(digits[:2]) if len(digits) >= 2 else 0

    # 1) Knowledge history from broker materials
    hist = KnowledgeHistory(
        office_id=office_id,
        key=f"workdoc:{doc.id}:{suggested_hs or 'na'}",
        chapter=chapter,
        product_category=(keywords[0] if keywords else "general"),
        violation_type=None,
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
            "keywords": keywords,
            "source": "work_document",
        },
        source="work_document",
    )
    db.add(hist)
    db.flush()

    # 2) Keyword weights toward suggested HS (if present)
    weight_updates = []
    if suggested_hs:
        for kw in keywords[:8]:
            row = (
                db.query(TenantKeywordWeight)
                .filter(
                    TenantKeywordWeight.office_id == office_id,
                    TenantKeywordWeight.keyword == kw,
                    TenantKeywordWeight.hs_code == suggested_hs,
                )
                .first()
            )
            if row:
                row.weight = min(5.0, float(row.weight) + 0.35)
                row.evidence_count = int(row.evidence_count or 0) + 1
                row.updated_at = datetime.utcnow()
            else:
                row = TenantKeywordWeight(
                    office_id=office_id,
                    keyword=kw,
                    hs_code=suggested_hs,
                    weight=1.35,
                    evidence_count=1,
                )
                db.add(row)
            weight_updates.append({"keyword": kw, "hs_code": suggested_hs, "weight": row.weight})

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
        "classification": classify_out,
    }
    doc.learning_artifact = artifact
    doc.status = "learned"
    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)

    try:
        get_kg().refresh_office_weights(db, office_id)
    except Exception:  # noqa: BLE001
        pass

    return {
        "document_id": doc.id,
        "status": doc.status,
        "learning_artifact": artifact,
        "classification_id": classification_id,
    }
