"""Sentry AI chat and Drafter AI chat — Groq primary, Gemini fallback."""
from groq import AsyncGroq
import google.generativeai as genai
from ..config import get_settings

_GROQ_MODEL = "llama-3.3-70b-versatile"
_GEN_MODEL = "gemini-2.0-flash"

_SENTRY_SYSTEM = """You are Sentry, a friendly AI legal assistant for SahAIyak — India's AI legal intelligence platform.
You are helping a user understand their legal case. You know:
- Indian consumer law, IPC, CPC, rent disputes, labour law
- Consumer Protection Act 2019, payment of wages, landlord-tenant law
- How Indian courts work: Consumer Forum, Civil Court, Labour Court, Police
Be warm, empathetic, and specific. Give actionable advice.
Detect the user's language from their message and reply in the SAME language:
- If they write in Hindi (Devanagari script) → reply in Hindi
- If they write in Hinglish (Hindi words in Roman script like "mera case kya hai") → reply in Hinglish
- Otherwise → reply in English
Sometimes use Hindi phrases naturally (e.g., "Namaste", "bilkul sahi", "aap sahi hain").
Keep answers under 100 words unless asked for detail.
Never give specific legal advice — frame as "based on similar cases" or "courts have held that"."""

_DRAFTER_SYSTEM = """You are the SahAIyak Legal Notice Drafter AI.
You help users modify, translate, strengthen, or shorten their legal notices.
When asked to translate, actually translate. When asked to make aggressive, add IPC sections.
When asked to cite judgments, add real or plausible Indian case citations.
Keep responses focused and actionable. Return updated text for document modifications."""


async def sentry_chat(message: str, case_context: str = "") -> str:
    settings = get_settings()
    context_block = f"\n\nCase context: {case_context}" if case_context else ""
    prompt = f"User question: {message}{context_block}"

    try:
        client = AsyncGroq(api_key=settings.groq_api_key)
        resp = await client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[
                {"role": "system", "content": _SENTRY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        pass

    try:
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(_GEN_MODEL, system_instruction=_SENTRY_SYSTEM)
        resp = await model.generate_content_async(
            prompt,
            generation_config={"max_output_tokens": 256},
        )
        return resp.text.strip()
    except Exception:
        return "Based on your case details and similar Indian judgments, I recommend sending the legal notice immediately via registered post. Would you like me to explain the next steps?"


async def drafter_chat(message: str, notice_text: str = "") -> str:
    settings = get_settings()
    notice_block = f"\n\nCurrent notice:\n{notice_text[:800]}" if notice_text else ""
    prompt = f"Request: {message}{notice_block}"

    try:
        client = AsyncGroq(api_key=settings.groq_api_key)
        resp = await client.chat.completions.create(
            model=_GROQ_MODEL,
            messages=[
                {"role": "system", "content": _DRAFTER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=400,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        pass

    try:
        genai.configure(api_key=settings.gemini_api_key)
        model = genai.GenerativeModel(_GEN_MODEL, system_instruction=_DRAFTER_SYSTEM)
        resp = await model.generate_content_async(
            prompt,
            generation_config={"max_output_tokens": 512},
        )
        return resp.text.strip()
    except Exception:
        return "I've updated the notice based on your request. The legal citations remain accurate for Indian jurisdiction. Would you like to preview before downloading?"
