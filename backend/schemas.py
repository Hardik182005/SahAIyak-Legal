from pydantic import BaseModel, Field
from typing import Optional


class CaseCreate(BaseModel):
    description: str = Field(..., min_length=20, max_length=3000)
    state: Optional[str] = None
    amount: Optional[str] = None
    date_started: Optional[str] = None
    evidence_text: Optional[str] = None
    language: str = "EN"
    session_id: Optional[str] = None


class SimilarCase(BaseModel):
    year: str
    court: str
    outcome: str
    amount: str
    key_fact: str


class EvidenceItem(BaseModel):
    title: str
    impact: str
    direction: str  # "positive" or "negative"
    sub: Optional[str] = None


class LawItem(BaseModel):
    act: str
    sections: list[str]
    plain_english: str


class AuthorityInfo(BaseModel):
    forum: str
    address: str
    filing_fee: str
    jurisdiction_notes: str
    avg_resolution: str


class AnalysisResponse(BaseModel):
    case_id: str
    win_probability: int
    similar_cases_count: int
    claim_amount: Optional[str]
    state: Optional[str]
    laws: list[LawItem]
    authority: AuthorityInfo
    evidence_strengths: list[EvidenceItem]
    evidence_gaps: list[EvidenceItem]
    similar_cases: list[SimilarCase]
    opponent_arguments: list[dict]
    summary: str


class NoticeResponse(BaseModel):
    case_id: str
    notice_text: str
    version: int


class ChatMessage(BaseModel):
    message: str
    case_id: str


class ChatResponse(BaseModel):
    reply: str
