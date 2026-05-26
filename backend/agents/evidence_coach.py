import json
from groq import AsyncGroq
from ..config import get_settings

_MODEL = "llama-3.3-70b-versatile"

_SYSTEM = """You are an Indian litigation evidence expert. Analyse the case description and identify:
1. Evidence the complainant LIKELY HAS (based on what they described) — positive impact
2. Evidence they are MISSING — negative impact if absent

Return ONLY valid JSON (no markdown):
{
  "strengths": [
    {"title": "Evidence name", "impact": "+X% WIN IMPACT", "direction": "positive"}
  ],
  "gaps": [
    {"title": "Missing evidence name", "sub": "How to obtain this", "impact": "-X% WITHOUT THIS", "direction": "negative"}
  ],
  "evidence_score": "X/10",
  "coaching_tip": "Most important single action to improve evidence score"
}
Be specific to Indian legal context. WhatsApp screenshots, NEFT receipts, signed agreements, witness statements are common."""


async def coach_evidence(description: str, evidence_text: str = "") -> dict:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key)
    prompt = f"Case: {description}\nEvidence user mentioned: {evidence_text or 'none specified'}\n\nAnalyse evidence strengths and gaps. Return JSON only."
    try:
        resp = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {
            "strengths": [{"title": "Case description provided", "impact": "+10% WIN IMPACT", "direction": "positive"}],
            "gaps": [{"title": "Written demand notice not yet sent", "sub": "Our legal notice cures this immediately", "impact": "-20% WITHOUT THIS", "direction": "negative"}],
            "evidence_score": "5/10",
            "coaching_tip": "Send the legal notice immediately via registered post.",
        }
