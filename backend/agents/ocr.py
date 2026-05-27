"""OCR Document Analyzer — extracts key legal facts from uploaded photos/PDFs."""
import base64
import json
import logging
import httpx
from ..config import get_settings

logger = logging.getLogger(__name__)

_PROMPT = """You are a legal document analyzer for Indian law. Extract structured information from this document.

Identify and return a JSON object with these fields:
- document_type: (e.g., "Rental Agreement", "WhatsApp Screenshot", "Bank Statement", "Salary Slip", "Invoice")
- parties: list of names/entities mentioned
- amounts: list of monetary amounts (e.g., ["₹80,000 deposit", "₹15,000 monthly rent"])
- dates: list of dates mentioned
- key_clauses: list of important clauses or statements (max 5, focus on legally relevant ones)
- summary: one-sentence plain-English summary of what this document proves
- evidence_type: "STRONG" | "MODERATE" | "WEAK" — how useful is this as evidence

Return ONLY valid JSON. No markdown. No explanation outside the JSON."""


async def analyze_document(file_bytes: bytes, mime_type: str = "image/jpeg") -> dict:
    settings = get_settings()

    if not settings.gemini_api_key:
        return {
            "document_type": "Document",
            "parties": [],
            "amounts": [],
            "dates": [],
            "key_clauses": ["Unable to process — API key not configured."],
            "summary": "Document uploaded but could not be analyzed.",
            "evidence_type": "WEAK",
        }

    b64 = base64.b64encode(file_bytes).decode()

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": [{
                        "parts": [
                            {"text": _PROMPT},
                            {"inline_data": {"mime_type": mime_type, "data": b64}},
                        ]
                    }],
                    "generationConfig": {"temperature": 0.05, "maxOutputTokens": 600},
                },
            )
            resp.raise_for_status()
        raw = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.split("```")[0]
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        return {
            "document_type": "Document",
            "parties": [],
            "amounts": [],
            "dates": [],
            "key_clauses": [raw[:200] if raw else "Could not parse document."],
            "summary": "Document processed but structured extraction failed.",
            "evidence_type": "MODERATE",
        }
    except Exception as exc:
        logger.warning("OCR analysis failed: %s", exc)
        return {
            "document_type": "Document",
            "parties": [],
            "amounts": [],
            "dates": [],
            "key_clauses": [],
            "summary": "Document could not be analyzed at this time.",
            "evidence_type": "WEAK",
        }
