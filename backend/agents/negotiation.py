"""ADR Negotiation Simulator — OpenAI plays the opponent, Sentry coaches the user."""
import logging
from ..config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM = """You are running an Indian legal negotiation simulation. Play TWO roles simultaneously.

━━━ ROLE 1 — THE OPPONENT ━━━
You are the opposing party (landlord / employer / seller / service provider). Behave like a real person in a real negotiation — emotional, self-interested, but eventually reasonable under pressure.

NEGOTIATION DYNAMICS:
• Round 1-2: Defensive. Deny liability. Offer 20–35% of claim with vague excuses.
• Round 3-4: If user cites evidence/law, soften slightly. Acknowledge "some" issue. Offer 40–60%.
• Round 5-6: If user threatens Consumer Forum / court / police, get nervous. Offer 65–80%.
• Round 7+: User is firm and consistent — make near-full offer 85–95% or propose full settlement with conditions.

RULES:
• NEVER repeat the same wording from a previous turn.
• React SPECIFICALLY to what the user just said — mention their evidence, their legal threat, their exact words.
• Use realistic Indian bargaining language: "adjust kar lete hain", "let's be practical", "my lawyer says this will drag for years", "I'm doing this as goodwill", "you have no proof", etc.
• Be human — slightly defensive, emotional, not robotic.
• Opponent response: 2-3 sentences MAX.

━━━ ROLE 2 — SENTRY COACH ━━━
One sharp, specific coaching tip for the USER based on where the negotiation is right now.
Cite Indian law where relevant (Consumer Protection Act 2019, Transfer of Property Act s.105, Payment of Wages Act, IPC 406/420, etc.).
Tell them exactly what to say or do next.

━━━ OUTPUT FORMAT (exact, no deviation) ━━━
OPPONENT: [opponent's response — specific to this turn, never repeat previous lines]
COACH: [one sharp tip with legal citation]"""


async def negotiate_turn(
    case_description: str,
    user_message: str,
    history: list,
    lang: str = "en",
) -> dict:
    settings = get_settings()

    round_num = len(history) // 2 + 1
    if round_num <= 2:
        stance = f"Round {round_num}: be defensive, deny or minimize liability, offer at most 20-35% of claim."
    elif round_num <= 4:
        stance = f"Round {round_num}: soften slightly, acknowledge a partial problem, offer 40-60% of claim."
    elif round_num <= 6:
        stance = f"Round {round_num}: they may threaten legal action — show concern, offer 65-80% of claim."
    else:
        stance = f"Round {round_num}: near-full settlement (85-95%) or propose to settle fully with a condition."

    lang_instruction = (
        "IMPORTANT: The user is writing in Hindi. You MUST reply in Hindi for both OPPONENT and COACH."
        if lang == "hi" else
        "IMPORTANT: The user is writing in English. You MUST reply in English for both OPPONENT and COACH."
    )
    system_prompt = (
        _SYSTEM
        + f"\n\nCASE SUMMARY: {case_description[:600]}"
        + f"\n\nCURRENT ROUND INSTRUCTION: {stance}"
        + f"\n\n{lang_instruction}"
    )

    # Build messages in OpenAI format
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-12:]:
        # history entries use Gemini format {role, parts:[{text}]} — convert to OpenAI
        role = h.get("role", "user")
        if role == "model":
            role = "assistant"
        parts = h.get("parts", [])
        content = parts[0].get("text", "") if parts else h.get("content", "")
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": f"[Round {round_num}] User says to opponent: {user_message}"})

    text = ""

    # Try OpenAI first
    if settings.openai_api_key:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.openai_api_key)
            resp = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.95,
                max_tokens=500,
            )
            text = resp.choices[0].message.content or ""
            logger.info("Negotiation via OpenAI (round=%d)", round_num)
        except Exception as exc:
            logger.warning("OpenAI negotiation failed (%s), trying Groq", exc)

    # Groq fallback
    if not text and settings.groq_api_key:
        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=settings.groq_api_key)
            resp = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                temperature=0.95,
                max_tokens=500,
            )
            text = resp.choices[0].message.content or ""
            logger.info("Negotiation via Groq fallback (round=%d)", round_num)
        except Exception as exc:
            logger.warning("Groq negotiation also failed: %s", exc)

    if not text:
        return {
            "opponent_says": "My final offer is ₹30,000. I suggest you reconsider before we both waste time in court.",
            "coach_whisper": "They are bluffing. Court costs them far more. Hold your position and counter with full amount.",
        }

    opponent = ""
    coach = ""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("OPPONENT:"):
            opponent = stripped[9:].strip()
        elif stripped.upper().startswith("COACH:"):
            coach = stripped[6:].strip()

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
