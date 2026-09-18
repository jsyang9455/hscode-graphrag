"""Adaptive learning + blind/eval/supervisor agent APIs."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.db.models import ExperimentRun, User, get_db
from backend.app.services.agents.loop import SupervisorAgent
from backend.app.services.auth.security import get_current_user
from backend.app.services.learning.adaptive import after_office_learning, rebuild_office_model

router = APIRouter(tags=["learning-agents"])


class BlindEvalRequest(BaseModel):
    limit: int = Field(10, ge=3, le=30)
    auto_remediate: bool = True


@router.post("/learning/retrain")
def retrain_office_model(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Rebuild office GraphRAG overlay from all HITL/workdoc learning and probe."""
    model = after_office_learning(db, office_id=user.office_id, run_probe=True)
    return {"ok": True, "office_model": model}


@router.get("/learning/model")
def get_office_model(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    return rebuild_office_model(db, user.office_id)


@router.post("/agents/blind-eval/run")
def run_blind_eval_cycle(
    req: BlindEvalRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Blind tester → evaluator → supervisor remediation cycle."""
    try:
        return SupervisorAgent().run_cycle(
            db,
            office_id=user.office_id,
            auto_remediate=req.auto_remediate,
            limit=req.limit,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"blind eval failed: {exc}") from exc


@router.get("/agents/blind-eval/latest")
def latest_blind_eval(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    limit: int = Query(5, ge=1, le=20),
) -> dict[str, Any]:
    rows = (
        db.query(ExperimentRun)
        .filter(
            ExperimentRun.office_id == user.office_id,
            ExperimentRun.experiment_type == "blind_supervisor_cycle",
        )
        .order_by(ExperimentRun.id.desc())
        .limit(limit)
        .all()
    )
    return {
        "runs": [
            {
                "id": r.id,
                "name": r.name,
                "status": r.status,
                "metrics": r.metrics,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
