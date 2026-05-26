import json
from groq import AsyncGroq
from ..config import get_settings

_MODEL = "llama-3.3-70b-versatile"

_SYSTEM = """You are an Indian court jurisdiction expert. Given a case description and state, determine the correct forum.
Return ONLY valid JSON (no markdown):
{
  "forum": "Full forum name",
  "address": "Generic address format for that forum type in the given state",
  "filing_fee": "Amount in rupees",
  "jurisdiction_notes": "Why this forum is correct in 2 sentences",
  "avg_resolution": "X-Y months",
  "claim_limit": "Up to X lakh",
  "next_step": "Exact first action the complainant should take"
}
Forums: District Consumer Disputes Redressal Commission (up to 50 lakh), State Commission (50L-2Cr),
National Commission (>2Cr), Civil Court (property/contract), Labour Court, Police Station (IPC crimes).
Consumer forum is preferred for service deficiency cases up to 50 lakh."""


async def find_authority(description: str, state: str = "Maharashtra", amount: str = "") -> dict:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key)
    try:
        resp = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Case: {description}\nState: {state}\nClaim amount: {amount or 'not specified'}\n\nDetermine the correct forum. Return JSON only."},
            ],
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception:
        return {
            "forum": "District Consumer Disputes Redressal Commission",
            "address": f"{state} District Consumer Disputes Redressal Commission",
            "filing_fee": "Rs. 200",
            "jurisdiction_notes": f"Consumer disputes up to Rs. 50 lakh are filed at the District Consumer Forum in {state}.",
            "avg_resolution": "4-6 months",
            "claim_limit": "Up to Rs. 50 lakh",
            "next_step": "File a written complaint with supporting documents and Rs. 200 filing fee at the District Consumer Forum.",
        }
