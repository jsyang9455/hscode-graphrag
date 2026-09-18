from __future__ import annotations

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
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from backend.app.core.config import get_settings


class Base(DeclarativeBase):
    pass


class Office(Base):
    """관세사 사무실(테넌트). 사무실별로 GraphRAG/학습모델이 분리된다."""

    __tablename__ = "offices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    users: Mapped[list["User"]] = relationship(back_populates="office")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("office_id", "email", name="uq_office_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    email: Mapped[str] = mapped_column(String(256), index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    full_name: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), default="broker")  # broker | admin
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    office: Mapped["Office"] = relationship(back_populates="users")


class ProductCase(Base):
    __tablename__ = "product_cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True, default=1)
    external_id: Mapped[str] = mapped_column(String(64), index=True)
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
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True, default=1)
    case_id: Mapped[int] = mapped_column(ForeignKey("product_cases.id"), index=True)
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    recommended_hs: Mapped[str] = mapped_column(String(16))
    final_hs: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    review_tier: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32))  # pending_broker | auto_approved | corrected | blocked
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
    broker_feedback: Mapped[Optional["BrokerOpinionFeedback"]] = relationship(
        back_populates="classification", uselist=False
    )


class OpinionReport(Base):
    """시스템 추천 의견서(초안). 관세사 HITL 검토 대기."""

    __tablename__ = "opinion_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True, default=1)
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
    review_status: Mapped[str] = mapped_column(String(32), default="pending_broker")  # pending_broker|broker_reviewed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classification: Mapped["ClassificationResult"] = relationship(back_populates="opinion")


class BrokerOpinionFeedback(Base):
    """관세사 HITL 의견: HS 확인/수정 + 조건 선택 + 상세 의견 → GraphRAG 학습 반영."""

    __tablename__ = "broker_opinion_feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    classification_id: Mapped[int] = mapped_column(ForeignKey("classification_results.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    system_hs: Mapped[str] = mapped_column(String(16))
    broker_hs: Mapped[str] = mapped_column(String(16))
    hs_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    conditions: Mapped[Any] = mapped_column(JSON, default=list)
    # conditions examples: hs_accurate, tariff_benefit, gir_interpretation, practice, precedent, exclusion_note
    detail_opinion: Mapped[str] = mapped_column(Text)
    applied_to_learning: Mapped[bool] = mapped_column(Boolean, default=False)
    learning_artifact: Mapped[Any] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    classification: Mapped["ClassificationResult"] = relationship(back_populates="broker_feedback")


class CorrectionDelta(Base):
    __tablename__ = "correction_deltas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True, default=1)
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
    __tablename__ = "knowledge_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True, default=1)
    key: Mapped[str] = mapped_column(String(256), index=True)
    chapter: Mapped[int] = mapped_column(Integer, index=True)
    product_category: Mapped[str] = mapped_column(String(128), index=True)
    violation_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    payload: Mapped[Any] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(64), default="broker_correction")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GuardrailState(Base):
    __tablename__ = "guardrail_state"
    __table_args__ = (UniqueConstraint("office_id", "chapter", name="uq_office_chapter_guard"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True, default=1)
    chapter: Mapped[int] = mapped_column(Integer, index=True)
    expected_share: Mapped[float] = mapped_column(Float, default=0.0)
    mode_collapse_threshold: Mapped[float] = mapped_column(Float, default=0.35)
    correction_count: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TenantKeywordWeight(Base):
    """사무실별 GraphRAG 키워드→HS 가중치 (HITL 학습으로 갱신)."""

    __tablename__ = "tenant_keyword_weights"
    __table_args__ = (UniqueConstraint("office_id", "keyword", "hs_code", name="uq_office_kw_hs"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    keyword: Mapped[str] = mapped_column(String(128), index=True)
    hs_code: Mapped[str] = mapped_column(String(16), index=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class HsCodeRecord(Base):
    """수집된 HS/HSK 마스터 (공유 규제 지식 — 전 사무실 공통 기반)."""

    __tablename__ = "hs_code_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hs_code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    level: Mapped[int] = mapped_column(Integer, default=6)
    title_en: Mapped[str] = mapped_column(Text, default="")
    title_ko: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    parent_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    chapter: Mapped[int] = mapped_column(Integer, index=True)
    source: Mapped[str] = mapped_column(String(64), default="wco_hs")
    raw: Mapped[Any] = mapped_column(JSON, default=dict)


class ExperimentRun(Base):
    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    experiment_type: Mapped[str] = mapped_column(String(64))
    config: Mapped[Any] = mapped_column(JSON, default=dict)
    metrics: Mapped[Any] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="completed")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WorkOrder(Base):
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


class ChatSession(Base):
    """HS 분류 챗봇 세션 (사무실·사용자 스코프)."""

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(256), default="새 분류 대화")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    messages: Mapped[list["ChatMessage"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    classification_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("classification_results.id"), nullable=True
    )
    payload: Mapped[Any] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["ChatSession"] = relationship(back_populates="messages")


class WorkDocument(Base):
    """관세사 기존 업무자료 업로드·분석·학습 반영."""

    __tablename__ = "work_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    office_id: Mapped[int] = mapped_column(ForeignKey("offices.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(128), default="text/plain")
    doc_type: Mapped[str] = mapped_column(String(64), default="opinion")  # opinion|invoice|pl|bl|memo|other
    storage_path: Mapped[str] = mapped_column(String(1024))
    raw_text: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(32), default="uploaded"
    )  # uploaded|analyzed|saved|learned
    analysis: Mapped[Any] = mapped_column(JSON, default=dict)
    edited_fields: Mapped[Any] = mapped_column(JSON, default=dict)
    classification_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("classification_results.id"), nullable=True
    )
    learning_artifact: Mapped[Any] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


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


def init_db(drop_all: bool = False):
    engine = get_engine()
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def get_db():
    Session = get_session_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()


def reset_engine_cache():
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
