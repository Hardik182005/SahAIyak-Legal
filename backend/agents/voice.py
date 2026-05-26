"""ElevenLabs Text-to-Speech for SahAIyak legal explanations."""
import httpx
from ..config import get_settings

_API_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_VOICE_EN = "EXAVITQu4vr4xnSDxMaL"   # Sarah — clear, professional English
_VOICE_HI = "pNInz6obpgDQGcFmaJgB"   # Adam — good for Hindi/mixed
_MODEL = "eleven_multilingual_v2"


async def speak(text: str, lang: str = "en") -> bytes:
    """Return MP3 audio bytes for the given text. Returns empty bytes on failure."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return b""

    voice_id = _VOICE_HI if lang in ("hi", "hindi") else _VOICE_EN
    url = _API_URL.format(voice_id=voice_id)
    payload = {
        "text": text[:500],
        "model_id": _MODEL,
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75, "style": 0.2},
    }
    headers = {
        "xi-api-key": settings.elevenlabs_api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code == 200:
                return resp.content
    except Exception:
        pass
    return b""
