from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    JSON,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class ProductCase(Base):
    __tablename__ = "product_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    external_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    description: Mapped[str] = mapped_column(Text)
    material: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    function: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    origin_country: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    ground_truth_hs: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    difficulty: Mapped[str] = mapped_column(String(32), default="normal")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classifications: Mapped[list["ClassificationResult"]] = relationship(back_populates="case")


class ClassificationResult(Base):
    __tablename__ = "classification_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("product_cases.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    recommended_hs: Mapped[str] = mapped_column(String(16))
    final_hs: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    review_tier: Mapped[str] = mapped_column(String(32))  # lightweight | deep
    status: Mapped[str] = mapped_column(String(32))  # auto_approved | corrected | blocked
    gir_applied: Mapped[Any] = mapped_column(JSON, default=list)
    exclusion_checks: Mapped[Any] = mapped_column(JSON, default=list)
    local_hits: Mapped[Any] = mapped_column(JSON, default=list)
    global_hits: Mapped[Any] = mapped_column(JSON, default=list)
    routing_mode: Mapped[str] = mapped_column(String(32), default="dual")
    contention_score: Mapped[float] = mapped_column(Float, default=0.0)
    trajectory: Mapped[Any] = mapped_column(JSON, default=list)
    metric_flags: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    case: Mapped["ProductCase"] = relationship(back_populates="classifications")
    opinion: Mapped[Optional["OpinionReport"]] = relationship(back_populates="classification", uselist=False)
    feedback: Mapped[Optional["CorrectionDelta"]] = relationship(back_populates="classification", uselist=False)


class OpinionReport(Base):
    __tablename__ = "opinion_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classification_id: Mapped[int] = mapped_column(ForeignKey("classification_results.id"), unique=True)
    product_summary: Mapped[str] = mapped_column(Text)
    candidate_codes: Mapped[Any] = mapped_column(JSON, default=list)
    gir_rationale: Mapped[str] = mapped_column(Text)
    exclusion_summary: Mapped[str] = mapped_column(Text)
    tariff_info: Mapped[Any] = mapped_column(JSON, default=dict)
    similar_cases: Mapped[Any] = mapped_column(JSON, default=list)
    broker_opinion: Mapped[str] = mapped_column(Text)
    confidence_grade: Mapped[str] = mapped_column(String(16))
    auto_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classification: Mapped["ClassificationResult"] = relationship(back_populates="opinion")


class CorrectionDelta(Base):
    __tablename__ = "correction_deltas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classification_id: Mapped[int] = mapped_column(ForeignKey("classification_results.id"), unique=True)
    original_code: Mapped[str] = mapped_column(String(16))
    corrected_code: Mapped[str] = mapped_column(String(16))
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(128))
    tariff_impact: Mapped[Any] = mapped_column(JSON, default=dict)
    chapter: Mapped[int] = mapped_column(Integer)
    gir_applied: Mapped[Any] = mapped_column(JSON, default=list)
    similar_cases: Mapped[Any] = mapped_column(JSON, default=list)
    incorporated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classification: Mapped["ClassificationResult"] = relationship(back_populates="feedback")


class KnowledgeHistory(Base):
    """K_history — cross-query knowledge transfer store."""

    __tablename__ = "knowledge_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(256), index=True)
    chapter: Mapped[int] = mapped_column(Integer, index=True)
    product_category: Mapped[str] = mapped_column(String(128), index=True)
    violation_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payload: Mapped[Any] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(64), default="broker_correction")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GuardrailState(Base):
    """K_guard — dynamic expert reality anchor for metric guardrails."""

    __tablename__ = "guardrail_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chapter: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    expected_share: Mapped[float] = mapped_column(Float, default=0.0)
    mode_collapse_threshold: Mapped[float] = mapped_column(Float, default=0.35)
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128))
    experiment_type: Mapped[str] = mapped_column(String(64))
    config: Mapped[Any] = mapped_column(JSON, default=dict)
    metrics: Mapped[Any] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkOrder(Base):
    """Meta-agent work orders from supervisor."""

    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    agent_role: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(256))
    instructions: Mapped[str] = mapped_column(Text)
    acceptance_criteria: Mapped[Any] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    result: Mapped[Any] = mapped_column(JSON, default=dict)
    verification_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class PaperArtifact(Base):
    __tablename__ = "paper_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512))
    section: Mapped[str] = mapped_column(String(128), index=True)
    content: Mapped[str] = mapped_column(Text)
    sources: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class EmpiricalReport(Base):
    __tablename__ = "empirical_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(512))
    summary: Mapped[str] = mapped_column(Text)
    metrics: Mapped[Any] = mapped_column(JSON, default=dict)
    findings: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


_engine = None
_SessionLocal = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        settings = get_settings()
        url = settings.database_url
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        _engine = create_engine(url, connect_args=connect_args, future=True)
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)
    return _engine


def get_session_factory():
    get_engine()
    return _SessionLocal


def init_db():
    engine = get_engine()
    Base.metadata.create_all(bind=engine)


def get_db():
    Session = get_session_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()
