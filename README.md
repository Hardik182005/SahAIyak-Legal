# SahAIyak — India's AI Legal Intelligence Platform

> **"Sahayak" (सहायक) means helper.** SahAIyak puts the power of a senior advocate, a data scientist, and a litigation strategist into the hands of every Indian citizen — for free.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Cloud%20Run-4285F4?style=for-the-badge&logo=google-cloud&logoColor=white)](https://sahayak-api-202376712479.asia-south1.run.app)
[![Python](https://img.shields.io/badge/Python-3.12-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Groq](https://img.shields.io/badge/Groq-Llama%203.3%2070B-F55036?style=for-the-badge&logo=meta&logoColor=white)](https://groq.com)
[![Pinecone](https://img.shields.io/badge/Pinecone-Vector%20DB-1A1AFF?style=for-the-badge&logo=pinecone&logoColor=white)](https://pinecone.io)
[![Google Cloud](https://img.shields.io/badge/GCP-asia--south1-4285F4?style=for-the-badge&logo=google-cloud&logoColor=white)](https://cloud.google.com)
[![ElevenLabs](https://img.shields.io/badge/ElevenLabs-TTS-000000?style=for-the-badge&logo=elevenlabs&logoColor=white)](https://elevenlabs.io)

---

## Live Deployment

| Service | URL |
|---|---|
| **App (Frontend + API)** | https://sahayak-api-202376712479.asia-south1.run.app |
| **Health Check** | https://sahayak-api-202376712479.asia-south1.run.app/health |
| **Intake Form** | https://sahayak-api-202376712479.asia-south1.run.app/intake |
| **Dashboard** | https://sahayak-api-202376712479.asia-south1.run.app/dashboard |
| **API Docs** | https://sahayak-api-202376712479.asia-south1.run.app/docs |

---

## The Problem

**1.4 billion Indians. ~70,000 active consumer complaints per month. Less than 1 lawyer per 1,000 people in rural India.**

When a landlord refuses to return a ₹1 lakh deposit, or an employer withholds salary, or an e-commerce platform ignores a refund — most Indians have no idea what to do. Legal help costs ₹2,000–₹10,000 per consultation. Court processes are opaque and intimidating.

**SahAIyak changes that.**

---

## What SahAIyak Does

Submit your case in plain language. Within 30 seconds, four specialized AI agents analyze it in parallel and deliver:

| Feature | What You Get |
|---|---|
| **Win Probability** | Semantic search over 10,000+ real Supreme Court & consumer forum judgments → exact probability with similar case citations |
| **Applicable Laws** | Every relevant IPC, CPC, Consumer Protection Act, RERA, Wages Act section — explained in plain English |
| **Evidence Coach** | What you have, what you're missing, how each piece affects your probability |
| **Legal Notice** | A complete, ready-to-send formal demand notice — citing actual acts and sections — in under 30 seconds |
| **Where to File** | Exact forum (Consumer Forum / Civil Court / Labour Court / Police), address, fee, avg resolution time |
| **Sentry AI Chat** | Ask anything about your case — voice-enabled, Hindi/English, backed by Groq Llama 3.3 70B |
| **Opponent Playbook** | What your opponent will argue and exactly how your notice pre-empts each argument |
| **Voice Mode** | ElevenLabs multilingual TTS — hear your case summary and Sentry responses |

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
│  POST /api/v1/cases  → asyncio.gather() 4 agents                │
│  GET  /api/v1/cases/{id}                                         │
│  POST /api/v1/cases/{id}/sentry  (Sentry AI chat)               │
│  POST /api/v1/voice/speak        (ElevenLabs TTS)                │
│  GET  /health                                                    │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  PARALLEL AGENT PIPELINE  (asyncio.gather, ~1.8s total)   │  │
│  │                                                            │  │
│  │  law_finder.py    ─→ Groq Llama 3.3 70B ─→ acts+sections │  │
│  │  authority.py     ─→ Groq Llama 3.3 70B ─→ forum+fee      │  │
│  │  win_predictor.py ─→ Gemini embed → Pinecone → %           │  │
│  │  evidence_coach.py─→ Groq Llama 3.3 70B ─→ gaps+strengths │  │
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
│  Pinecone (gcp-us-central1) — 10k+ judgment vectors (3072-dim)  │
│  GCS gs://sahaiyak/archive.zip — 10k+ SC judgment PDFs          │
│  Cloud SQL PostgreSQL 15 (asia-south1) — cases, notices         │
│  Secret Manager — all API keys (never in code)                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Backend** | FastAPI 0.115, Python 3.12, asyncio |
| **LLM (text)** | Groq `llama-3.3-70b-versatile` (200 tok/s, free tier) |
| **LLM (embed)** | Google `gemini-embedding-001` (3072-dim) |
| **Vector DB** | Pinecone Serverless (gcp-us-central1) |
| **Voice** | ElevenLabs `eleven_multilingual_v2` (Hindi + English) |
| **Database** | SQLAlchemy async + aiosqlite/asyncpg |
| **Cache** | Redis (Memorystore) |
| **Deploy** | Google Cloud Run (asia-south1, 2GB RAM) |
| **Build** | Cloud Build → Artifact Registry |
| **Secrets** | Secret Manager |
| **Dataset** | GCS `gs://sahaiyak/archive.zip` (Indian Kanoon SC judgments) |

---

## AI Stack Detail

| Agent | Model | Provider | Latency |
|---|---|---|---|
| Law Finder | Llama 3.3 70B | Groq | ~0.8s |
| Authority Agent | Llama 3.3 70B | Groq | ~0.7s |
| Evidence Coach | Llama 3.3 70B | Groq | ~0.9s |
| Win Predictor | gemini-embedding-001 + Pinecone | Google + Pinecone | ~1.2s |
| Notice Drafter | Llama 3.3 70B | Groq | ~1.5s |
| Sentry Chat | Llama 3.3 70B / Gemini 2.0 Flash | Groq + Google | ~0.6s |
| Voice TTS | eleven_multilingual_v2 | ElevenLabs | ~1.5s |

**Total pipeline latency: ~1.8s** (agents run in parallel via `asyncio.gather`)

---

## Privacy & Compliance (DPDP Act 2023)

- **PII Anonymization**: Phone (10-digit), Aadhaar (12-digit), PAN, email, pincode stripped before every LLM call
- **Data Retention**: All case data auto-deleted after 30 days
- **No training**: Groq and Google AI APIs do not train on user data (API tier)
- **Session-based**: No account/registration required
- **Secrets**: All API keys in GCP Secret Manager — never in code

---

## Quick Start (Local Dev)

```bash
# 1. Clone
git clone https://github.com/2005sahildeshmukh/SahAIyak.git
cd SahAIyak

# 2. Create .env
cp .env.example .env
# Fill in your API keys (Groq is free at console.groq.com)

# 3. Install deps
pip install -r backend/requirements.txt

# 4. Start backend (SQLite — no Postgres needed locally)
uvicorn backend.main:app --reload --port 8000

# 5. Open: http://localhost:8000/
```

### .env keys

```env
GEMINI_API_KEY=       # Google AI Studio (for embeddings)
GROQ_API_KEY=         # Groq (free, 6000 req/day)
ELEVENLABS_API_KEY=   # ElevenLabs (voice)
PINECONE_API_KEY=     # Pinecone (vector search)
PINECONE_HOST=        # Pinecone index host URL
DATABASE_URL=sqlite+aiosqlite:///./sahayak.db  # local
REDIS_URL=            # optional for local dev
```

---

## Judgment Dataset Ingestion

```bash
# From GCS (production — archive.zip in gs://sahaiyak/)
pip install google-cloud-storage
python scripts/ingest_judgments.py --gcs gs://sahaiyak/archive.zip

# From local zip
python scripts/ingest_judgments.py --zip /path/to/archive.zip --limit 500
```

Processes: extracts PDF text → detects outcome → Gemini embeds → Pinecone upsert

---

## GCP Deployment

```bash
# One-command deploy (requires gcloud auth as avinashgehi3@gmail.com)
bash scripts/gcp_deploy.sh
```

GCP Project: `sahaiyak` (202376712479) | Region: `asia-south1` (Mumbai)

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/cases` | Submit case → run agents → `case_id` |
| `GET` | `/api/v1/cases/{id}` | Full analysis (laws, win%, evidence, forum) |
| `GET` | `/api/v1/cases/{id}/notice` | Legal notice text |
| `POST` | `/api/v1/cases/{id}/notice` | Modify notice |
| `POST` | `/api/v1/cases/{id}/sentry` | Sentry AI chat |
| `POST` | `/api/v1/cases/{id}/drafter` | Notice editor chat |
| `POST` | `/api/v1/voice/speak` | ElevenLabs TTS → MP3 |
| `GET` | `/health` | Health check |

**POST /api/v1/cases example:**
```json
{
  "description": "My landlord is refusing to return my ₹80,000 security deposit after I moved out 3 months ago",
  "state": "Maharashtra",
  "amount": "₹80,000",
  "evidence_text": "WhatsApp messages, NEFT receipt, signed agreement"
}
```

---

## Pages

| Page | URL | Description |
|---|---|---|
| Home | `/` | Landing — value prop, manifesto |
| Intake | `/intake` | Case submission form |
| Dashboard | `/dashboard` | Win%, evidence coach, similar cases, playbook |
| Document | `/document` | Legal notice viewer + AI editor |
| Manifesto | `/manifesto` | The mission |
| Settings | `/settings` | Language, data controls |

---

## License

MIT — Built to give every Indian their legal rights back.

GCP Project: `sahaiyak` (202376712479) | Account: avinashgehi3@gmail.com

> *"The law is not a luxury. It is the language of rights."*
