"""ADR Negotiation Simulator — AI plays the opponent, Sentry coaches the user."""
import httpx
import logging
from ..config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM = """You are simultaneously playing TWO roles in an Indian legal negotiation simulation:

ROLE 1 — THE OPPONENT: You play the opposing party (landlord / employer / seller). Use realistic Indian legal defences, start with low-ball offers, be firm but not absurd. Keep responses short (1-3 sentences). Never capitulate immediately.

ROLE 2 — SENTRY COACH: You advise the user's side with sharp, specific coaching. Cite Indian law sections where relevant.

Format your response EXACTLY as:
OPPONENT: [what the opponent says]
COACH: [one-sentence coaching tip for the user]

Case context will be provided. Always stay in character."""


async def negotiate_turn(
    case_description: str,
    user_message: str,
    history: list,
) -> dict:
    settings = get_settings()

    if not settings.gemini_api_key:
        return {
            "opponent_says": "I can offer ₹20,000 as a goodwill gesture — that's my final word.",
            "coach_whisper": "Do not accept less than 80% of your claim. Stay firm and cite Section 19 of the Consumer Protection Act.",
        }

    messages = []
    messages.append({
        "role": "user",
        "parts": [{"text": _SYSTEM + f"\n\nCASE SUMMARY: {case_description[:600]}"}]
    })
    messages.append({
        "role": "model",
        "parts": [{"text": "Understood. I am ready to play the opponent and coach simultaneously. Please begin the simulation."}]
    })

    for h in history[-10:]:
        messages.append(h)

    messages.append({
        "role": "user",
        "parts": [{"text": f"User says to opponent: {user_message}"}]
    })

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": messages,
                    "generationConfig": {"temperature": 0.85, "maxOutputTokens": 400},
                },
            )
            resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:
        logger.warning("Negotiation Gemini call failed: %s", exc)
        return {
            "opponent_says": "My final offer is ₹30,000. I suggest you reconsider before wasting both our times in court.",
            "coach_whisper": "They are bluffing. Court costs them far more than your full claim. Hold your position.",
        }

    opponent = ""
    coach = ""
    for line in text.splitlines():
        if line.upper().startswith("OPPONENT:"):
            opponent = line[9:].strip()
        elif line.upper().startswith("COACH:"):
            coach = line[6:].strip()

    if not opponent:
        opponent = text.split("COACH:")[0].replace("OPPONENT:", "").strip()

    return {
        "opponent_says": opponent or "I need to consult my lawyer before responding.",
        "coach_whisper": coach or "Stay calm and stick to the facts. Let them make the next move.",
        "history_entry": {
            "role": "model",
            "parts": [{"text": text}],
        },
    }
