# SENTINEL — Clinical Escalation Agent

> **Hackanova 5.0 · The Three Hackeeters**

SENTINEL is a production-grade, real-time clinical escalation platform. It continuously ingests patient vitals from wearable/IoT sensors, runs a five-sublayer AI scoring pipeline, reasons over the data with large language models, and autonomously triggers the appropriate escalation action — SMS alert, email report, EMS dispatch, appointment booking, or fall protocol — without any human in the loop.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Feature Highlights](#feature-highlights)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Scoring Pipeline — Five Sub-Layers](#scoring-pipeline--five-sub-layers)
- [Escalation Engine](#escalation-engine)
- [Frontend Pages](#frontend-pages)
- [Nearby Doctors](#nearby-doctors)
- [ML Model — Isolation Forest](#ml-model--isolation-forest)
- [Testing](#testing)
- [Team](#team)

---

## Architecture Overview

```
CSV Dataset / IoT Sensor
        │
        ▼
 ┌─────────────┐     WebSocket / REST
 │  Simulator  │──────────────────────────────────────────────┐
 └─────────────┘                                              │
        │                                                     ▼
        ▼                                           ┌──────────────────┐
 ┌──────────────────┐   processed reading           │   React Frontend │
 │ Signal Processor │──────────────┐                │  (Vite + Tailwind│
 │  · Plausibility  │              │                │   Dashboard,     │
 │  · Thresholds    │              │                │   Audit Trail,   │
 │  · Trends        │              │                │   System Health, │
 └──────────────────┘              │                │   Settings,      │
        │                          │                │   Nearby Doctors)│
        ▼                          ▼                └──────────────────┘
 ┌──────────────────┐     ┌────────────────┐               ▲
 │  Scoring Engine  │     │  Redis Cache   │               │
 │  SL1 Thresholds  │◄────│  · Vitals buf  │               │
 │  SL2 Context     │     │  · Latest read │    ┌──────────┴──────────┐
 │  SL3 Syndromes   │     │  · OSM cache   │    │   sentinelApi.ts    │
 │  SL4 Trends      │     │  · SERP cache  │    │  (typed fetch layer)│
 │  SL5 Isolation   │     └────────────────┘    └─────────────────────┘
 │     Forest       │
 └──────────────────┘
        │  SHAL band + score
        ▼
 ┌──────────────────┐     ┌─────────────────────────────────────────┐
 │   LLM Reasoning  │────►│  Gemini 2.0 Flash  (primary)            │
 │   · Differential │     │  Claude Opus 4.5   (extended thinking)  │
 │     diagnoses    │     │  Rule Fallback     (offline mode)       │
 │   · Reasoning    │     └─────────────────────────────────────────┘
 │     chain        │
 └──────────────────┘
        │
        ▼
 ┌──────────────────────────────────────────────────┐
 │              Escalation Engine                    │
 │  NOMINAL  → no action                            │
 │  ELEVATED → SMS + email                          │
 │  WARNING  → SMS + email + audit                  │
 │  HIGH     → SMS + email + Calendly appointment   │
 │  CRITICAL → SMS + email + EMS dispatch + audit   │
 │  FALL     → fall protocol (countdown → EMS)      │
 └──────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐
 │   Twilio    │  │  Resend  │  │ Calendly │  │  EMS API  │
 │    SMS      │  │  Email   │  │  Appt.   │  │ Dispatch  │
 └─────────────┘  └──────────┘  └──────────┘  └───────────┘
        │
        ▼
 ┌─────────────────────────────────┐
 │  PostgreSQL Audit Repository    │
 │  (Neon serverless, async)       │
 └─────────────────────────────────┘
```

---

## Feature Highlights

### Real-Time Vitals Processing
- CSV dataset streamed at configurable interval (default 500 ms per row)
- WebSocket endpoint for live sensor integration
- Plausibility bounds validation — rejects physiologically impossible values before scoring
- 30-second Redis TTL cache for the latest reading per patient

### Five-Sublayer AI Scoring Engine
- **SL1 — Threshold Classification**: NEWS2/MEWS-derived rules for HR, SpO₂, RR, Temp, HRV
- **SL2 — Contextual Modifiers**: Stress score, activity context, sleep deficit, HRV acute drop
- **SL3 — Syndrome Detection**: SIRS, Hypoxic Episode, Distributive Shock, Autonomic Collapse, Respiratory Failure, Multi-System Stress, qSOFA
- **SL4 — Trend Analysis**: HR ascent, SpO₂ decline, HRV collapse, inverse HR/SpO₂ patterns
- **SL5 — ML Anomaly (Isolation Forest)**: Sklearn-trained model flags statistical outliers not caught by rules
- Outputs a 0–100 normalised score mapped to five SHAL bands: NOMINAL / ELEVATED / WARNING / HIGH / CRITICAL

### LLM-Powered Medical Reasoning
- **Google Gemini 2.0 Flash** — primary LLM; low-latency differential diagnosis + reasoning chain
- **Anthropic Claude Opus 4.5** — extended thinking mode for complex HIGH/CRITICAL cases
- **Rule Fallback** — deterministic fallback when both LLM APIs are unavailable
- Outputs: `reasoning_summary`, `llm_thinking_chain`, `differential_diagnoses[]`, `confidence`

### Automated Escalation Engine
| SHAL Band | Actions |
|-----------|---------|
| NOMINAL | No action |
| ELEVATED | SMS alert |
| WARNING | SMS + email clinical report |
| HIGH | SMS + email + Calendly scheduling link |
| CRITICAL | SMS + email + EMS dispatch (3-retry with backoff) |
| FALL | Fall protocol — 60-second countdown, then EMS if unacknowledged |

### Fall Detection Protocol
- Detects `fall_event` field in vitals (hard sensor trigger)
- 30-second monitoring window to distinguish likely vs confirmed fall
- 60-second acknowledgement countdown
- Auto-dispatches EMS on timeout
- Can be acknowledged via `POST /api/v1/fall/{patient_id}/acknowledge`

### Notification Services
- **Twilio SMS** — vitals summary + top syndrome + Google Maps patient location link
- **Resend Email** — full HTML clinical report with vitals, score, reasoning, and differential diagnoses
- **Firebase FCM** — push notifications (service-account JSON configurable)
- Emergency contacts managed via API (Redis-backed; env var contacts are defaults)

### Appointment Booking — Calendly
- Generates single-use Calendly scheduling links via `POST /scheduling_links`
- Patient name, email, and reason pre-filled in the booking URL
- Auto-triggered on HIGH-band escalations
- Frontend settings panel for manual booking with event-type dropdown

### Nearby Doctors
- Queries **OpenStreetMap Overpass API** for hospitals, clinics, doctors, pharmacies within configurable radius
- Enriches with **live Google Maps ratings via SerpAPI** (parallel async, Redis-cached 1 hr)
- Scoring: proximity 40% + rating 20% + specialization match 30% + data completeness 10%
- Syndrome-aware: active clinical syndromes from the audit log influence specialization ranking
- OSM results cached in Redis (5 min) to avoid redundant Overpass queries
- **Primary sort by rating** (rated facilities first), secondary by composite score

### Immutable Audit Trail
- Every escalation decision logged to PostgreSQL with full context:
  `patient_id`, `session_id`, `final_score`, `shal_band`, `decision_source`, `reasoning_summary`, `llm_thinking_chain`, `differential_diagnoses`, `ems_dispatched`, `sms_sent`, `email_sent`, `appointment_booked`, `vitals_snapshot`, `syndromes_fired`, `trends_fired`, `actions_latency_ms`

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Backend** | Python 3.11, FastAPI, Uvicorn, Pydantic v2 |
| **Real-Time** | WebSockets, Redis (Upstash TLS) |
| **AI — LLM** | Google Gemini 2.0 Flash, Anthropic Claude Opus 4.5 |
| **AI — ML** | Scikit-learn Isolation Forest, NumPy, Pandas |
| **Database** | PostgreSQL async (Neon serverless) via SQLAlchemy + asyncpg |
| **Notifications** | Twilio (SMS), Resend (email), Firebase FCM (push) |
| **Scheduling** | Calendly REST API v2 |
| **Location** | OpenStreetMap Overpass API, SerpAPI (Google Maps ratings) |
| **Frontend** | React 19, TypeScript, Vite 7, Tailwind CSS v4 |
| **UI Components** | Radix UI, Recharts, Framer Motion, Lucide React |
| **Testing** | Pytest, pytest-asyncio, pytest-mock, fakeredis |
| **Infra** | Docker Compose (local Redis + PostgreSQL) |

---

## Project Structure

```
Hackanova/
├── backend/
│   ├── app/
│   │   ├── main.py                      # FastAPI app, lifespan, router registration
│   │   ├── api/
│   │   │   └── routes/
│   │   │       ├── vitals.py            # POST /ingest, GET /latest/{id}, WS /ws/vitals
│   │   │       ├── simulator.py         # Start/stop/status CSV simulation
│   │   │       ├── audit.py             # Audit log query endpoints
│   │   │       ├── settings.py          # Contacts, test-SMS, test-email, booking
│   │   │       └── doctors.py           # Nearby doctors (OSM + SerpAPI)
│   │   ├── core/
│   │   │   ├── constants.py             # All thresholds, scoring weights, API URLs
│   │   │   ├── redis_client.py          # Async Redis connection wrapper
│   │   │   └── rule_engine.py           # Rule-based threshold classifier
│   │   ├── db/
│   │   │   ├── database.py              # SQLAlchemy async engine + session factory
│   │   │   ├── models.py                # ORM table definitions
│   │   │   └── audit_repository.py      # Write/query audit entries
│   │   ├── ml/
│   │   │   ├── isolation_forest.py      # IsolationForestWrapper (load/predict)
│   │   │   ├── train_isolation_forest.py# Training script
│   │   │   └── sentinel_if.pkl          # Trained model binary
│   │   ├── models/
│   │   │   ├── vitals.py                # VitalReading, ProcessedReading, ThresholdFlag
│   │   │   ├── assessment.py            # RiskAssessment, SHL_BAND, sub-layer results
│   │   │   ├── reasoning.py             # LLMReasoning, DifferentialDiagnosis
│   │   │   └── escalation.py            # ActionResult, ActionStatus, EscalationRecord
│   │   └── services/
│   │       ├── pipeline.py              # VitalsPipeline — orchestrates all stages
│   │       ├── signal_processor.py      # Plausibility + threshold + Redis windowing
│   │       ├── scoring_engine.py        # Five-sublayer scoring (SL1–SL5)
│   │       ├── llm_client.py            # LLM router (Gemini → Claude → fallback)
│   │       ├── gemini_client.py         # Google Gemini 2.0 Flash integration
│   │       ├── llm_prompts.py           # Prompt templates for medical reasoning
│   │       ├── rule_fallback.py         # Deterministic fallback when LLMs unavailable
│   │       ├── escalation_engine.py     # SHAL-band → action dispatcher
│   │       ├── notification_service.py  # Twilio SMS + Resend email + FCM
│   │       ├── ems_service.py           # EMS API with retry/backoff
│   │       ├── appointment_service.py   # Calendly scheduling link creation
│   │       ├── fall_protocol.py         # Fall detection countdown + EMS trigger
│   │       └── simulator.py             # CSV row streamer with configurable interval
│   ├── tests/
│   │   ├── test_scoring_engine.py
│   │   ├── test_signal_processor.py
│   │   ├── test_escalation_engine.py
│   │   └── test_llm_client.py
│   ├── requirements.txt
│   ├── docker-compose.yml
│   ├── run_server.bat
│   └── run_tests.bat
├── frontend/
│   └── Asset-Manager/
│       └── artifacts/
│           └── mockup-sandbox/
│               ├── src/
│               │   ├── components/mockups/sentinel/
│               │   │   ├── _SentinelNav.tsx     # Shared sidebar navigation
│               │   │   ├── Login.tsx             # Authentication page
│               │   │   ├── Dashboard.tsx         # Live vitals dashboard
│               │   │   ├── AuditTrail.tsx        # Escalation audit log viewer
│               │   │   ├── SystemHealth.tsx      # Backend service health monitor
│               │   │   ├── Settings.tsx          # Contacts, notifications, booking
│               │   │   └── NearbyDoctors.tsx     # Nearby facilities finder
│               │   └── lib/
│               │       └── sentinelApi.ts        # Type-safe fetch layer for all APIs
│               ├── vite.config.ts
│               └── package.json
├── data/
│   ├── dataset.csv                      # Synthetic patient vitals dataset
│   └── generate_dataset.py              # Dataset generation script
├── doctors/
│   ├── fetch_doctors.py                 # Standalone OSM doctor finder script
│   └── server.py                        # Standalone HTTP server for the script
└── .env                                 # All credentials (never commit)
```

---

## Getting Started

### Prerequisites

| Requirement | Version |
|-------------|---------|
| Python | 3.11+ |
| Node.js | 18+ |
| pnpm | 8+ |
| Redis | Any (cloud or local) |
| PostgreSQL | Any (cloud or local) |

> **Quickest setup**: Use [Upstash](https://upstash.com) for Redis (free tier) and [Neon](https://neon.tech) for PostgreSQL (free tier). Both are already configured in `.env`.

---

### Backend Setup

```bash
# 1. Clone
git clone https://github.com/ParthChauhan1658/Hackanova.git
cd Hackanova

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate      # macOS/Linux

# 3. Install backend dependencies
pip install -r backend/requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env — see Environment Variables section below

# 5. Run the backend
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
# Or on Windows:
run_server.bat
```

The backend starts on **http://localhost:8000**.
Interactive API docs: **http://localhost:8000/docs**
Health check: **http://localhost:8000/health**

On startup the backend will:
1. Connect to Redis
2. Load the Isolation Forest model from `app/ml/sentinel_if.pkl`
3. Create PostgreSQL tables if they don't exist
4. **Auto-start CSV simulation** — streams `data/dataset.csv` through the full pipeline every 500 ms

---

### Frontend Setup

```bash
cd frontend/Asset-Manager/artifacts/mockup-sandbox

# Install dependencies
pnpm install

# Start dev server (proxies /api/* → http://localhost:8000)
pnpm dev
```

The frontend starts on **http://localhost:3000**.
Navigation: `http://localhost:3000/preview/sentinel/Dashboard`

---

## Environment Variables

Create `.env` at the repository root (alongside `backend/`). All variables are optional except Redis and the simulation path — the system degrades gracefully when keys are missing.

```env
# ── Redis (required) ────────────────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0
# For Upstash TLS: rediss://default:<password>@<host>.upstash.io:6379

# ── PostgreSQL ───────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@host/dbname?ssl=require

# ── Isolation Forest model path ──────────────────────────────────────────────
# Defaults to backend/app/ml/sentinel_if.pkl — leave blank
# IF_MODEL_PATH=

# ── LLM — Anthropic (Claude) ────────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...

# ── LLM — Google (Gemini) ────────────────────────────────────────────────────
GEMINI_API_KEY=AIza...

# ── Twilio (SMS) ─────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_FROM_NUMBER=+1xxxxxxxxxx

# ── Emergency contacts ───────────────────────────────────────────────────────
# Prefix with # to disable a contact without deleting it
EMERGENCY_CONTACT_NUMBERS=+91xxxxxxxxxx,+91xxxxxxxxxx
EMERGENCY_CONTACT_EMAILS=doctor@hospital.com,nurse@hospital.com

# ── Resend (email alerts) ────────────────────────────────────────────────────
RESEND_API_KEY=re_...
RESEND_FROM_EMAIL=SENTINEL <onboarding@resend.dev>

# ── Firebase FCM (push notifications) ───────────────────────────────────────
# FIREBASE_CREDENTIALS_JSON={"type":"service_account","project_id":"..."}

# ── Calendly (appointment booking) ──────────────────────────────────────────
# Personal Access Token from:
# https://calendly.com/integrations/api_webhooks → Personal Access Tokens
CALENDLY_API_TOKEN=eyJraWQ...
# Pin a specific event type (optional — fetched dynamically if blank)
CALENDLY_EVENT_TYPE_URI=

# ── SerpAPI (live Google Maps ratings for Nearby Doctors) ───────────────────
# https://serpapi.com/manage-api-key  (100 free searches/month on free plan)
# Leave blank for OSM-only mode (no ratings, just proximity + specialization)
SERP_API_KEY=

# ── EMS dispatch API ─────────────────────────────────────────────────────────
# Leave blank to use mock dispatch during development
EMS_API_URL=

# ── Simulator ────────────────────────────────────────────────────────────────
CSV_DATA_DIR=D:\Hackanova\data
SIMULATE_INTERVAL=0.5   # seconds between CSV rows (0.5 = 2 readings/sec)
```

---

## API Reference

All REST endpoints are prefixed with `/api/v1/`. The Swagger UI at `/docs` documents every field.

### Vitals

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/vitals/ingest` | Ingest a single `VitalReading` through the full pipeline |
| `GET` | `/api/v1/vitals/latest/{patient_id}` | Latest reading from Redis cache (30 s TTL) |
| `POST` | `/api/v1/fall/{patient_id}/acknowledge` | Acknowledge a detected fall event |
| `WS` | `/ws/vitals/{patient_id}` | WebSocket stream — send JSON readings, receive scored assessments |

### Simulator

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/v1/simulator/start` | Start CSV simulation for a patient |
| `POST` | `/api/v1/simulator/stop` | Stop simulation |
| `GET` | `/api/v1/simulator/status/{patient_id}` | Ticks sent, elapsed time, row index |

### Audit Log

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/audit` | Recent escalation entries (default limit 50) |
| `GET` | `/api/v1/audit/patient/{patient_id}/latest` | Latest entry for a specific patient |

### Settings

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/settings/contacts` | All emergency contacts (env + Redis) |
| `POST` | `/api/v1/settings/contacts/number` | Add a phone number |
| `DELETE` | `/api/v1/settings/contacts/number` | Remove a phone number |
| `POST` | `/api/v1/settings/contacts/email` | Add an email address |
| `DELETE` | `/api/v1/settings/contacts/email` | Remove an email address |
| `POST` | `/api/v1/settings/test-sms` | Send a test SMS via Twilio |
| `POST` | `/api/v1/settings/test-email` | Send a test email via Resend |
| `POST` | `/api/v1/settings/book-appointment` | Create a Calendly scheduling link |
| `GET` | `/api/v1/settings/calendly-event-types` | List available Calendly event types |

### Nearby Doctors

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/v1/doctors/nearby` | Ranked nearby facilities (OSM + optional SerpAPI) |

**Query parameters:**

| Parameter | Default | Description |
|-----------|---------|-------------|
| `patient_id` | `P01` | Resolves location from Redis vitals cache |
| `lat` | — | Override latitude |
| `lng` | — | Override longitude |
| `radius_m` | `5000` | Search radius in metres (500–50000) |
| `syndromes` | — | Comma-separated syndrome keys for specialization scoring |
| `limit` | `10` | Max results (1–25) |

### Health Check

```
GET /health
```

Returns status of Redis, Isolation Forest, Claude API, Gemini API, Twilio, Resend, Calendly, SerpAPI, EMS, and PostgreSQL.

---

## Scoring Pipeline — Five Sub-Layers

The scoring engine produces a single **0–100 normalised score** from five compounding sub-layers, then maps it to a SHAL band.

```
SL1 — Threshold Classification (max 40 pts)
  Heart Rate, SpO₂, Respiratory Rate, Body Temperature, HRV
  Each vital classified: NORMAL / WARNING_LOW / WARNING_HIGH /
                          CRITICAL_LOW / CRITICAL_HIGH
  Weights: RR=4, SpO₂=4, HR=3, HRV=3, Temp=2

SL2 — Contextual Modifiers (additive bonus points)
  + Stress score > 70  → +8 pts
  + HRV acute drop     → +2 pts
  + ECG arrhythmia     → HR weight ×1.5
  + Deep sleep deficit → floor score 8 pts
  + Sedentary context  → HR weight ×1.25
  + Vigorous exercise  → HR weight ×0.5 (reduces false positives)

SL3 — Syndrome Detection (bonus 20–30 pts each)
  SIRS / Sepsis, Hypoxic Episode, Distributive Shock,
  Autonomic Collapse, Respiratory Failure, Multi-System Stress,
  qSOFA (≥2 criteria), ECG ST-elevation / VT patterns

SL4 — Trend Analysis (bonus 6–12 pts each)
  HR sustained ascent, SpO₂ progressive decline,
  HRV collapse, Inverse HR↑ + SpO₂↓, Temp trajectory

SL5 — Isolation Forest Anomaly (bonus 5–15 pts)
  sklearn model trained on normal vital combinations
  Low contamination score → +5 pts
  Medium → +10 pts, High → +15 pts
```

**SHAL Band thresholds:**

| Band | Score Range | Colour |
|------|-------------|--------|
| NOMINAL | 0–29 | Green |
| ELEVATED | 30–49 | Yellow |
| WARNING | 50–69 | Amber |
| HIGH | 70–79 | Orange |
| CRITICAL | 80–100 | Red |

---

## Escalation Engine

The escalation engine is triggered after every pipeline cycle where the SHAL band is ELEVATED or above.

```
Assessment received
│
├─ HARD OVERRIDE checks (run before scoring)
│   ├─ FALL_UNRESPONSIVE detected → Fall Protocol
│   ├─ ECG_STEMI/ECG_VT_VF detected → CRITICAL override
│   └─ SpO₂ < 85% sustained → CRITICAL override
│
└─ SHAL Band routing
    ├─ ELEVATED → SMS alert
    ├─ WARNING  → SMS + email
    ├─ HIGH     → SMS + email + Calendly scheduling link
    └─ CRITICAL → SMS + email + EMS dispatch (3 retries, 0/2/4 s backoff)
                              + PostgreSQL audit entry
```

**Fall Protocol state machine:**

```
NONE ──► POSSIBLE (fall_event detected)
           │
           ▼ 30 s monitoring window
         LIKELY (no motion, zero steps)
           │
           ▼ 60 s countdown
         CONFIRMED ──► EMS dispatch
           │
           └─► ACKNOWLEDGED (if POST /fall/{id}/acknowledge received in time)
```

---

## Frontend Pages

All pages share the `SentinelLayout` sidebar wrapper with live data polling.

### Dashboard
- **Vitals cards**: Heart Rate, SpO₂, Respiratory Rate, Temperature, HRV, Stress Score — polled every 2 s from `/api/v1/vitals/latest/P01`
- **ECG Details**: Rhythm, ST deviation, QTc interval
- **Sleep Metrics**: Efficiency %, Deep sleep %, REM %
- **Activity**: Steps/hr, Activity context
- **Patient Location**: Live GPS coordinates with Google Maps link; demographics overlay
- **SHAL Band indicator**: Animated colour-coded escalation status
- **Recent Escalations**: Last 5 audit entries with score and actions taken
- Vitals fallback chain: `latestVitals` (Redis/CSV) → `vitals_snapshot` (audit log) → animated placeholder

### Audit Trail
- Full paginated history of every escalation decision
- Expandable rows: reasoning chain, differential diagnoses, vitals snapshot, syndromes/trends fired
- Colour-coded SHAL band badges, action outcome chips (EMS/SMS/email/booking)
- Source indicator: `llm:gemini`, `llm:claude`, or `rule_fallback`

### System Health
- Live service status grid: Redis, Isolation Forest, Claude API, Gemini API, Twilio, Resend, Calendly, SerpAPI, EMS, PostgreSQL
- Auto-refreshes every 30 s
- Connection status derived from `/health` endpoint

### Settings
- **Emergency Contacts**: Add/remove phone numbers and emails; persisted in Redis
- **Test SMS**: Send a test message via Twilio; Twilio error codes surfaced directly
- **Test Email**: Send a test HTML report via Resend
- **Book Appointment**: Select Calendly event type from live dropdown, fill patient details, generate scheduling link; link displayed with Open/Copy actions

### Nearby Doctors
- Patient ID + radius selector + syndrome chip filter
- Syndromes auto-populated from the latest audit log entry
- Doctor cards: rank badge, type badge, distance, address, opening hours, rating (⭐), specialization match score bar, Directions / Call / Website buttons
- Sorted by Google rating (when SerpAPI key is set), then by composite score
- OpenStreetMap attribution + map link for patient location

---

## Nearby Doctors

The nearby doctors feature combines two data sources:

**OpenStreetMap Overpass API** (free, no key required)
- Queries `amenity=doctors`, `amenity=clinic`, `amenity=hospital`, `healthcare=doctor`, `amenity=pharmacy`
- Returns name, address, phone, website, opening hours, wheelchair accessibility
- Results cached in Redis for 5 minutes per location+radius combination

**SerpAPI — Google Maps** (optional, requires `SERP_API_KEY`)
- Fetches live Google ratings for the top 12 nearest results in parallel
- Ratings cached in Redis per OSM node ID for 1 hour
- Without a key: ratings show "No rating", facilities sorted by proximity + specialization only

**Scoring formula:**

| Component | Weight | Details |
|-----------|--------|---------|
| Proximity | 40% | Linearly decays to 0 at `radius_m` |
| Rating | 20% | `rating / 5.0 × 20` — requires SerpAPI |
| Specialization match | 30% | Syndrome → specialty mapping; primary match = 30 pts |
| Data completeness | 10% | +2.5 pts each for phone, website, hours, specialization |

**Syndrome → Specialization mapping:**

| Syndrome | Priority Specializations |
|----------|--------------------------|
| SIRS / Sepsis | internal medicine, intensive care, emergency |
| Respiratory Failure | pulmonology, intensive care, emergency |
| ECG STEMI / VT | cardiology, emergency, intensive care |
| Fall Unresponsive | neurology, orthopaedics, emergency, traumatology |
| Hyperpyrexia | infectious diseases, internal medicine, emergency |

---

## ML Model — Isolation Forest

The Isolation Forest model (`backend/app/ml/sentinel_if.pkl`) is trained on a synthetic dataset of normal vital combinations to detect statistical anomalies.

**Input features:**
`heart_rate`, `respiratory_rate`, `spo2`, `body_temperature`, `hrv_ms`, `ecg_st_deviation_mm`, `ecg_qtc_ms`, `stress_score`, `steps_per_hour`, `sleep_efficiency`, `deep_sleep_pct`, `rem_pct`

**Retrain the model:**
```bash
cd backend
python app/ml/train_isolation_forest.py
```

**Anomaly score integration:**
The raw contamination score is bucketed into three tiers and added as bonus points in SL5 of the scoring engine. The model degrades gracefully — if the `.pkl` file is missing, SL5 contributes 0 points and the pipeline continues normally.

---

## Dataset

The synthetic dataset at `data/dataset.csv` contains realistic patient vitals across multiple clinical scenarios — normal baseline, SIRS progression, hypoxic episode, ECG abnormalities, fall events, and hyperpyrexia. It includes GPS coordinates for location-aware features.

**Regenerate the dataset:**
```bash
cd data
python generate_dataset.py
```

---

## Testing

```bash
cd backend

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a specific module
pytest tests/test_scoring_engine.py -v

# Run benchmarks
pytest --benchmark-only

# Windows shortcut
run_tests.bat
```

Test coverage includes:
- Signal processor plausibility validation and threshold classification
- All five scoring sub-layers with edge cases
- Escalation engine action routing per SHAL band
- LLM client fallback chain
- Audit repository write/read round-trips

---

## Team

**The Three Hackeeters** — Hackanova 5.0

- [Parth Chauhan](https://github.com/ParthChauhan1658)
- [Pranav Sonmale](https://github.com/Sonmale25)
- [Nihar Shah](https://github.com/NiharShah10)

---

## License

Built for Hackanova 5.0. All rights reserved by The Three Hackeeters.
