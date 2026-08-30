# GMaps Personal Assistant — Collaborative Partner Agent

**Submission for the *All Things Agentic Hackathon* (Collaborative Partner Track)**

[![Google GenAI SDK](https://img.shields.io/badge/Google%20GenAI%20SDK-Gemini%20on%20Vertex%20AI-4285F4)](https://cloud.google.com/vertex-ai)
[![Google Cloud Run](https://img.shields.io/badge/Google%20Cloud-Cloud%20Run-34A853)](https://cloud.google.com/run)
[![Google Cloud Firestore](https://img.shields.io/badge/Database-Cloud%20Firestore-EA4335)](https://cloud.google.com/firestore)
[![Places API New](https://img.shields.io/badge/Google%20Maps-Places%20API%20(New)-FBBC05)](https://developers.google.com/maps/documentation/places/web-service)

---

## 🎯 Track: Collaborative Partner
> **Track Goal**: *Build an agent that leads the way and takes notes. It should ask clarifying questions, guide the user step-by-step, and have a clear way to capture feedback, so it constantly adapts to the user's unique way of thinking.*

GMaps Personal Assistant turns travel planning into a collaborative co-discovery journey that **remembers, proves, and delivers**:

1. **Leads the Way Step-by-Step** — proactively guides the conversation from destination → vibe/occasion → curated spots, asking focused clarifying questions along the way.
2. **Takes Notes (Agent Notebook)** — autonomously maintains confirmed preferences, itinerary notes, and a shortlist in a live structured notebook.
3. **Remembers** — your Google Takeout saved places build a taste profile; every 👍 / 🚩 / 🎭 feedback is stored with place context and read back into the agent's memory on the next turn, adapting taste weights bidirectionally (clamped 0.2–1.0).
4. **Proves** — every recommendation carries honest dual scores **`Intent 8 · Taste 7 → 7.5`**. Places the model never scored are visibly labeled *"heuristic shortlist"* — scores are never fabricated.
5. **Delivers** — the shortlist becomes an itinerary: a Leaflet map plus one-click **Google Maps directions** (≤10 stops), **KML**, and **CSV** export.

---

## 🏗️ System Architecture

```
                                  ┌────────────────────────────────┐
                                  │   User / Web Client (SPA)      │
                                  └───────────────┬────────────────┘
                                                  │
                                                  ▼
                               ┌─────────────────────────────────────┐
                               │  Google Cloud Run: FastAPI Agent    │
                               │  agent.py  — collaborate loop       │
                               │  ranking.py — honest dual scoring   │
                               │  db.py     — Firestore + memory     │
                               └──────┬───────────────────┬──────────┘
                                      │                   │
                ┌─────────────────────┴──────┐   ┌────────┴─────────────────────┐
                ▼                            ▼   ▼                              ▼
   ┌───────────────────────────┐ ┌──────────────────────────┐ ┌───────────────────────────────┐
   │ Gemini on Vertex AI       │ │ Google Places API (New)  │ │ Google Cloud Firestore Native │
   │ • Proactive guidance      │ │ • Live text search       │ │ • Taste profiles              │
   │ • Clarifying questions    │ │ • Ratings & coordinates  │ │ • Sessions & agent notebooks  │
   │ • Dual intent×taste       │ │ • Maps URLs              │ │ • Feedback memory (queried)   │
   │   batch scoring           │ │                          │ │ • Itinerary shortlists        │
   └───────────────────────────┘ └──────────────────────────┘ └───────────────────────────────┘
```

## 🚀 Hackathon Mandatory Requirements Checklist

- [x] **Gemini (Flash / Pro)** accessed via **Vertex AI** & the **Google GenAI SDK** (`google-genai`).
- [x] **Google Agent Framework**: structured JSON outputs, multi-turn reasoning, proactive clarification triggers, real-time state adaptation.
- [x] **Google Cloud Infrastructure**:
  - **Cloud Run** — serverless containerized backend.
  - **Cloud Firestore** — taste vectors, session state, feedback memory, agent notebooks.
  - **Vertex AI** — enterprise model execution.
  - **Places API (New)** — live venue & geo search.

---

## ⚡ Quick Start

### Prerequisites
- Python 3.11+
- A Google Cloud project with **Firestore** and **Vertex AI** enabled, and a service account key with `roles/datastore.user` + Vertex AI User
- A **Places API (New)** key

```bash
git clone https://github.com/dobrinsm/gmaps-personal-assistant.git
cd gmaps-personal-assistant

python3 -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

cp .env.example backend/.env
# edit backend/.env with your project, credentials path, model, and Places key
```

```bash
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open **http://localhost:8000**. Without a Places key the agent serves two labeled demo places so the UI stays explorable.

## 🧪 Tests

```bash
python -m pytest tests/ -q           # 68 contract & integration tests (no GCP creds needed)
node tests/test_frontend_exports.js  # 27 export/map smoke checks
ruff check backend/ tests/           # lint
```

Tests fake Firestore/GenAI/Places — nothing external is required. CI runs the same commands on every push.

## ⚙️ Configuration

All knobs and defaults are documented in [`.env.example`](.env.example): model, Places key, ranking weights (`INTENT_WEIGHT` / `TASTE_WEIGHT`), the `RANKING_MODE=dual|legacy` rollback flag, and feedback-loop steps/clamps. Config is env-only — the Dockerfile strips `backend/.env` from images.

## ☁️ Deploying to Google Cloud Run

Docker → Artifact Registry → Cloud Run v2 API:

```bash
export REGION=europe-west1
export PROJECT=your-gcp-project-id
export REGISTRY=$REGION-docker.pkg.dev/$PROJECT/gmaps-assistant

docker build -t "$REGISTRY/app:v1" .
docker push "$REGISTRY/app:v1"

# Patch the Cloud Run v2 service with the image + env vars (never a baked .env),
# then grant roles/run.invoker to allUsers if you want a public demo.
```

The runtime service account needs Cloud Run Invoker/Admin, Artifact Registry write, `roles/datastore.user`, and Vertex AI User. If runtime Firestore/Vertex calls fail, check those IAM roles first.

---

## 💡 Key Accomplishments
- **True agentic collaboration**: multi-turn dialogue, clarifying questions, and a live notebook instead of a static search box.
- **Honest dual-score ranking**: intent × taste with a heuristic prefilter, batch retries, and labeled fallback — no fabricated scores, ever.
- **Closing the feedback loop**: feedback with place context is aggregated and injected into the agent's memory; weights adapt bidirectionally with clamps.
- **From conversation to itinerary**: map + Google Maps / KML / CSV export generated entirely client-side.

## 📄 License
MIT License — see [LICENSE](LICENSE).
