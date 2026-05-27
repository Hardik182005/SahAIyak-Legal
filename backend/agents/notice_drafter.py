import json
from groq import AsyncGroq
from ..config import get_settings
from datetime import date

_MODEL = "llama-3.3-70b-versatile"

_SYSTEM = """You are a senior Indian advocate drafting a formal legal notice.
Write a professional, legally sound demand notice in formal English.
The notice must:
- Cite specific acts and section numbers
- State facts clearly in numbered paragraphs
- Make specific demands with a 15-day deadline
- Reference consequences (Consumer Forum, compensation, interest at 12% p.a.)
- Be ready to send via registered post

Format as plain text (no markdown). Use formal legal language.
Include: FROM/TO blocks, date, REF number, salutation, facts, legal basis, demands, warning, closing, signature block."""

_MODIFY_SYSTEM = """You are an AI legal notice editor. Given an existing notice and a modification request, update the notice accordingly.
Keep the same formal structure. Return only the updated notice text (no explanations)."""


def _get_system_prompt_for_lang(language: str) -> str:
    lang_insts = {
        "HI": "Write the notice in formal Hindi using Devanagari script (देवनागरी). Ensure all legal terms are translated professionally.",
        "MR": "Write the notice in formal Marathi using Devanagari script (देवनागरी). Ensure all legal terms are translated professionally.",
        "TA": "Write the notice in formal Tamil using Tamil script (தமிழ்). Ensure all legal terms are translated professionally.",
        "TE": "Write the notice in formal Telugu using Telugu script (తెలుగు). Ensure all legal terms are translated professionally.",
        "BN": "Write the notice in formal Bengali using Bengali script (বাংলা). Ensure all legal terms are translated professionally.",
        "KN": "Write the notice in formal Kannada using Kannada script (ಕನ್ನಡ). Ensure all legal terms are translated professionally.",
        "PA": "Write the notice in formal Punjabi using Gurmukhi script (ਗੁਰਮੁਖੀ). Ensure all legal terms are translated professionally.",
    }
    lang_inst = lang_insts.get(language.upper(), "Write a professional, legally sound demand notice in formal English.")
    return f"""You are a senior Indian advocate drafting a formal legal notice.
{lang_inst}
The notice must:
- Cite specific acts and section numbers
- State facts clearly in numbered paragraphs
- Make specific demands with a 15-day deadline
- Reference consequences (Consumer Forum, compensation, interest at 12% p.a.)
- Be ready to send via registered post

Format as plain text (no markdown). Use formal, professional legal language of the selected language.
Include: FROM/TO blocks, date, REF number, salutation, facts, legal basis, demands, warning, closing, signature block."""


async def draft_notice(
    description: str,
    laws: list,
    authority: dict,
    evidence: dict,
    state: str = "Maharashtra",
    amount: str = "",
    language: str = "EN",
) -> str:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key)

    today = date.today().strftime("%d %B, %Y")
    laws_str = json.dumps(laws, indent=2)
    forum = authority.get("forum", "District Consumer Disputes Redressal Commission")

    system_prompt = _get_system_prompt_for_lang(language)

    prompt = f"""Draft a complete legal notice for this case:

Case Description: {description}

Applicable Laws:
{laws_str}

Recommended Forum: {forum}
State: {state}
Claim Amount: {amount or "as mentioned in case"}
Today's Date: {today}

Generate a complete, ready-to-send legal notice. Plain text only, no markdown."""

    try:
        resp = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return _fallback_notice(description, amount, state, today, forum)


async def modify_notice(existing_notice: str, instruction: str) -> str:
    settings = get_settings()
    client = AsyncGroq(api_key=settings.groq_api_key)
    prompt = f"Existing Notice:\n{existing_notice}\n\nModification Request: {instruction}\n\nUpdated Notice:"
    try:
        resp = await client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _MODIFY_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2048,
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return existing_notice


def _fallback_notice(description: str, amount: str, state: str, today: str, forum: str) -> str:
    return f"""LEGAL NOTICE

Date: {today}
REF: SAHAIYAK/2026/LEGAL-NOTICE

UNDER: The Consumer Protection Act, 2019 & Indian Contract Act, 1872

To,
[Respondent Name and Address]

Sir/Madam,

Under instructions from my client, I hereby serve you with this legal notice:

FACTS:
{description}

LEGAL BASIS:
This constitutes deficiency in service under Section 2(11) of the Consumer Protection Act, 2019
and breach of contract under Section 73 of the Indian Contract Act, 1872.

DEMAND:
1. Immediately settle the matter involving {amount or "the amount in dispute"}.
2. Respond within 15 (fifteen) days from receipt of this notice.

CONSEQUENCE:
Failure to comply will result in proceedings before the {forum} seeking full recovery
plus compensation for harassment, mental agony, and legal costs.

This notice is served without prejudice to all other rights and remedies.

Yours faithfully,
[Complainant Name]
Assisted by SahAIyak Legal Intelligence Platform
"""
