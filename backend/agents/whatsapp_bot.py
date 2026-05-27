"""WhatsApp Bot — Twilio-powered intake and case status via WhatsApp."""
import logging
import re
from ..config import get_settings

logger = logging.getLogger(__name__)

# Conversation state stored per phone number in Redis (key: wa_state:{phone})
_STATE_TTL = 3600 * 6  # 6 hours


async def handle_whatsapp(from_number: str, body: str, redis=None) -> str:
    """Process an incoming WhatsApp message and return the reply text."""
    settings = get_settings()
    body = body.strip()
    body_lower = body.lower()

    state = await _get_state(from_number, redis)

    # ── GREET / RESET ──────────────────────────────────────────────
    if not state or body_lower in ("hi", "hello", "start", "नमस्ते", "help"):
        await _set_state(from_number, {"step": "await_desc"}, redis)
        return (
            "🙏 *Namaste! Welcome to SahAIyak — India's Free Legal AI.*\n\n"
            "I can help you:\n"
            "• 📋 Analyze your legal problem\n"
            "• ⚖️ Find applicable laws\n"
            "• 📄 Draft a legal notice\n"
            "• 🏛️ Tell you where to file your case\n\n"
            "*Please describe your problem in a few sentences.*\n"
            "_Example: My landlord is not returning my ₹50,000 deposit after 2 months._"
        )

    # ── COLLECT DESCRIPTION ────────────────────────────────────────
    if state.get("step") == "await_desc":
        if len(body) < 20:
            return "Please describe your problem in more detail so I can help you properly."
        await _set_state(from_number, {"step": "await_state", "description": body}, redis)
        return (
            "Got it! 📝\n\n"
            "*Which state are you in?*\n"
            "_(Example: Maharashtra, Delhi, Karnataka)_"
        )

    if state.get("step") == "await_state":
        await _set_state(from_number, {
            "step": "await_amount",
            "description": state.get("description", ""),
            "state": body,
        }, redis)
        return "What is the approximate amount involved? _(Example: ₹80,000)_"

    if state.get("step") == "await_amount":
        desc = state.get("description", "")
        user_state = state.get("state", "Maharashtra")
        amount = body

        await _set_state(from_number, {"step": "analyzing"}, redis)
        reply = await _run_quick_analysis(desc, user_state, amount, settings)
        await _set_state(from_number, {"step": "done", "description": desc}, redis)
        return reply

    # ── FOLLOW-UP IN DONE STATE ────────────────────────────────────
    if state.get("step") == "done":
        if any(w in body_lower for w in ("notice", "draft", "letter")):
            return (
                "📄 To get your full legal notice, visit:\n"
                "*https://sahayak-api-202376712479.asia-south1.run.app/intake*\n\n"
                "Your case will be analyzed and a complete legal notice drafted in under 30 seconds."
            )
        if any(w in body_lower for w in ("rti", "right to information")):
            return (
                "📋 For RTI applications, visit:\n"
                "*https://sahayak-api-202376712479.asia-south1.run.app/rti*"
            )
        if any(w in body_lower for w in ("new", "another", "नई", "start over")):
            await _set_state(from_number, None, redis)
            return "Starting fresh! Please describe your new problem."
        return (
            "I'm here to help! You can:\n"
            "• Type *new* to start a fresh case\n"
            "• Type *notice* to get a legal notice\n"
            "• Type *rti* for RTI help\n"
            "• Visit: sahayak-api-202376712479.asia-south1.run.app"
        )

    return "Type *hi* to start."


async def _run_quick_analysis(description: str, state: str, amount: str, settings) -> str:
    """Quick 3-point AI analysis for WhatsApp (shorter than full web analysis)."""
    if not settings.groq_api_key:
        return _fallback_analysis(description, state, amount)

    system = """You are a concise Indian legal assistant replying via WhatsApp. Given a case, provide:
1. WIN CHANCE: X% + one-line reason
2. KEY LAW: Most relevant act + section (one line)
3. WHERE TO FILE: Exact forum + city
4. NEXT STEP: Single most important action

Keep total response under 200 words. Use *bold* for WhatsApp formatting."""

    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=settings.groq_api_key)
        resp = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Case: {description}\nState: {state}\nAmount: {amount}"},
            ],
            temperature=0.4,
            max_tokens=350,
        )
        analysis = resp.choices[0].message.content or ""
        return (
            "⚖️ *SahAIyak Quick Analysis*\n\n"
            + analysis
            + "\n\n📱 _For full analysis with legal notice, evidence coach & court filing guide:_\n"
            "sahayak-api-202376712479.asia-south1.run.app"
        )
    except Exception as e:
        logger.warning("WhatsApp analysis failed: %s", e)
        return _fallback_analysis(description, state, amount)


def _fallback_analysis(desc, state, amount):
    return (
        f"⚖️ *SahAIyak Quick Analysis*\n\n"
        f"Based on your description:\n\n"
        f"*NEXT STEP:* Send a formal legal notice to the opposite party citing the relevant law.\n\n"
        f"For a complete analysis with win probability, legal notice draft, and court filing guide:\n"
        f"📱 sahayak-api-202376712479.asia-south1.run.app\n\n"
        f"_Type *new* for another case._"
    )


async def _get_state(phone: str, redis) -> dict:
    if not redis:
        return {}
    try:
        import json
        val = await redis.get(f"wa_state:{phone}")
        return json.loads(val) if val else {}
    except Exception:
        return {}


async def _set_state(phone: str, state, redis):
    if not redis:
        return
    try:
        import json
        if state is None:
            await redis.delete(f"wa_state:{phone}")
        else:
            await redis.setex(f"wa_state:{phone}", _STATE_TTL, json.dumps(state))
    except Exception:
        pass


async def send_whatsapp(to: str, message: str, settings) -> bool:
    """Send a WhatsApp message via Twilio."""
    if not (settings.twilio_account_sid and settings.twilio_auth_token and settings.twilio_whatsapp_number):
        logger.warning("Twilio not configured — WhatsApp send skipped")
        return False
    try:
        import httpx, base64
        creds = base64.b64encode(
            f"{settings.twilio_account_sid}:{settings.twilio_auth_token}".encode()
        ).decode()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
                headers={"Authorization": f"Basic {creds}"},
                data={
                    "From": f"whatsapp:{settings.twilio_whatsapp_number}",
                    "To": f"whatsapp:{to}",
                    "Body": message,
                },
                timeout=10,
            )
            return resp.status_code == 201
    except Exception as e:
        logger.warning("Twilio send failed: %s", e)
        return False
