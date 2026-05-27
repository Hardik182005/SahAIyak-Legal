"""SahAIyak FastAPI backend — Legal AI for India."""
import logging
import json
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import os
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from redis.asyncio import Redis as AIORedis
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from .config import get_settings
from .database import init_engine, create_tables, get_db
from .models import Case, AnalysisResult, LegalNotice
from .schemas import CaseCreate, AnalysisResponse, NoticeResponse, ChatMessage, ChatResponse
from .agents.analyzer import analyze_case
from .agents.notice_drafter import modify_notice
from .agents.sentry import sentry_chat, drafter_chat
from .agents.voice import speak
from .utils.cleanup import start_cleanup_scheduler, stop_cleanup_scheduler

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")
logger = logging.getLogger(__name__)

_redis: Optional[AIORedis] = None
_session_factory = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis, _session_factory
    settings = get_settings()
    init_engine(settings.database_url)
    from .database import _SessionLocal
    _session_factory = _SessionLocal
    await create_tables()
    try:
        _redis = AIORedis.from_url(settings.redis_url, decode_responses=True)
        await _redis.ping()
        logger.info("Redis connected: %s", settings.redis_url)
    except Exception as e:
        logger.warning("Redis unavailable (%s) — proceeding without cache", e)
        _redis = None
    start_cleanup_scheduler(_session_factory, settings.data_retention_days)
    yield
    stop_cleanup_scheduler()
    if _redis:
        await _redis.close()


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="SahAIyak API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve /static/ folder (JS, CSS, etc.)
_PROJECT_ROOT = Path(__file__).parent.parent  # project root
_SCREENS_DIR = _PROJECT_ROOT / "screens"   # HTML pages live here
_FRONTEND_DIR = _SCREENS_DIR if _SCREENS_DIR.exists() else _PROJECT_ROOT
_STATIC_DIR = _PROJECT_ROOT / "static"
if _STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


async def _cache_get(key: str) -> Optional[dict]:
    if not _redis:
        return None
    try:
        val = await _redis.get(key)
        return json.loads(val) if val else None
    except Exception:
        return None


async def _cache_set(key: str, data: dict, ttl: int = 3600):
    if not _redis:
        return
    try:
        await _redis.setex(key, ttl, json.dumps(data))
    except Exception:
        pass


@app.get("/health")
async def health():
    return {"status": "ok", "service": "SahAIyak API"}


@app.post("/api/v1/cases")
@limiter.limit("10/minute")
async def create_case(request: Request, payload: CaseCreate, db: AsyncSession = Depends(get_db)):
    session_id = payload.session_id or str(uuid.uuid4())

    case = Case(
        session_id=session_id,
        description=payload.description,
        state=payload.state or "Maharashtra",
        amount=payload.amount or "",
        date_started=payload.date_started or "",
        evidence_text=payload.evidence_text or "",
        language=payload.language,
    )
    db.add(case)
    await db.flush()

    cache_key = f"analysis:{case.id}"
    cached = await _cache_get(cache_key)

    if cached:
        result_data = cached
    else:
        result_data = await analyze_case(
            description=payload.description,
            state=payload.state or "Maharashtra",
            amount=payload.amount or "",
            evidence_text=payload.evidence_text or "",
            language=payload.language,
        )
        await _cache_set(cache_key, result_data, ttl=3600)

    analysis = AnalysisResult(
        case_id=case.id,
        win_probability=result_data["win_probability"],
        law_data={"laws": result_data["laws"], "summary": result_data.get("law_summary", "")},
        authority_data=result_data["authority"],
        evidence_data={
            "strengths": result_data["evidence_strengths"],
            "gaps": result_data["evidence_gaps"],
            "score": result_data.get("evidence_score", "5/10"),
            "tip": result_data.get("coaching_tip", ""),
        },
        similar_cases=result_data["similar_cases"],
    )
    db.add(analysis)

    notice = LegalNotice(
        case_id=case.id,
        notice_text=result_data["notice_text"],
        version=1,
    )
    db.add(notice)
    await db.commit()

    return {
        "case_id": case.id,
        "session_id": session_id,
        "win_probability": result_data["win_probability"],
        "message": "Case analysis complete",
    }


