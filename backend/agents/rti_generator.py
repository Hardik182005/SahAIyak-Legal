"""RTI Generator — drafts Right to Information Act 2005 applications via Groq."""
import logging
from ..config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM = """You are an expert in India's Right to Information Act, 2005. Draft a formal RTI application.

OUTPUT FORMAT — respond ONLY with valid JSON, no markdown:
{
  "subject": "Brief subject line (1 sentence)",
  "application_text": "Full RTI application text in formal legal language",
  "department_head": "Correct designation of Public Information Officer for this department",
  "fee": "₹10 (RTI fee)",
  "expected_response_days": "30 days (Section 7, RTI Act 2005)",
  "tips": ["tip1", "tip2", "tip3"],
  "follow_up_if_denied": "First Appellate Authority: [designation]. File within 30 days of refusal under Section 19(1)."
}

APPLICATION TEXT REQUIREMENTS:
1. Open with: "To, The Public Information Officer, [Department Name], [State/Centre]"
2. Cite Section 6(1) of RTI Act 2005 for the request
3. List specific, pointed questions (numbered) — not vague requests
4. Close with: "I am depositing the prescribed fee of ₹10 via [postal order/online payment]."
5. End: "Please provide the information within 30 days as mandated by Section 7(1) of the RTI Act, 2005."
6. Sign off: "[Applicant Name], [Address], [Date]"

Keep application crisp — 250-350 words. Questions must be specific and answerable (not "tell me everything")."""


async def generate_rti(
    department: str,
    state: str,
    information_needed: str,
    applicant_name: str = "The Applicant",
    language: str = "en",
) -> dict:
    settings = get_settings()

    if language == "hi":
        lang_note = "IMPORTANT: Write the application_text in Hindi (Devanagari script). Subject may be in English."
    elif language == "hinglish":
        lang_note = "IMPORTANT: Write the application_text in Hinglish — Hindi words written in Roman/Latin script mixed with English. Example: 'Aapko 30 din mein information dena hoga.' Keep the legal citations in English."
    else:
        lang_note = "Write all text in formal English."

    prompt = f"""Draft an RTI application with these details:
Department/Ministry: {department}
State (or Central): {state}
Information needed: {information_needed}
Applicant name: {applicant_name}

{lang_note}

Generate specific, legally valid questions that will compel the PIO to respond."""

    text = ""

    if settings.groq_api_key:
        try:
            from groq import AsyncGroq
            client = AsyncGroq(api_key=settings.groq_api_key)
            resp = await client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1200,
            )
            text = resp.choices[0].message.content or ""
        except Exception as e:
            logger.warning("Groq RTI failed: %s", e)

    if not text and settings.gemini_api_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.gemini_api_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            resp = await model.generate_content_async(
                f"{_SYSTEM}\n\n{prompt}",
                generation_config={"temperature": 0.3, "max_output_tokens": 1200},
            )
            text = resp.text or ""
        except Exception as e:
            logger.warning("Gemini RTI failed: %s", e)

    if not text:
        return _fallback(department, state, information_needed, applicant_name)

    import json, re
    try:
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception:
        pass

    return _fallback(department, state, information_needed, applicant_name)


def _fallback(dept, state, info, name):
    return {
        "subject": f"RTI Request — {dept}, {state}",
        "application_text": f"""To,
The Public Information Officer,
{dept},
{state}

Subject: Application under Right to Information Act, 2005

Sir/Madam,

I, {name}, hereby request the following information under Section 6(1) of the Right to Information Act, 2005:

1. {info}

2. Please provide certified copies of all documents, records, or files relating to the above information.

3. Please provide the names and designations of officials responsible for the above matter.

I am depositing the prescribed fee of ₹10 via Indian Postal Order as required.

Kindly provide the information within 30 days as mandated by Section 7(1) of the RTI Act, 2005. Failure to do so will entitle me to file a First Appeal under Section 19(1).

Yours faithfully,
{name}
Date: ____________
Address: ____________""",
        "department_head": f"Public Information Officer, {dept}",
        "fee": "₹10 (Indian Postal Order)",
        "expected_response_days": "30 days (Section 7, RTI Act 2005)",
        "tips": [
            "Send via Speed Post with AD to get proof of delivery",
            "Keep a copy of everything you submit",
            "If no response in 30 days, file First Appeal immediately",
        ],
        "follow_up_if_denied": "File First Appeal with the First Appellate Authority within 30 days of refusal under Section 19(1). If that also fails, file Second Appeal with Central/State Information Commission under Section 19(3).",
    }
