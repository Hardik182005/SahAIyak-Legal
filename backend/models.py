import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Integer, DateTime, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .database import Base


def _now():
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    session_id: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(String(64))
    amount: Mapped[str | None] = mapped_column(String(64))
    date_started: Mapped[str | None] = mapped_column(String(32))
    evidence_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(8), default="EN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    analysis: Mapped["AnalysisResult | None"] = relationship("AnalysisResult", back_populates="case", uselist=False)
    notices: Mapped[list["LegalNotice"]] = relationship("LegalNotice", back_populates="case")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("cases.id", ondelete="CASCADE"), unique=True)
    win_probability: Mapped[int] = mapped_column(Integer, default=0)
    law_data: Mapped[dict] = mapped_column(JSON, default=dict)
    authority_data: Mapped[dict] = mapped_column(JSON, default=dict)
    evidence_data: Mapped[dict] = mapped_column(JSON, default=dict)
    similar_cases: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped["Case"] = relationship("Case", back_populates="analysis")


class LegalNotice(Base):
    __tablename__ = "legal_notices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String(36), ForeignKey("cases.id", ondelete="CASCADE"))
    notice_text: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    case: Mapped["Case"] = relationship("Case", back_populates="notices")
