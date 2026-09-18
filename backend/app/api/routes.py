from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.schemas import (
    AuthResponse,
    BatchClassifyRequest,
    BrokerOpinionRequest,
    ClassifyRequest,
    ClassifyResponse,
    ExperimentRequest,
    LoginRequest,
    SignupRequest,
)
from backend.app.db.models import (
    BrokerOpinionFeedback,
    ClassificationResult,
    EmpiricalReport,
    ExperimentRun,
    HsCodeRecord,
    KnowledgeHistory,
    Office,
    OpinionReport,
    PaperArtifact,
    ProductCase,
    TenantKeywordWeight,
    User,
    WorkOrder,
    get_db,
    init_db,
)
from backend.app.services.auth.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from backend.app.services.classification.pipeline import ClassificationPipeline
from backend.app.services.knowledge.graph import get_kg
from backend.app.services.knowledge.loader import ensure_hs_master
from backend.app.services.learning.hitl import CONDITION_LABELS, apply_broker_feedback
from backend.app.services.metrics.eval import compute_metrics

router = APIRouter()
pipeline = ClassificationPipeline()


def _user_payload(user: User, office: Office) -> dict[str, Any]:
    return {
        "id": user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role,
        "office_id": office.id,
        "office_code": office.code,
        "office_name": office.name,
    }


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "hscode-graphrag",
        "hs_records": db.query(HsCodeRecord).count(),
        "data_mode": "kcs_hsk_legacy" if db.query(HsCodeRecord).count() > 1000 else "limited",
    }


@router.post("/auth/signup", response_model=AuthResponse)
def signup(req: SignupRequest, db: Session = Depends(get_db)) -> AuthResponse:
    office = db.query(Office).filter(Office.code == req.office_code.strip()).first()
    if not office:
        office = Office(code=req.office_code.strip(), name=req.office_name.strip())
        db.add(office)
        db.flush()
    exists = (
        db.query(User)
        .filter(User.office_id == office.id, User.email == req.email.strip().lower())
        .first()
    )
    if exists:
        raise HTTPException(400, "해당 사무실에 이미 등록된 이메일입니다")
    user = User(
        office_id=office.id,
        email=req.email.strip().lower(),
        password_hash=hash_password(req.password),
        full_name=req.full_name.strip(),
        role="broker",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    token = create_access_token({"sub": str(user.id), "office_id": office.id})
    return AuthResponse(access_token=token, user=_user_payload(user, office))


@router.post("/auth/login", response_model=AuthResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)) -> AuthResponse:
    q = db.query(User).filter(User.email == req.email.strip().lower())
    if req.office_code:
        office = db.query(Office).filter(Office.code == req.office_code.strip()).first()
        if not office:
            raise HTTPException(401, "사무실 코드를 확인하세요")
        q = q.filter(User.office_id == office.id)
    user = q.first()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "이메일 또는 비밀번호가 올바르지 않습니다")
    office = db.query(Office).filter(Office.id == user.office_id).first()
    token = create_access_token({"sub": str(user.id), "office_id": user.office_id})
    return AuthResponse(access_token=token, user=_user_payload(user, office))