@app.get("/api/v1/cases/{case_id}")
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)):
    cache_key = f"case_full:{case_id}"
    cached = await _cache_get(cache_key)
    if cached:
        return cached

    result = await db.execute(
        select(Case, AnalysisResult).join(AnalysisResult, Case.id == AnalysisResult.case_id).where(Case.id == case_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    case, analysis = row
    response = {
        "case_id": case.id,
        "description": case.description[:200] + "..." if len(case.description) > 200 else case.description,
        "state": case.state,
        "amount": case.amount,
        "language": case.language,
        "created_at": case.created_at.isoformat(),
        "win_probability": analysis.win_probability,
        "similar_cases_count": len(analysis.similar_cases),
        "laws": analysis.law_data.get("laws", []),
        "law_summary": analysis.law_data.get("summary", ""),
        "authority": analysis.authority_data,
        "evidence_strengths": analysis.evidence_data.get("strengths", []),
        "evidence_gaps": analysis.evidence_data.get("gaps", []),
        "evidence_score": analysis.evidence_data.get("score", "5/10"),
        "coaching_tip": analysis.evidence_data.get("tip", ""),
        "similar_cases": analysis.similar_cases,
        "outcome_breakdown": {
            "won_pct": 58, "settled_pct": 28, "lost_pct": 14
        },
    }
    await _cache_set(cache_key, response, ttl=1800)
    return response


@app.get("/api/v1/cases/{case_id}/notice")
async def get_notice(case_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LegalNotice).where(LegalNotice.case_id == case_id).order_by(LegalNotice.version.desc())
    )
    notice = result.scalars().first()
    if not notice:
        raise HTTPException(status_code=404, detail="Notice not found")
    return {"case_id": case_id, "notice_text": notice.notice_text, "version": notice.version}


@app.post("/api/v1/cases/{case_id}/notice")
async def update_notice(case_id: str, payload: ChatMessage, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LegalNotice).where(LegalNotice.case_id == case_id).order_by(LegalNotice.version.desc())
    )
    existing = result.scalars().first()
    if not existing:
        raise HTTPException(status_code=404, detail="Notice not found")

    updated_text = await modify_notice(existing.notice_text, payload.message)
    new_notice = LegalNotice(
        case_id=case_id,
        notice_text=updated_text,
        version=existing.version + 1,
    )
    db.add(new_notice)
    await db.commit()
    return {"case_id": case_id, "notice_text": updated_text, "version": new_notice.version}


@app.post("/api/v1/cases/{case_id}/sentry")
async def sentry_endpoint(case_id: str, payload: ChatMessage, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalars().first()
    context = ""
    if case:
        result2 = await db.execute(select(AnalysisResult).where(AnalysisResult.case_id == case_id))
        analysis = result2.scalars().first()
        if analysis:
            context = f"Win probability: {analysis.win_probability}%. State: {case.state}. Amount: {case.amount}."

    reply = await sentry_chat(payload.message, context)
    return {"reply": reply}


@app.post("/api/v1/cases/{case_id}/drafter")
async def drafter_endpoint(case_id: str, payload: ChatMessage, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(LegalNotice).where(LegalNotice.case_id == case_id).order_by(LegalNotice.version.desc())
    )
    notice = result.scalars().first()
    notice_text = notice.notice_text if notice else ""

    reply = await drafter_chat(payload.message, notice_text)
    return {"reply": reply}


@app.post("/api/v1/voice/speak")
async def voice_speak(payload: dict):
    text = (payload.get("text") or "")[:500].strip()
    lang = payload.get("lang", "en")
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    audio = await speak(text, lang)
    if not audio:
        raise HTTPException(status_code=503, detail="Voice service unavailable")
    return Response(content=audio, media_type="audio/mpeg")


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error: %s", exc, exc_info=True)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ── FRONTEND CATCH-ALL (must be last) ────────────────────────────────
from fastapi.responses import FileResponse as _FileResponse

_HTML_MAP = {
    "index": "index.html", "intake": "intake.html",
    "dashboard": "dashboard.html", "document": "document.html",
    "manifesto": "manifesto.html", "settings": "settings.html",
}

@app.get("/{page_path:path}", include_in_schema=False)
async def serve_frontend(page_path: str, request: Request):
    slug = page_path.strip("/").replace(".html", "") or "index"
    html_file = _HTML_MAP.get(slug)
    if html_file:
        fp = _FRONTEND_DIR / html_file
        if fp.exists():
            return _FileResponse(str(fp))
    raise HTTPException(status_code=404, detail="Not found")
