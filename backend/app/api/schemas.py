from typing import Any, Optional

from pydantic import BaseModel, Field


class ClassifyRequest(BaseModel):
    description: str
    material: Optional[str] = None
    function: Optional[str] = None
    origin_country: Optional[str] = None
    external_id: Optional[str] = None
    ground_truth_hs: Optional[str] = None
    difficulty: str = "normal"
    closed_loop: bool = True
    force_routing: Optional[str] = None


class ClassifyResponse(BaseModel):
    session_id: str
    recommended_hs: str
    final_hs: str
    confidence: float
    review_tier: str
    status: str
    gir_applied: list[str]
    routing_mode: str
    metric_flags: list[str]
    opinion: dict[str, Any]
    delta: dict[str, Any]


class BatchClassifyRequest(BaseModel):
    closed_loop: bool = True
    limit: int = Field(default=100, ge=1, le=5000)


class ExperimentRequest(BaseModel):
    name: str = "exp1_main"
    experiment_type: str = "main_comparison"
    closed_loop: bool = True
    ablation: Optional[str] = None  # no_feedback | local_only | etc.


class WorkOrderCreate(BaseModel):
    agent_role: str
    title: str
    instructions: str
    acceptance_criteria: list[str] = []


class WorkOrderUpdate(BaseModel):
    status: str
    result: dict[str, Any] = {}
    verification_notes: Optional[str] = None
