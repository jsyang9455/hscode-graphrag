from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class SignupRequest(BaseModel):
    email: str
    password: str = Field(min_length=8)
    full_name: str
    office_code: str = Field(min_length=2, description="관세사 사무실 코드")
    office_name: str = Field(min_length=2, description="관세사 사무실명")


class LoginRequest(BaseModel):
    email: str
    password: str
    office_code: Optional[str] = None


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class ClassifyRequest(BaseModel):
    description: str
    material: Optional[str] = None
    function: Optional[str] = None  # usage
    origin_country: Optional[str] = None
    external_id: Optional[str] = None
    ground_truth_hs: Optional[str] = None
    difficulty: str = "normal"
    closed_loop: bool = True
    force_routing: Optional[str] = None


class ClassifyResponse(BaseModel):
    classification_id: int
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
    broker_brief: dict[str, Any] = {}
    candidates: list[dict[str, Any]] = []
    delta: dict[str, Any]
    fusion: dict[str, Any] = {}
    trajectory: list[dict[str, Any]] = []


class BrokerOpinionRequest(BaseModel):
    classification_id: int
    broker_hs: str
    conditions: list[str] = Field(
        default_factory=list,
        description="hs_accurate|tariff_benefit|gir_interpretation|practice|precedent|exclusion_note",
    )
    detail_opinion: str = Field(min_length=2)


class BatchClassifyRequest(BaseModel):
    closed_loop: bool = True
    limit: int = Field(default=100, ge=1, le=5000)


class ExperimentRequest(BaseModel):
    name: str = "exp1_main"
    experiment_type: str = "main_comparison"
    closed_loop: bool = True
    ablation: Optional[str] = None


class ChatSessionCreate(BaseModel):
    title: Optional[str] = None


class ChatMessageRequest(BaseModel):
    content: str = Field(min_length=1)
    material: Optional[str] = None
    function: Optional[str] = None
    closed_loop: bool = True


class WorkDocPasteRequest(BaseModel):
    title: str = "pasted-memo.txt"
    text: str = Field(min_length=5)
    doc_type: str = "opinion"


class WorkDocEditRequest(BaseModel):
    product_description: Optional[str] = None
    material: Optional[str] = None
    usage: Optional[str] = None
    suggested_hs: Optional[str] = None
    broker_opinion_excerpt: Optional[str] = None
    keywords: Optional[list[str]] = None


class WorkDocSaveRequest(BaseModel):
    run_classify: bool = True
    closed_loop: bool = True
    edited: Optional[WorkDocEditRequest] = None
