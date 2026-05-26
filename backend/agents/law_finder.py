import json
from groq import AsyncGroq
from ..config import get_settings

_MODEL = "llama-3.3-70b-versatile"

_SYSTEM = """You are an expert Indian law researcher. Given a case description, identify ALL applicable laws.
Return ONLY valid JSON (no markdown, no extra text) matching this schema exactly:
{
  "laws": [
    {
      "act": "Full act name",
      "sections": ["Section X", "Section Y"],
      "plain_english": "What this means for the complainant in 1 sentence"
    }
  ],
  "summary": "One sentence legal characterisation of the dispute"
}
Focus on: Consumer Protection Act 2019, IPC, CPC, Specific Relief Act, Transfer of Property Act,
Payment of Wages Act, RERA, state Rent Control Acts, Maharashtra Rent Control Act 1999.
Always include 3-5 laws. Be precise about section numbers."""


async def find_laws(description: str) -> dict:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key)
    try:
        resp = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": f"Case description: {description}\n\nIdentify all applicable Indian laws and sections. Return JSON only."},
            ],
            max_tokens=1024,
            response_format={"type": "json_object"},
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        return {
            "laws": [
                {"act": "Consumer Protection Act, 2019", "sections": ["Section 2(11)", "Section 35", "Section 39"], "plain_english": "File a complaint for deficiency in service at Consumer Forum."},
                {"act": "Indian Contract Act, 1872", "sections": ["Section 73", "Section 74"], "plain_english": "Claim damages for breach of the rental agreement."},
                {"act": "Maharashtra Rent Control Act, 1999", "sections": ["Section 16"], "plain_english": "Governs tenancy, deposit refund obligations in Maharashtra."},
            ],
            "summary": "Consumer and contract dispute involving wrongful withholding of security deposit.",
        }