@router.get("/auth/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    office = db.query(Office).filter(Office.id == user.office_id).first()
    return _user_payload(user, office)


@router.post("/classify", response_model=ClassifyResponse)
def classify(
    req: ClassifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClassifyResponse:
    desc = req.description
    if req.material:
        desc = f"{desc} material:{req.material}"
    if req.function:
        desc = f"{desc} usage:{req.function}"
    ext = req.external_id or f"adhoc-{uuid.uuid4().hex[:8]}"
    case = (
        db.query(ProductCase)
        .filter(ProductCase.office_id == user.office_id, ProductCase.external_id == ext)
        .first()
    )
    if not case:
        case = ProductCase(
            office_id=user.office_id,
            external_id=ext,
            description=desc,
            material=req.material,
            function=req.function,
            origin_country=req.origin_country,
            ground_truth_hs=req.ground_truth_hs,
            difficulty=req.difficulty,
        )
        db.add(case)
        db.commit()
        db.refresh(case)
    out = pipeline.classify(db, case, office_id=user.office_id, closed_loop=req.closed_loop, force_routing=req.force_routing)
    return ClassifyResponse(
        classification_id=out.classification_id,
        session_id=out.session_id,
        recommended_hs=out.recommended_hs,
        final_hs=out.final_hs,
        confidence=out.confidence,
        review_tier=out.review_tier,
        status=out.status,
        gir_applied=out.gir_applied,
        routing_mode=out.routing_mode,
        metric_flags=out.metric_flags,
        opinion=out.opinion,
        broker_brief=(out.opinion or {}).get("broker_brief") or {},
        candidates=out.local_hits,
        delta=out.delta,
    )


@router.get("/opinions/pending")
def pending_opinions(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(OpinionReport, ClassificationResult, ProductCase)
        .join(ClassificationResult, OpinionReport.classification_id == ClassificationResult.id)
        .join(ProductCase, ClassificationResult.case_id == ProductCase.id)
        .filter(OpinionReport.office_id == user.office_id, OpinionReport.review_status == "pending_broker")
        .order_by(OpinionReport.id.desc())
        .limit(100)
        .all()
    )
    out = []
    for op, clf, case in rows:
        out.append(
            {
                "opinion_id": op.id,
                "classification_id": clf.id,
                "description": case.description,
                "recommended_hs": clf.recommended_hs,
                "confidence": clf.confidence,
                "confidence_grade": op.confidence_grade,
                "gir_rationale": op.gir_rationale,
                "exclusion_summary": op.exclusion_summary,
                "tariff_info": op.tariff_info,
                "candidate_codes": op.candidate_codes,
                "system_opinion": op.broker_opinion,
            }
        )
    return out


@router.get("/opinions/conditions")
def opinion_conditions() -> dict[str, Any]:
    return {"conditions": CONDITION_LABELS}


@router.post("/opinions/broker-review")
def broker_review(
    req: BrokerOpinionRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    try:
        return apply_broker_feedback(
            db,
            office_id=user.office_id,
            user_id=user.id,
            classification_id=req.classification_id,
            broker_hs=req.broker_hs,
            conditions=req.conditions or ["hs_accurate"],
            detail_opinion=req.detail_opinion,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/learning/weights")
def learning_weights(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(TenantKeywordWeight)
        .filter(TenantKeywordWeight.office_id == user.office_id)
        .order_by(TenantKeywordWeight.weight.desc())
        .limit(100)
        .all()
    )
    return [
        {"keyword": r.keyword, "hs_code": r.hs_code, "weight": r.weight, "evidence_count": r.evidence_count}
        for r in rows
    ]


@router.get("/metrics")
def metrics(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict[str, Any]:
    return compute_metrics(db, office_id=user.office_id)


@router.get("/classifications")
def list_classifications(
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = (
        db.query(ClassificationResult)
        .filter(ClassificationResult.office_id == user.office_id)
        .order_by(ClassificationResult.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "recommended_hs": r.recommended_hs,
            "final_hs": r.final_hs,
            "confidence": r.confidence,
            "review_tier": r.review_tier,
            "status": r.status,
            "routing_mode": r.routing_mode,
        }
        for r in rows
    ]


@router.get("/knowledge/history")
def knowledge_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(KnowledgeHistory)
        .filter(KnowledgeHistory.office_id == user.office_id)
        .order_by(KnowledgeHistory.id.desc())
        .limit(100)
        .all()
    )
    return [
        {
            "id": r.id,
            "key": r.key,
            "chapter": r.chapter,
            "product_category": r.product_category,
            "violation_type": r.violation_type,
            "payload": r.payload,
            "source": r.source,
        }
        for r in rows
    ]


@router.get("/data/status")
def data_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    n = db.query(HsCodeRecord).count()
    sample = db.query(HsCodeRecord).filter(HsCodeRecord.source == "kcs_hsk_hscode_prj").limit(3).all()
    return {
        "hs_records": n,
        "using_legacy_kcs": n > 1000,
        "source_project": "jsyang9455/hscode_prj" if n > 1000 else None,
        "samples": [
            {"hs_code": s.hs_code, "title_ko": s.title_ko, "title_en": s.title_en, "source": s.source}
            for s in sample
        ],
    }


@router.post("/admin/ingest-hs")
def ingest_hs(db: Session = Depends(get_db)) -> dict[str, Any]:
    meta = ensure_hs_master(db)
    kg = get_kg()
    loaded = kg.load_from_db(db)
    meta["kg_nodes"] = loaded
    return meta


@router.post("/admin/init")
def admin_init(db: Session = Depends(get_db)) -> dict[str, Any]:
    init_db(drop_all=True)
    meta = ensure_hs_master(db)
    get_kg().load_from_db(db)
    return {"status": "initialized", **meta}


@router.post("/classify/batch")
def classify_batch(
    req: BatchClassifyRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    cases = db.query(ProductCase).filter(ProductCase.office_id == user.office_id).limit(req.limit).all()
    if not cases:
        # seed minimal cases for office from descriptions
        from backend.app.services.knowledge.seed import seed_cases_for_office

        seed_cases_for_office(db, user.office_id)
        cases = db.query(ProductCase).filter(ProductCase.office_id == user.office_id).limit(req.limit).all()
    outputs = []
    for case in cases:
        out = pipeline.classify(db, case, office_id=user.office_id, closed_loop=req.closed_loop)
        outputs.append({"external_id": case.external_id, "final_hs": out.final_hs, "status": out.status})
    return {"processed": len(outputs), "results": outputs, "metrics": compute_metrics(db, office_id=user.office_id)}


@router.get("/papers")
def list_papers(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(PaperArtifact).order_by(PaperArtifact.id.asc()).all()
    return [{"id": r.id, "title": r.title, "section": r.section, "content": r.content} for r in rows]


@router.get("/reports/empirical")
def list_empirical(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(EmpiricalReport).order_by(EmpiricalReport.id.desc()).all()
    return [{"id": r.id, "title": r.title, "summary": r.summary, "metrics": r.metrics, "findings": r.findings} for r in rows]
