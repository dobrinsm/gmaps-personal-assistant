"""Minimal mock backend for browser-level e2e validation of the remediation
batch. Serves the real frontend plus scripted /api responses — no GCP, no
network. Used ONLY by tests/browser_e2e_remediation.py.
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = FastAPI()
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

SESSION_STATE = {
    "session_id": "sess_mock",
    "user_id": "user_mock",
    # Pre-seeded history so F-03 replay can be verified without a live chat
    # round-trip (mirrors the shape agent.py writes: role/content/places).
    "messages": [
        {"role": "user", "content": "Fresh seafood in Catania", "timestamp": "t1"},
        {"role": "assistant", "content": "Great choice — here are **two** mock matches. Probe: <img src=x onerror=window.__xss=1>",
         "clarifying_questions": ["Is this for a special occasion, or more of a casual, authentic local experience?"],
         "recommended_places": [
             {"id": "ChIJmock1", "name": "Ciurma Catania", "rating": 4.8, "review_count": 2437,
              "intent_score": 9, "taste_score": 9, "combined_score": 9.0, "scored_by": "llm",
              "lat": 37.5091595, "lng": 15.0868184, "address": "Via Gemmellaro, 42, Catania",
              "maps_url": "https://maps.google.com/?cid=1183098378246967159",
              "types": ["seafood_restaurant", "restaurant"], "price_level": "PRICE_LEVEL_MODERATE",
              "match_reason": "Excellent seafood match."},
         ], "timestamp": "t2"},
    ],
    "notebook": {
        "destination": "Catania, Sicily",
        "clarified_preferences": {"fancy_level": "nothing fancy", "occasion_vibe": "casual authentic local"},
        "itinerary_notes": ["Mock note"],
        "shortlist": [
            {"id": "ChIJmock1", "name": "Ciurma Catania", "rating": 4.8, "review_count": 2437,
             "intent_score": 9, "taste_score": 9, "combined_score": 9.0, "scored_by": "llm",
             "lat": 37.5091595, "lng": 15.0868184, "address": "Via Gemmellaro, 42, Catania",
             "maps_url": "https://maps.google.com/?cid=1183098378246967159",
             "types": ["seafood_restaurant", "restaurant"], "price_level": "PRICE_LEVEL_MODERATE",
             "match_reason": "Excellent seafood match."},
            {"id": "ChIJmock2", "name": "Café <img src=x onerror=window.__xss=1>", "rating": 4.2,
             "review_count": 12, "intent_score": 7, "taste_score": 6, "combined_score": 6.5,
             "scored_by": "heuristic", "lat": 37.5050, "lng": 15.0840,
             "address": "Via Test 1, Catania", "maps_url": "",
             "types": ["cafe"], "price_level": "PRICE_LEVEL_INEXPENSIVE",
             "match_reason": "Heuristic match for cafes."},
        ],
    },
}
DEFAULT_PROFILE = {
    "user_id": "user_mock", "is_default": True,
    "taste_profile": {"summary": "Explorer seeking local, authentic experiences",
                      "vibes": ["Cozy & Intimate"], "cuisines": ["Seafood"],
                      "avoid": ["Tourist traps"],
                      "weights": {"authenticity": 0.9, "culinary_quality": 0.85,
                                  "scenic_ambiance": 0.8, "value_for_money": 0.75}},
    "saved_places_count": 0,
}

FEEDBACK_CALLS = []


@app.get("/api/health")
def health():
    return {"status": "healthy", "project": "mock", "model": "mock-model"}


@app.get("/api/profile/{user_id}")
def profile(user_id: str):
    return dict(DEFAULT_PROFILE)


@app.get("/api/session/{session_id}")
def session(session_id: str, user_id: str = "user_default"):
    return dict(SESSION_STATE)


@app.post("/api/chat")
async def chat(req: dict):
    reply = {
        "message": "Here are **three** spots. Probe: <img src=x onerror=window.__xss=1>",
        "clarifying_questions": ["Is this for a special occasion, or more of a casual, authentic local experience?"],
        "places": SESSION_STATE["notebook"]["shortlist"],
        "notebook": SESSION_STATE["notebook"],
        "thought_process": "",
    }
    SESSION_STATE["messages"].append({"role": "user", "content": req.get("message", ""), "timestamp": "t"})
    SESSION_STATE["messages"].append({**{"role": "assistant", "content": reply["message"],
                                         "clarifying_questions": reply["clarifying_questions"],
                                         "recommended_places": reply["places"], "timestamp": "t"}})
    return reply


@app.post("/api/feedback")
async def feedback(req: dict):
    FEEDBACK_CALLS.append(req)
    return {"status": "success", "updated_weights": {"authenticity": 0.92}}


@app.get("/api/feedback-summary")
def feedback_summary(user_id: str = "user_default", session_id: str = "session_default"):
    return {"avoid_patterns": ["Cafe <img src=x onerror=window.__xss=1> flagged as too touristy"],
            "like_patterns": ["Ciurma Catania was loved"]}


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
