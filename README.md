# SahAIyak — India's AI Legal Intelligence Platform

> **"Sahayak" (सहायक) means helper.** SahAIyak puts the power of a senior advocate, a data scientist, and a litigation strategist into the hands of every Indian citizen — for free.

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
│  FRONTEND (Firebase Hosting)                                      │
│  index.html · intake.html · dashboard.html · document.html       │
│  static/api.js — shared fetch wrapper + speakText() (ElevenLabs)│
└─────────────────────┬────────────────────────────────────────────┘
                      │ HTTPS
┌─────────────────────▼────────────────────────────────────────────┐
│  BACKEND (FastAPI on Cloud Run — asia-south1)                    │
│                                                                   │
│  POST /api/v1/cases  →  asyncio.gather() all 4 agents            │
│  GET  /api/v1/cases/{id}                                         │
│  GET/POST /api/v1/cases/{id}/notice                              │
│  POST /api/v1/cases/{id}/sentry                                  │
│  POST /api/v1/cases/{id}/drafter                                 │
│  POST /api/v1/voice/speak    (ElevenLabs TTS proxy)              │
│  GET  /health                                                     │
│                                                                   │
│  ┌───────────────────────────────────────────────────────────┐   │
│  │  AGENT PIPELINE (parallel asyncio.gather)                 │   │
│  │                                                           │   │
│  │  law_finder.py    → Groq Llama 3.3 70B → applicable laws │   │
│  │  authority.py     → Groq Llama 3.3 70B → correct forum   │   │
│  │  win_predictor.py → Gemini Embeddings → Pinecone → %      │   │
│  │  evidence_coach.py→ Groq Llama 3.3 70B → evidence gaps   │   │
│  │                                                           │   │
│  │  notice_drafter.py (after gather) → full legal notice     │   │
│  │  sentry.py       → Groq primary / Gemini fallback         │   │
│  │  voice.py        → ElevenLabs multilingual TTS            │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                   │
│  utils/anonymizer.py  — strips PII before every LLM call        │
│  utils/cleanup.py     — APScheduler deletes data after 30 days  │
│                                                                   │
│  Cache: Redis (Memorystore) · DB: PostgreSQL (Cloud SQL)        │
└──────────────────────────────────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────────────┐
│  DATA LAYER                                                       │
│  Pinecone (gcp-us-central1) — 10,000+ judgment vectors (768-dim)│
│  GCS bucket gs://sahaiyak/archive/ — source PDFs (Indian Kanoon)│
│  Cloud SQL PostgreSQL (asia-south1) — cases, notices, results   │
│  Redis Memorystore — analysis cache (1 hr TTL)                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## AI Stack

| Component | Model | Provider | Purpose |
|---|---|---|---|
| Law Finder | Llama 3.3 70B Versatile | Groq (free) | Indian statute identification |
| Authority Agent | Llama 3.3 70B Versatile | Groq (free) | Forum selection |
| Evidence Coach | Llama 3.3 70B Versatile | Groq (free) | Evidence gap analysis |
| Notice Drafter | Llama 3.3 70B Versatile | Groq (free) | Legal notice drafting |
| Win Predictor | gemini-embedding-001 + Pinecone | Google AI | Semantic case matching |
| Sentry Chat | Llama 3.3 70B / Gemini 2.0 Flash | Groq + Google | Legal Q&A assistant |
| Voice | eleven_multilingual_v2 | ElevenLabs | Hindi/English TTS |

**Why Groq?** 200 tokens/second inference — sub-2-second responses for all 4 agents in parallel.

---

## Privacy & Compliance

- **PII Anonymization**: Phone numbers, Aadhaar, PAN, email stripped before every LLM call
- **Data Retention**: All case data auto-deleted after 30 days (DPDP Act 2023 compliance)
- **No training**: Groq and Google AI APIs do not train on your data (API tier)
- **No auth required**: Session-based, no account needed
- **CORS restricted**: Production CORS locked to known origins

---

## Quick Start (Local Dev)

```bash
# 1. Clone
git clone https://github.com/Hardik182005/SahAIyak.git
cd SahAIyak

# 2. Create .env (copy from example)
cp .env.example .env
# Fill in your API keys

# 3. Install backend deps
cd backend && pip install -r requirements.txt

# 4. Start backend (SQLite locally, no Postgres needed)
uvicorn backend.main:app --reload --port 8000

# 5. Open frontend
# Just open index.html in a browser
# API auto-detected at localhost:8000
```

### Environment Variables

```env
GEMINI_API_KEY=       # Google AI Studio key (for embeddings)
GROQ_API_KEY=         # Groq API key (free tier, fast)
ELEVENLABS_API_KEY=   # ElevenLabs key (for voice)
PINECONE_API_KEY=     # Pinecone API key
PINECONE_HOST=        # Pinecone index host URL
DATABASE_URL=         # postgresql://... or sqlite+aiosqlite:///./dev.db
REDIS_URL=            # redis://localhost:6379
```

---

## Judgment Dataset Ingestion

SahAIyak's Win Predictor is powered by semantic search over **10,000+ Indian Supreme Court judgments** from Indian Kanoon.

```bash
# From GCS bucket (production)
python scripts/ingest_judgments.py --gcs gs://sahaiyak/archive/ --batch 50

# From local zip
python scripts/ingest_judgments.py --zip /path/to/archive.zip --limit 500
```

The script:
1. Reads PDFs (supports zip or GCS bucket)
2. Extracts text from first 5 pages via pypdf
3. Detects outcome (ALLOWED / DISMISSED / UPHELD / PARTIAL)
4. Embeds with `gemini-embedding-001` (3072-dim)
5. Batch-upserts to Pinecone `sahayak-judgments` index

