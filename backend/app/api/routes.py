from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.api.schemas import (
    BatchClassifyRequest,
    ClassifyRequest,
    ClassifyResponse,
    ExperimentRequest,
    WorkOrderCreate,
    WorkOrderUpdate,
)
from backend.app.db.models import (
    ClassificationResult,
    EmpiricalReport,
    ExperimentRun,
    KnowledgeHistory,
    OpinionReport,
    PaperArtifact,
    ProductCase,
    WorkOrder,
    get_db,
    init_db,
)
from backend.app.services.classification.pipeline import ClassificationPipeline
from backend.app.services.metrics.eval import compute_metrics

router = APIRouter()
pipeline = ClassificationPipeline()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "hscode-graphrag"}


@router.post("/classify", response_model=ClassifyResponse)
def classify(req: ClassifyRequest, db: Session = Depends(get_db)) -> ClassifyResponse:
    ext = req.external_id or f"adhoc-{uuid.uuid4().hex[:8]}"
    case = db.query(ProductCase).filter(ProductCase.external_id == ext).first()
    if not case:
        case = ProductCase(
            external_id=ext,
            description=req.description,
            material=req.material,
            function=req.function,
            origin_country=req.origin_country,
            ground_truth_hs=req.ground_truth_hs,
            difficulty=req.difficulty,
        )
        db.add(case)
        db.commit()
        db.refresh(case)
    out = pipeline.classify(db, case, closed_loop=req.closed_loop, force_routing=req.force_routing)
    return ClassifyResponse(
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
        delta=out.delta,
    )


@router.post("/classify/batch")
def classify_batch(req: BatchClassifyRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    cases = db.query(ProductCase).limit(req.limit).all()
    if not cases:
        raise HTTPException(400, "No product cases seeded. Call /admin/seed first.")
    outputs = []
    for case in cases:
        out = pipeline.classify(db, case, closed_loop=req.closed_loop)
        outputs.append(
            {
                "external_id": case.external_id,
                "final_hs": out.final_hs,
                "status": out.status,
                "confidence": out.confidence,
            }
        )
    metrics = compute_metrics(db)
    return {"processed": len(outputs), "results": outputs, "metrics": metrics}


@router.post("/experiments/run")
def run_experiment(req: ExperimentRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    closed_loop = req.closed_loop and req.ablation != "no_feedback"
    force_routing = "local_only" if req.ablation == "local_only" else None
    cases = db.query(ProductCase).all()
    for case in cases:
        pipeline.classify(db, case, closed_loop=closed_loop, force_routing=force_routing)
    metrics = compute_metrics(db)
    run = ExperimentRun(
        name=req.name,
        experiment_type=req.experiment_type,
        config={"closed_loop": closed_loop, "ablation": req.ablation},
        metrics=metrics,
        status="completed",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"experiment_id": run.id, "metrics": metrics, "config": run.config}


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)) -> dict[str, Any]:
    return compute_metrics(db)


@router.get("/cases")
def list_cases(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    cases = db.query(ProductCase).order_by(ProductCase.id.desc()).limit(200).all()
    return [
        {
            "id": c.id,
            "external_id": c.external_id,
            "description": c.description,
            "ground_truth_hs": c.ground_truth_hs,
            "difficulty": c.difficulty,
        }
        for c in cases
    ]


@router.get("/classifications")
def list_classifications(limit: int = 50, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (
        db.query(ClassificationResult)
        .order_by(ClassificationResult.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "case_id": r.case_id,
            "recommended_hs": r.recommended_hs,
            "final_hs": r.final_hs,
            "confidence": r.confidence,
            "review_tier": r.review_tier,
            "status": r.status,
            "routing_mode": r.routing_mode,
            "metric_flags": r.metric_flags,
        }
        for r in rows
    ]


@router.get("/opinions/{classification_id}")
def get_opinion(classification_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    op = db.query(OpinionReport).filter(OpinionReport.classification_id == classification_id).first()
    if not op:
        raise HTTPException(404, "Opinion not found")
    return {
        "id": op.id,
        "classification_id": op.classification_id,
        "product_summary": op.product_summary,
        "candidate_codes": op.candidate_codes,
        "gir_rationale": op.gir_rationale,
        "exclusion_summary": op.exclusion_summary,
        "tariff_info": op.tariff_info,
        "broker_opinion": op.broker_opinion,
        "confidence_grade": op.confidence_grade,
        "auto_approved": op.auto_approved,
    }


@router.get("/knowledge/history")
def knowledge_history(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(KnowledgeHistory).order_by(KnowledgeHistory.id.desc()).limit(100).all()
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


@router.post("/admin/seed")
def seed(db: Session = Depends(get_db)) -> dict[str, Any]:
    from backend.app.services.knowledge.seed import seed_cases

    n = seed_cases(db)
    return {"seeded": n}


@router.post("/admin/init")
def admin_init() -> dict[str, str]:
    init_db()
    return {"status": "initialized"}


@router.post("/work-orders")
def create_work_order(req: WorkOrderCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    wo = WorkOrder(
        order_id=f"WO-{uuid.uuid4().hex[:8]}",
        agent_role=req.agent_role,
        title=req.title,
        instructions=req.instructions,
        acceptance_criteria=req.acceptance_criteria,
        status="pending",
    )
    db.add(wo)
    db.commit()
    db.refresh(wo)
    return {"order_id": wo.order_id, "id": wo.id, "status": wo.status}


@router.patch("/work-orders/{order_id}")
def update_work_order(order_id: str, req: WorkOrderUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    wo = db.query(WorkOrder).filter(WorkOrder.order_id == order_id).first()
    if not wo:
        raise HTTPException(404, "Work order not found")
    wo.status = req.status
    wo.result = req.result
    wo.verification_notes = req.verification_notes
    db.commit()
    return {"order_id": wo.order_id, "status": wo.status}


@router.get("/work-orders")
def list_work_orders(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(WorkOrder).order_by(WorkOrder.id.desc()).all()
    return [
        {
            "order_id": r.order_id,
            "agent_role": r.agent_role,
            "title": r.title,
            "status": r.status,
            "verification_notes": r.verification_notes,
            "result": r.result,
        }
        for r in rows
    ]


@router.get("/reports/empirical")
def list_empirical(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(EmpiricalReport).order_by(EmpiricalReport.id.desc()).all()
    return [
        {"id": r.id, "title": r.title, "summary": r.summary, "metrics": r.metrics, "findings": r.findings}
        for r in rows
    ]


@router.get("/papers")
def list_papers(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(PaperArtifact).order_by(PaperArtifact.id.asc()).all()
    return [
        {"id": r.id, "title": r.title, "section": r.section, "content": r.content, "sources": r.sources}
        for r in rows
    ]


@router.get("/experiments")
def list_experiments(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = db.query(ExperimentRun).order_by(ExperimentRun.id.desc()).all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "experiment_type": r.experiment_type,
            "config": r.config,
            "metrics": r.metrics,
            "status": r.status,
        }
        for r in rows
    ]
