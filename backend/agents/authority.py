import json
from groq import AsyncGroq
from ..config import get_settings

_MODEL = "llama-3.3-70b-versatile"

_SYSTEM = """You are an Indian court jurisdiction expert with deep knowledge of exact court addresses and localities.
Given a case description and state, determine the correct forum and return its REAL physical address with locality.

Return ONLY valid JSON (no markdown):
{
  "forum": "Full official forum name",
  "address": "Specific real address with locality/area name, landmark, city, PIN (e.g. 'Plot 42, Near Collector Office, Bandra East, Mumbai – 400051')",
  "locality": "Area/neighbourhood name where the court is located (e.g. 'Bandra', 'Andheri', 'Jogeshwari')",
  "filing_fee": "Amount in rupees",
  "jurisdiction_notes": "Why this forum is correct in 2 sentences. Mention the specific locality.",
  "avg_resolution": "X-Y months",
  "claim_limit": "Up to X lakh",
  "next_step": "Exact first action with specific locality name of the court"
}

Forum selection rules:
- District Consumer Disputes Redressal Commission (DCDRC): claims up to ₹50 lakh — service deficiency, goods defect
- State Consumer Disputes Redressal Commission: claims ₹50L – ₹2Cr
- National Consumer Disputes Redressal Commission: claims above ₹2Cr (New Delhi, Connaught Place)
- Civil Court / Small Causes Court: property disputes, contract, money recovery
- Labour Court / Industrial Tribunal: salary disputes, wrongful termination
- Police Station: IPC offences (fraud, cheating, theft)

Known Maharashtra court localities (use these exact localities):
- Mumbai City/South: Dhobi Talao area, near CST
- Mumbai Suburban (Andheri, Jogeshwari, Goregaon, Malad): Bandra or Andheri DCDRC, Plot 11-12 Govt Colony, Bandra East
- Thane: Collector Office compound, Thane West
- Pune: Near Collector Office, Shivajinagar
- Nagpur: Civil Lines area
- Nashik: Near Collector Office, Nashik Road

For other states use the state capital district headquarters locality.
If the case description mentions a specific area (e.g., Jogeshwari, Andheri, Bandra), pick the nearest known court locality."""


async def find_authority(description: str, state: str = "Maharashtra", amount: str = "") -> dict:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key)
    try:
        resp = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Case: {description}\nState: {state}\nClaim amount: {amount or 'not specified'}\n\nDetermine the correct forum with its REAL locality-specific address. Include the area name (e.g. Jogeshwari, Andheri, Bandra) in both address and locality fields. Return JSON only."},
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
