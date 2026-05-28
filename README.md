# SahAIyak — India's AI Legal Intelligence Platform

> **"Sahayak" (सहायक) means helper.** SahAIyak puts the power of a senior advocate, a data scientist, and a litigation strategist into the hands of every Indian citizen — for free.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Cloud%20Run-4285F4?style=for-the-badge&logo=google-cloud&logoColor=white)](https://sahayak-api-202376712479.asia-south1.run.app)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-F55036?style=for-the-badge&logo=meta&logoColor=white)](https://groq.com)
[![OpenAI](https://img.shields.io/badge/OpenAI-GPT--4o--mini-412991?style=for-the-badge&logo=openai&logoColor=white)](https://openai.com)
[![Pinecone](https://img.shields.io/badge/Pinecone-Vector%20DB-1A1AFF?style=for-the-badge&logo=pinecone&logoColor=white)](https://pinecone.io)
[![Google Cloud](https://img.shields.io/badge/GCP-asia--south1-4285F4?style=for-the-badge&logo=google-cloud&logoColor=white)](https://cloud.google.com)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-TTS-000000?style=for-the-badge&logo=elevenlabs&logoColor=white)](https://elevenlabs.io)
[![Twilio](https://img.shields.io/badge/Twilio-WhatsApp%20Bot-F22F46?style=for-the-badge&logo=twilio&logoColor=white)](https://twilio.com)

---

## Live Deployment

| Service | URL |
|---|---|
| **App (Frontend + API)** | https://sahayak-api-202376712479.asia-south1.run.app |
| **Health Check** | https://sahayak-api-202376712479.asia-south1.run.app/health |
| **Intake Form** | https://sahayak-api-202376712479.asia-south1.run.app/intake |
| **Dashboard** | https://sahayak-api-202376712479.asia-south1.run.app/dashboard |
| **RTI Generator** | https://sahayak-api-202376712479.asia-south1.run.app/rti |
| **Negotiation Simulator** | https://sahayak-api-202376712479.asia-south1.run.app/negotiation |
| **API Docs** | https://sahayak-api-202376712479.asia-south1.run.app/docs |

**GCP Project:** `sahaiyak` (202376712479) | **Region:** `asia-south1` (Mumbai)  
**GitHub:** https://github.com/Hardik182005/SahAIyak-Legal

---

## The Problem

**1.4 billion Indians. ~70,000 active consumer complaints per month. Less than 1 lawyer per 1,000 people in rural India.**

When a landlord refuses to return a ₹1 lakh deposit, or an employer withholds salary, or an e-commerce platform ignores a refund — most Indians have no idea what to do. Legal help costs ₹2,000–₹10,000 per consultation. Court processes are opaque and intimidating.

**SahAIyak changes that.**

---

## What SahAIyak Does

Submit your case in plain language. Within 30 seconds, AI agents analyze it and deliver:

| Feature | What You Get |
|---|---|
| **Win Probability** | Semantic search over 10,000+ real Supreme Court & consumer forum judgments → exact probability with similar case citations |
| **Applicable Laws** | Every relevant IPC, CPC, Consumer Protection Act, RERA, Wages Act section — explained in plain English |
| **Evidence Coach** | What you have, what you're missing, how each piece affects your win probability |
| **Legal Notice** | Complete, ready-to-send formal demand notice citing actual acts and sections — in under 30 seconds |
| **Where to File** | Exact forum (Consumer Forum / Civil Court / Labour Court), real address with locality, filing fee, avg resolution time + Google Maps link |
| **Deadlines & Checklist** | Auto-detected limitation period (1–5 years by case type), filing deadline calculator, case-specific document checklist |
| **Negotiation Simulator** | Practice ADR negotiation — OpenAI GPT-4o-mini plays the opponent, Groq coaches you in real-time. Supports English / Hindi / Hinglish |
| **RTI Generator** | Drafts Right to Information Act 2005 applications for any government department — English, Hindi, or Hinglish |
| **Sentry AI Chat** | Ask anything about your case — voice-enabled, auto-detects Hindi/Hinglish/English |
| **Document OCR** | Upload photos/PDFs of agreements and bills → AI extracts key legal facts |
| **Voice Mode** | ElevenLabs multilingual TTS — hear your case summary, Sentry responses, and coach tips |
| **WhatsApp Bot** | Send `hi` to +1 415 523 8886 (Twilio Sandbox) → full legal analysis via WhatsApp in 3 messages |
| **e-Daakhil Packet** | Pre-filled court filing packet ready for e-Daakhil portal submission |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  CLOUD RUN (asia-south1) — serves frontend + API in one container│
│  https://sahayak-api-202376712479.asia-south1.run.app           │
│                                                                   │
│  GET  /              → index.html                                │
│  GET  /intake        → intake.html                               │
│  GET  /dashboard     → dashboard.html                            │
│  GET  /document      → document.html                             │
│  GET  /negotiation   → negotiation.html                          │
│  GET  /rti           → rti.html                                  │
│  GET  /edaakhil      → edaakhil.html                             │
│  POST /api/v1/cases             → 4 parallel agents              │
│  GET  /api/v1/cases/{id}        → full analysis                  │
│  POST /api/v1/cases/{id}/sentry → Sentry AI chat                 │
│  POST /api/v1/cases/{id}/negotiate → negotiation turn            │
│  POST /api/v1/rti               → RTI application draft          │
│  POST /api/v1/whatsapp          → Twilio WhatsApp webhook         │
│  POST /api/v1/ocr               → document analysis              │
│  POST /api/v1/voice/speak       → ElevenLabs TTS                 │
│  GET  /health                                                    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  PARALLEL AGENT PIPELINE  (asyncio.gather, ~1.8s total)   │  │
│  │                                                            │  │
│  │  law_finder.py    → Groq Llama 3.3 70B → acts+sections    │  │
│  │  authority.py     → Groq Llama 3.3 70B → forum+address    │  │
│  │  win_predictor.py → Vertex embed → Pinecone → %           │  │
│  │  evidence_coach.py→ Groq Llama 3.3 70B → gaps+strengths   │  │
│  │                                                            │  │
│  │  notice_drafter.py (serial, after gather) → full notice   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                   │
│  utils/anonymizer.py  — strip PII before every LLM call         │
│  utils/cleanup.py     — APScheduler: hard-delete after 30 days  │
└──────────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────────────┐
│  DATA                                                             │
│  Pinecone (gcp-us-central1) — 10k+ judgment vectors (768-dim)   │
│  GCS gs://sahaiyak/archive.zip — 10k+ SC judgment PDFs          │
│  SQLite (local dev) / Cloud SQL PostgreSQL 15 (production)       │
│  Redis Memorystore (session cache) / in-memory fallback          │
│  Secret Manager — all API keys (never in code)                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## AI Stack

| Agent | Model | Provider | Notes |
|---|---|---|---|
| Law Finder | Llama 3.3 70B | Groq | JSON mode, ~0.8s |
| Authority Agent | Llama 3.3 70B | Groq | Real address + locality |
| Evidence Coach | Llama 3.3 70B | Groq | Strength/gap scoring |
| Win Predictor | text-embedding-005 + Pinecone | Vertex AI | 768-dim vectors |
| Notice Drafter | Llama 3.3 70B | Groq | Multi-language |
| Sentry Chat | Llama 3.3 70B → Gemini 2.0 Flash | Groq → Google | Auto Hindi/Hinglish/English |
| Negotiation Opponent | GPT-4o-mini → Llama 3.3 70B | OpenAI → Groq | Round-based ADR |
| RTI Generator | Llama 3.3 70B → Gemini 2.0 Flash | Groq → Google | JSON output |
| WhatsApp Bot | Llama 3.3 70B → GPT-4o-mini | Groq → OpenAI | Twilio webhook |
| Document OCR | Gemini 2.0 Flash | Google | Vision + structured extraction |
| Voice TTS | eleven_multilingual_v2 | ElevenLabs | Hindi + English voices |

**Fallback chains:** Groq → OpenAI → static fallback (no single point of failure)

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI 0.115, Python 3.12, asyncio |
| **Primary LLM** | Groq `llama-3.3-70b-versatile` (200 tok/s) |
| **Negotiation LLM** | OpenAI `gpt-4o-mini` (primary), Groq (fallback) |
| **Embeddings** | Google Vertex AI `text-embedding-005` (768-dim) |
| **Vector DB** | Pinecone Serverless (gcp-us-central1) |
| **Voice** | ElevenLabs `eleven_multilingual_v2` |
| **WhatsApp** | Twilio Sandbox / WhatsApp Business API |
| **Database** | SQLAlchemy async + aiosqlite (dev) / asyncpg (prod) |
| **Cache** | Redis Memorystore (prod) / in-memory dict fallback |
| **Deploy** | Google Cloud Run (asia-south1, 2GB RAM) |
| **Build** | Cloud Build → Artifact Registry |
| **Secrets** | GCP Secret Manager |

---

## WhatsApp Bot Setup

### Testing (Sandbox)

1. Go to [console.twilio.com](https://console.twilio.com) → **Messaging → Try it out → Send a WhatsApp message**
2. Click **Sandbox settings**
3. Set **"When a message comes in"** to:
   ```
   https://sahayak-api-202376712479.asia-south1.run.app/api/v1/whatsapp
   ```
   Method: `HTTP POST`
4. Save
5. Join sandbox: send `join <your-code>` to `+1 415 523 8886` on WhatsApp
6. Send `hi` to start

### Bot Conversation Flow

```
User: hi
Bot:  🙏 Namaste! Welcome to SahAIyak... [welcome message]

User: My landlord is not returning my ₹80,000 deposit
Bot:  Got it! Which state are you in?

User: Maharashtra
Bot:  What is the approximate amount involved?

User: 80000
Bot:  ⚖️ SahAIyak Quick Analysis
      WIN CHANCE: 72% — strong evidence trail
      KEY LAW: Consumer Protection Act 2019, Section 35
      WHERE TO FILE: District Consumer Forum, Pune
      NEXT STEP: Send registered legal notice immediately
```

### Follow-up Commands (after analysis)

| Message | Response |
|---|---|
| Any follow-up question | AI answers with case context |
| `notice` | Link to full legal notice |
| `rti` | Link to RTI generator |
| `new` | Start a fresh case |

### Production (Go Live)

Upgrade from sandbox to a real WhatsApp Business number in Twilio → update `TWILIO_WHATSAPP_NUMBER` in Secret Manager.

---

## Pages

| Page | URL | Description |
|---|---|---|
| Home | `/` | Landing — value prop + how it works |
| Intake | `/intake` | Case submission form with OCR upload |
| Dashboard | `/dashboard` | 6-tab analysis: Overview, Win%, Evidence, Where to File, Similar Cases, Deadlines |
| Document | `/document` | Legal notice viewer + AI editor chat |
| Negotiation | `/negotiation` | ADR practice simulator — OpenAI opponent + Groq coach |
| RTI | `/rti` | Right to Information application generator |
| e-Daakhil | `/edaakhil` | Pre-filled court filing packet |
| Manifesto | `/manifesto` | The mission |
| Settings | `/settings` | Language, data controls |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/cases` | Submit case → run 4 parallel agents → `case_id` |
| `GET` | `/api/v1/cases/{id}` | Full analysis (laws, win%, evidence, forum, address) |
| `GET` | `/api/v1/cases/{id}/notice` | Legal notice text |
| `POST` | `/api/v1/cases/{id}/notice` | Modify notice via AI |
| `POST` | `/api/v1/cases/{id}/sentry` | Sentry AI chat |
| `POST` | `/api/v1/cases/{id}/drafter` | Notice editor AI chat |
| `POST` | `/api/v1/cases/{id}/negotiate` | Negotiation turn (opponent + coach) |
| `GET` | `/api/v1/cases/{id}/filing-packet` | e-Daakhil filing packet |
| `POST` | `/api/v1/rti` | Generate RTI application |
| `POST` | `/api/v1/whatsapp` | Twilio WhatsApp webhook |
| `POST` | `/api/v1/ocr` | Document analysis (multipart/form-data) |
| `POST` | `/api/v1/voice/speak` | ElevenLabs TTS → MP3 |
| `GET` | `/health` | Health check |

**POST /api/v1/cases example:**
```json
{
  "description": "My landlord is refusing to return my ₹80,000 security deposit after I moved out 3 months ago",
  "state": "Maharashtra",
  "amount": "80000",
  "evidence_text": "WhatsApp messages, NEFT receipt, signed agreement"
}
```

**POST /api/v1/rti example:**
```json
{
  "department": "Municipal Corporation of Pune",
  "state": "Maharashtra",
  "information_needed": "Status of my road repair complaint filed on 1 Jan 2025",
  "applicant_name": "Raj Kumar",
  "language": "en"
}
```

---

## Quick Start (Local Dev)

```bash
# 1. Clone
git clone https://github.com/Hardik182005/SahAIyak-Legal.git
cd SahAIyak-Legal

# 2. Create .env
cp .env.example .env
# Fill in your API keys

# 3. Install deps
pip install -r backend/requirements.txt

# 4. Start backend (SQLite — no Postgres needed locally)
uvicorn backend.main:app --reload --port 8000

# 5. Open: http://localhost:8000/
```

### .env keys

```env
GEMINI_API_KEY=       # Google AI Studio — for OCR + Gemini fallback
OPENAI_API_KEY=       # OpenAI — negotiation simulator (primary)
GROQ_API_KEY=         # Groq — primary LLM (free, 6000 req/day)
ELEVENLABS_API_KEY=   # ElevenLabs — voice TTS
PINECONE_API_KEY=     # Pinecone — judgment vector search
PINECONE_HOST=        # Pinecone index host URL
PINECONE_INDEX=       # sahayak-judgments
DATABASE_URL=sqlite+aiosqlite:///./sahayak.db   # local SQLite
REDIS_URL=redis://localhost:6379                 # optional locally
TWILIO_ACCOUNT_SID=   # Twilio — WhatsApp bot
TWILIO_AUTH_TOKEN=    # Twilio — WhatsApp bot
TWILIO_WHATSAPP_NUMBER=+14155238886              # Twilio sandbox number
```

---

## Judgment Dataset Ingestion

```bash
# From GCS (production)
python scripts/ingest_judgments.py --gcs gs://sahaiyak/archive.zip

# From local zip
python scripts/ingest_judgments.py --zip /path/to/archive.zip --limit 500
```

Processes: extracts PDF text → detects outcome (WON/LOST/SETTLED) → embeds via Vertex AI → upserts to Pinecone

---

## GCP Deployment

```bash
# One-command full deploy (Cloud SQL + Redis + Cloud Run + Secrets)
bash scripts/gcp_deploy.sh

# Or manual redeploy after a git push:
gcloud builds submit --tag asia-south1-docker.pkg.dev/sahaiyak/sahayak-repo/sahayak-api:latest
gcloud run deploy sahayak-api --image=... --region=asia-south1
```

---

## Privacy & Compliance (DPDP Act 2023)

- **PII Anonymization** — phone, Aadhaar, PAN, email, pincode stripped before every LLM call
- **Data Retention** — all case data auto-deleted after 30 days via APScheduler
- **No training** — Groq, OpenAI, and Google APIs do not train on API-tier user data
- **Session-based** — no account or registration required
- **Secrets** — all API keys in GCP Secret Manager, never in code or environment files in production

---

## License

MIT — Built to give every Indian their legal rights back.

> *"The law is not a luxury. It is the language of rights."*