---

## GCP Deployment (One Command)

Prerequisites: `gcloud` CLI authenticated as `avinashgehi3@gmail.com`, billing enabled.

```bash
bash scripts/gcp_deploy.sh
```

What it does:
1. Enables 9 GCP APIs (Cloud Run, SQL, Redis, Secret Manager, etc.)
2. Creates Artifact Registry Docker repo (`asia-south1`)
3. Provisions Cloud SQL PostgreSQL 15 (`asia-south1`, db-f1-micro)
4. Creates VPC connector for Memorystore Redis access
5. Creates Memorystore Redis (`asia-south1`, Basic 1GB)
6. Stores all secrets in Secret Manager (never in code)
7. Builds Docker image via Cloud Build
8. Deploys to Cloud Run (2GB RAM, autoscale 0→10)
9. Deploys frontend to Firebase Hosting

**Production URLs:**
- Backend: `https://sahayak-api-XXXX-el.a.run.app`
- Frontend: `https://sahaiyak.web.app`

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/cases` | Submit case → run 4 agents → return `case_id` |
| `GET` | `/api/v1/cases/{id}` | Full analysis (laws, win%, evidence, authority) |
| `GET` | `/api/v1/cases/{id}/notice` | Get latest legal notice text |
| `POST` | `/api/v1/cases/{id}/notice` | Regenerate/modify notice |
| `POST` | `/api/v1/cases/{id}/sentry` | Sentry AI chat |
| `POST` | `/api/v1/cases/{id}/drafter` | Notice editor AI chat |
| `POST` | `/api/v1/voice/speak` | ElevenLabs TTS → MP3 audio |
| `GET` | `/health` | Health check |

### POST /api/v1/cases

```json
{
  "description": "My landlord is refusing to return my ₹80,000 security deposit...",
  "state": "Maharashtra",
  "amount": "₹80,000",
  "date_started": "2024-01-15",
  "evidence_text": "WhatsApp messages, NEFT receipt, signed agreement",
  "language": "en"
}
```

Response:
```json
{
  "case_id": "550e8400-e29b-41d4-a716-446655440000",
  "win_probability": 74,
  "message": "Case analysis complete"
}
```

---

## Database Schema

```sql
cases(
  id UUID PRIMARY KEY,
  session_id TEXT, description TEXT, state TEXT, amount TEXT,
  date_started TEXT, evidence_text TEXT, language TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
)

analysis_results(
  id UUID PRIMARY KEY, case_id UUID REFERENCES cases(id),
  win_probability INT,
  law_data JSONB,       -- { laws: [...], summary: "..." }
  authority_data JSONB, -- { forum, address, filing_fee, ... }
  evidence_data JSONB,  -- { strengths, gaps, score, tip }
  similar_cases JSONB,  -- [{ year, court, outcome, amount, key_fact }]
  created_at TIMESTAMPTZ DEFAULT NOW()
)

legal_notices(
  id UUID PRIMARY KEY, case_id UUID REFERENCES cases(id),
  notice_text TEXT, version INT DEFAULT 1,
  created_at TIMESTAMPTZ DEFAULT NOW()
)
```

---

## Pages

| Page | Description |
|---|---|
| `index.html` | Landing — value prop, hero animation, manifesto |
| `intake.html` | Case intake form — description, state, amount, evidence |
| `dashboard.html` | Full analysis — win%, evidence coach, similar cases, playbook, topology canvas |
| `document.html` | Legal notice viewer + drafter AI chat |
| `manifesto.html` | The vision: legal rights for all 1.4B Indians |
| `settings.html` | User preferences, language, data controls |

---

## Key Technical Decisions

**Why Groq over Gemini for text generation?**
Gemini's free tier quota (15 req/min) is exhausted quickly in demo conditions. Groq's free tier allows 6,000 req/day at 200 tok/s — making the 4-agent parallel pipeline sub-2-second. Gemini is reserved for embeddings (only needed at ingest time).

**Why SQLite locally + PostgreSQL in production?**
Zero-friction local dev — no Docker required. The `_make_async_url()` helper transparently switches between `aiosqlite` and `asyncpg` based on the `DATABASE_URL` prefix.

**Why asyncio.gather() for agents?**
Law Finder + Authority + Win Predictor + Evidence Coach run in parallel — total latency is max(individual) not sum. Typical: 1.8s for all four.

**Why Pinecone over a local vector store?**
10,000+ 3072-dim vectors at sub-100ms query latency. Pinecone Serverless on GCP us-central1 is co-located with the embedding model.

**DPDP Act 2023 compliance**
The `anonymizer.py` strips 5 PII patterns (Aadhaar, PAN, phone, email, pincode) before any LLM call. APScheduler runs a hard delete of all cases older than 30 days daily at 2 AM IST.

---

## Roadmap

- [ ] Hindi/Marathi full UI translation
- [ ] Document upload (parse PDF evidence with Gemini Vision)
- [ ] RTI filing assistant
- [ ] Labour court e-filing integration
- [ ] WhatsApp bot (Twilio) — file a case by sending a voice note
- [ ] District court scraper for live case status
- [ ] Lawyer referral marketplace (1-on-1 at ₹499)

---

## Team

Built at **[Hackathon Name]** — **SahAIyak** by Team Hardik

GCP Project: `sahaiyak` (202376712479)  
Contact: hardikhinduja399@gmail.com

---

## License

MIT License. Built to give every Indian their legal rights back.

> *"The law is not a luxury. It is the language of rights."*
