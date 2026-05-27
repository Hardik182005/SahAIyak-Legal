"""ADR Negotiation Simulator — AI plays the opponent, Sentry coaches the user."""
import httpx
import logging
from ..config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM = """You are running an Indian legal negotiation simulation. Play TWO roles simultaneously.

━━━ ROLE 1 — THE OPPONENT ━━━
You are the opposing party (landlord / employer / seller / service provider). Behave like a real person in a real negotiation:

NEGOTIATION DYNAMICS — follow these rules strictly:
• Round 1-2: Start defensive. Deny liability or offer 20–35% of the claim. Use vague excuses.
• Round 3-4: If user cites evidence or law, show slight softening. Acknowledge "some" issue. Move offer to 40–60%.
• Round 5-6: If user threatens Consumer Forum / Labour Court / police, take it seriously. Move to 65–80%.
• Round 7+: If user is firm and consistent, make a near-full offer (85–95%) or propose full settlement with conditions.
• NEVER repeat the same line from a previous turn — each response must be distinct.
• React SPECIFICALLY to what the user just said — if they mentioned bank transfer proof, acknowledge it; if they cited a law section, respond to it.
• Use realistic Indian language and mindset: mention "adjust kar lete hain", "let's settle this amicably", "my lawyer says", "this will take years in court", etc.
• Be slightly emotional and human — not robotic.

OPPONENT response: 1-3 sentences max. Be specific to the conversation.

━━━ ROLE 2 — SENTRY COACH ━━━
Give the user ONE sharp, specific coaching tip based on the current negotiation state. Cite Indian law (Consumer Protection Act 2019 s.2(9), s.39; Transfer of Property Act s.105; Payment of Wages Act; IPC 406/420 etc.) where relevant. Tell them exactly what leverage to use next.

━━━ OUTPUT FORMAT (exact, no deviation) ━━━
OPPONENT: [opponent's response — specific to this turn]
COACH: [one sharp coaching tip with legal citation if applicable]

Case context will be provided. Track conversation history carefully — never repeat yourself."""


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

    # Round number is half the history length (each round = 1 user + 1 model entry)
    round_num = len(history) // 2 + 1
    if round_num <= 2:
        stance = "You are in Round 1-2: be defensive, deny liability, offer 20-35% of claim max."
    elif round_num <= 4:
        stance = "You are in Round 3-4: soften slightly, acknowledge partial issue, offer 40-60%."
    elif round_num <= 6:
        stance = "You are in Round 5-6: they may threaten court. Be more conciliatory, offer 65-80%."
    else:
        stance = "You are in Round 7+: consider near-full settlement (85-95%) or agree with conditions."

    messages = []
    messages.append({
        "role": "user",
        "parts": [{"text": _SYSTEM + f"\n\nCASE SUMMARY: {case_description[:600]}\n\nCURRENT NEGOTIATION STATE: {stance} (Round {round_num})"}]
    })
    messages.append({
        "role": "model",
        "parts": [{"text": f"Understood. I am in Round {round_num}. I will follow the negotiation dynamics for this round. Ready."}]
    })

    for h in history[-12:]:
        messages.append(h)

    messages.append({
        "role": "user",
        "parts": [{"text": f"[Round {round_num}] User says to opponent: {user_message}"}]
    })

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}",
                json={
                    "contents": messages,
                    "generationConfig": {"temperature": 0.95, "maxOutputTokens": 500},
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
