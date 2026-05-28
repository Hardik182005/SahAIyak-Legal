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
from .agents.negotiation import negotiate_turn
from .agents.ocr import analyze_document
from .agents.rti_generator import generate_rti
from .agents.whatsapp_bot import handle_whatsapp
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
            "total_analyzed": result_data.get("total_analyzed", 0),
            "outcome_breakdown": result_data.get("outcome_breakdown", {}),
            "avg_award": result_data.get("avg_award", "₹91,400"),
            "avg_resolution_months": result_data.get("avg_resolution_months", "4.2"),
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
    cases = analysis.similar_cases or []
    stored_ob = analysis.evidence_data.get("outcome_breakdown") or {}
    if stored_ob:
        ob = stored_ob
    else:
        won = sum(1 for c in cases if c.get("outcome") == "WON")
        settled = sum(1 for c in cases if c.get("outcome") == "SETTLED")
        lost = len(cases) - won - settled
        ob = {
            "won_pct": round(won / len(cases) * 100) if cases else 58,
            "settled_pct": round(settled / len(cases) * 100) if cases else 28,
            "lost_pct": round(lost / len(cases) * 100) if cases else 14,
        }
    stored_total = analysis.evidence_data.get("total_analyzed", 0)
    total_analyzed = stored_total if stored_total > 0 else len(cases)

    from datetime import datetime, timezone as _tz
    ca = case.created_at
    if ca and ca.tzinfo is None:
        ca = ca.replace(tzinfo=_tz.utc)
    days_active = (datetime.now(_tz.utc) - ca).days if ca else 0

    response = {
        "case_id": case.id,
        "description": case.description[:200] + "..." if len(case.description) > 200 else case.description,
        "state": case.state,
        "amount": case.amount,
        "language": case.language,
        "created_at": case.created_at.isoformat(),
        "days_active": days_active,
        "win_probability": analysis.win_probability,
        "similar_cases_count": len(cases),
        "total_analyzed": total_analyzed,
        "laws": analysis.law_data.get("laws", []),
        "law_summary": analysis.law_data.get("summary", ""),
        "authority": analysis.authority_data,
        "evidence_strengths": analysis.evidence_data.get("strengths", []),
        "evidence_gaps": analysis.evidence_data.get("gaps", []),
        "evidence_score": analysis.evidence_data.get("score", "5/10"),
        "coaching_tip": analysis.evidence_data.get("tip", ""),
        "similar_cases": cases,
        "outcome_breakdown": ob,
        "avg_award": analysis.evidence_data.get("avg_award", "₹91,400"),
        "avg_resolution_months": analysis.evidence_data.get("avg_resolution_months", "4.2"),
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
            ev = analysis.evidence_data or {}
            auth = analysis.authority_data or {}
            law_data = analysis.law_data or {}
            strengths_txt = ', '.join(s.get('title', '') for s in ev.get('strengths', [])[:3])
            gaps_txt = ', '.join(g.get('title', '') for g in ev.get('gaps', [])[:3])
            laws_txt = ', '.join(
                f"{l.get('act','')} s.{','.join(l.get('sections',[]))}"
                for l in law_data.get('laws', [])[:3]
            )
            similar = analysis.evidence_data.get('similar_cases', []) if analysis.evidence_data else []
            context = (
                f"Case: {case.description[:600]}. "
                f"Win probability: {analysis.win_probability}%. "
                f"State: {case.state}. Amount: ₹{case.amount}. "
                f"Forum: {auth.get('forum','')}. "
                f"Filing fee: {auth.get('filing_fee','')}. "
                f"Avg resolution: {auth.get('avg_resolution','')}. "
                f"Evidence score: {ev.get('score','')}. "
                f"Coaching tip: {ev.get('tip','')}. "
                f"Evidence strengths: {strengths_txt}. "
                f"Evidence gaps: {gaps_txt}. "
                f"Applicable laws: {laws_txt}. "
                f"Law summary: {law_data.get('summary','')[:300]}."
            )

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


@app.post("/api/v1/cases/{case_id}/negotiate")
async def negotiate_endpoint(case_id: str, payload: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Case).where(Case.id == case_id))
    case = result.scalars().first()
    description = case.description if case else payload.get("description", "")
    user_msg = (payload.get("message") or "").strip()
    history  = payload.get("history", [])
    lang     = payload.get("lang", "en")
    if not user_msg:
        raise HTTPException(status_code=400, detail="message is required")
    reply = await negotiate_turn(description, user_msg, history, lang=lang)
    return reply


@app.post("/api/v1/rti")
async def rti_endpoint(payload: dict):
    dept = (payload.get("department") or "").strip()
    state = (payload.get("state") or "Central Government").strip()
    info = (payload.get("information_needed") or "").strip()
    name = (payload.get("applicant_name") or "The Applicant").strip()
    lang = payload.get("language", "en")
    if not dept or not info:
        raise HTTPException(status_code=400, detail="department and information_needed are required")
    result = await generate_rti(dept, state, info, name, lang)
    return result


@app.post("/api/v1/whatsapp")
async def whatsapp_webhook(request: Request):
    """Twilio WhatsApp webhook — receives incoming messages."""
    form = await request.form()
    from_number = str(form.get("From", "")).replace("whatsapp:", "")
    body = str(form.get("Body", "")).strip()
    if not from_number or not body:
        return Response(content="", media_type="text/plain")
    reply = await handle_whatsapp(from_number, body, _redis)
    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response><Message>{reply}</Message></Response>"""
    return Response(content=twiml, media_type="application/xml")


@app.post("/api/v1/ocr")
async def ocr_endpoint(request: Request):
    import io
    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="file is required")
    data = await file.read()
    mime = file.content_type or "image/jpeg"
    result = await analyze_document(data, mime)
    return result


@app.get("/api/v1/cases/{case_id}/filing-packet")
async def filing_packet(case_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Case, AnalysisResult).join(AnalysisResult, Case.id == AnalysisResult.case_id).where(Case.id == case_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")
    case, analysis = row
    notice_r = await db.execute(
        select(LegalNotice).where(LegalNotice.case_id == case_id).order_by(LegalNotice.version.desc())
    )
    notice = notice_r.scalars().first()
    return {
        "case_id": case_id,
        "description": case.description,
        "state": case.state,
        "amount": case.amount,
        "date_started": case.date_started,
        "authority": analysis.authority_data,
        "laws": analysis.law_data.get("laws", []),
        "notice_text": notice.notice_text if notice else "",
        "evidence_strengths": analysis.evidence_data.get("strengths", []),
        "evidence_gaps": analysis.evidence_data.get("gaps", []),
        "filing_fee": (analysis.authority_data or {}).get("filing_fee", "₹200"),
        "forum": (analysis.authority_data or {}).get("forum", "District Consumer Forum"),
    }


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
    "negotiation": "negotiation.html", "edaakhil": "edaakhil.html",
    "rti": "rti.html",
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
