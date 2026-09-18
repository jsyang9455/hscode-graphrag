"""Chat classify + work-document upload/learn routes."""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.app.api.schemas import (
    ChatMessageRequest,
    ChatSessionCreate,
    WorkDocPasteRequest,
    WorkDocSaveRequest,
)
from backend.app.db.models import (
    ChatMessage,
    ChatSession,
    ProductCase,
    User,
    WorkDocument,
    get_db,
)
from backend.app.services.auth.security import get_current_user
from backend.app.services.classification.pipeline import ClassificationPipeline
from backend.app.services.documents.workdocs import (
    analyze_document_text,
    ensure_upload_dir,
    extract_text_from_bytes,
)
from backend.app.services.learning.workdoc_learn import save_work_document_learning

router = APIRouter()
pipeline = ClassificationPipeline()


def _session_or_404(db: Session, session_id: int, user: User) -> ChatSession:
    row = (
        db.query(ChatSession)
        .filter(
            ChatSession.id == session_id,
            ChatSession.office_id == user.office_id,
            ChatSession.user_id == user.id,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, "chat session not found")
    return row


def _doc_or_404(db: Session, doc_id: int, user: User) -> WorkDocument:
    row = (
        db.query(WorkDocument)
        .filter(WorkDocument.id == doc_id, WorkDocument.office_id == user.office_id)
        .first()
    )
    if not row:
        raise HTTPException(404, "document not found")
    return row


def _doc_payload(doc: WorkDocument) -> dict[str, Any]:
    preview = (doc.raw_text or "")[:500].replace("\r", " ").replace("\n", " ")
    return {
        "id": doc.id,
        "filename": doc.filename,
        "mime_type": doc.mime_type,
        "doc_type": doc.doc_type,
        "status": doc.status,
        "raw_text_preview": preview,
        "analysis": doc.analysis or {},
        "edited_fields": doc.edited_fields or {},
        "classification_id": doc.classification_id,
        "learning_artifact": doc.learning_artifact or {},
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.post("/chat/sessions")
def create_chat_session(
    req: ChatSessionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    title = (req.title or "새 HS 분류 대화").strip() or "새 HS 분류 대화"
    row = ChatSession(office_id=user.office_id, user_id=user.id, title=title)
    db.add(row)
    db.flush()
    welcome = ChatMessage(
        session_id=row.id,
        office_id=user.office_id,
        role="assistant",
        content=(
            "안녕하세요. HS 분류 상담 챗봇입니다.\n"
            "상품명·재질·용도를 말씀해 주시면 추천 코드와 선정 사유를 정리해 드립니다.\n"
            "예: 「히알루론산 수분 크림, 재질 cream, 용도 skin care」"
        ),
        payload={"kind": "welcome"},
    )
    db.add(welcome)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "title": row.title, "created_at": row.created_at.isoformat()}


@router.get("/chat/sessions")
def list_chat_sessions(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.office_id == user.office_id, ChatSession.user_id == user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(50)
        .all()
    )
    return [
        {
            "id": r.id,
            "title": r.title,
            "active": r.active,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/chat/sessions/{session_id}/messages")
def list_chat_messages(
    session_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    _session_or_404(db, session_id, user)
    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.id.asc())
        .all()
    )
    return [
        {
            "id": r.id,
            "role": r.role,
            "content": r.content,
            "classification_id": r.classification_id,
            "meta": r.payload or {},
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.post("/chat/sessions/{session_id}/messages")
def send_chat_message(
    session_id: int,
    req: ChatMessageRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = _session_or_404(db, session_id, user)
    content = req.content.strip()
    user_msg = ChatMessage(
        session_id=session.id,
        office_id=user.office_id,
        role="user",
        content=content,
        payload={"material": req.material, "function": req.function},
    )
    db.add(user_msg)
    db.flush()

    desc = content
    if req.material:
        desc = f"{desc} material:{req.material}"
    if req.function:
        desc = f"{desc} usage:{req.function}"

    case = ProductCase(
        office_id=user.office_id,
        external_id=f"chat-{session.id}-{uuid.uuid4().hex[:8]}",
        description=desc,
        material=req.material,
        function=req.function,
        difficulty="chat",
    )
    db.add(case)
    db.flush()
    out = pipeline.classify(db, case, office_id=user.office_id, closed_loop=req.closed_loop)
    brief = (out.opinion or {}).get("broker_brief") or {}
    narrative = brief.get("narrative_ko") or out.opinion.get("broker_opinion") or ""
    assistant_text = (
        f"추천 HS **{out.recommended_hs}** (신뢰도 {out.confidence:.1%})\n\n"
        f"{brief.get('headline') or ''}\n\n"
        f"{narrative}"
    ).strip()

    asst = ChatMessage(
        session_id=session.id,
        office_id=user.office_id,
        role="assistant",
        content=assistant_text,
        classification_id=out.classification_id,
        payload={
            "kind": "classify_result",
            "recommended_hs": out.recommended_hs,
            "confidence": out.confidence,
            "review_tier": out.review_tier,
            "status": out.status,
            "broker_brief": brief,
            "gir_applied": out.gir_applied,
        },
    )
    db.add(asst)
    session.title = content[:40] if session.title.startswith("새") else session.title
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(asst)
    db.refresh(user_msg)

    return {
        "user_message": {
            "id": user_msg.id,
            "role": "user",
            "content": user_msg.content,
            "meta": user_msg.payload,
        },
        "assistant_message": {
            "id": asst.id,
            "role": "assistant",
            "content": asst.content,
            "classification_id": asst.classification_id,
            "meta": asst.payload,
        },
        "classification": {
            "classification_id": out.classification_id,
            "recommended_hs": out.recommended_hs,
            "confidence": out.confidence,
            "status": out.status,
            "broker_brief": brief,
        },
    }


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form("opinion"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty file")
    if len(data) > 8_000_000:
        raise HTTPException(400, "file too large (max 8MB)")

    upload_dir = ensure_upload_dir() / str(user.office_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename or "upload.bin").name
    stored = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    stored.write_bytes(data)

    text = extract_text_from_bytes(safe_name, data, file.content_type or "")
    if not text.strip():
        text = f"(텍스트 추출 실패) 파일명: {safe_name}"

    doc = WorkDocument(
        office_id=user.office_id,
        user_id=user.id,
        filename=safe_name,
        mime_type=file.content_type or "application/octet-stream",
        doc_type=doc_type or "opinion",
        storage_path=str(stored),
        raw_text=text,
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _doc_payload(doc)


@router.post("/documents/paste")
def paste_document(
    req: WorkDocPasteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    upload_dir = ensure_upload_dir() / str(user.office_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(req.title or "pasted.txt").name
    stored = upload_dir / f"{uuid.uuid4().hex}_{safe_name}"
    stored.write_text(req.text, encoding="utf-8")
    doc = WorkDocument(
        office_id=user.office_id,
        user_id=user.id,
        filename=safe_name,
        mime_type="text/plain",
        doc_type=req.doc_type or "opinion",
        storage_path=str(stored),
        raw_text=req.text,
        status="uploaded",
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _doc_payload(doc)


@router.post("/documents/{doc_id}/analyze")
def analyze_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    doc = _doc_or_404(db, doc_id, user)
    analysis = analyze_document_text(doc.raw_text or "", doc.doc_type)
    doc.analysis = analysis
    doc.status = "analyzed"
    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    return _doc_payload(doc)


@router.post("/documents/{doc_id}/save")
def save_document(
    doc_id: int,
    req: WorkDocSaveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    doc = _doc_or_404(db, doc_id, user)
    if req.edited:
        edited = {k: v for k, v in req.edited.model_dump().items() if v is not None}
        doc.edited_fields = {**(doc.edited_fields or {}), **edited}
    if not doc.analysis:
        doc.analysis = analyze_document_text(doc.raw_text or "", doc.doc_type)
    doc.status = "saved"
    doc.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(doc)
    result = save_work_document_learning(
        db,
        doc=doc,
        office_id=user.office_id,
        run_classify=req.run_classify,
        closed_loop=req.closed_loop,
    )
    return {**_doc_payload(doc), **result}


@router.get("/documents")
def list_documents(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        db.query(WorkDocument)
        .filter(WorkDocument.office_id == user.office_id)
        .order_by(WorkDocument.id.desc())
        .limit(100)
        .all()
    )
    return [_doc_payload(r) for r in rows]


@router.get("/documents/{doc_id}")
def get_document(
    doc_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return _doc_payload(_doc_or_404(db, doc_id, user))
