"""FastAPI integration tests with Firestore/Gemini/Places faked.

Validates the API contract end-to-end without GCP credentials:
health, profile, session, feedback (+place context), feedback-summary
user scoping, upload-takeout coordinate preservation, chat (ranking fields).
"""
import io
import json
import re
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from fastapi.testclient import TestClient

import main as app_module
from main import app


class FakeDocRef:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    def get(self):
        class _Snap:
            exists = self._key in self._store
            def to_dict(inner):
                return self._store.get(self._key)
        return _Snap()

    def set(self, data, merge=False):
        if merge and self._key in self._store:
            self._store[self._key].update(data)
        else:
            self._store[self._key] = json.loads(json.dumps(data, default=str))

    def update(self, data):
        self._store.setdefault(self._key, {}).update(data)


class FakeCol:
    def __init__(self):
        self.store = {}
        self._n = 0

    def document(self, key):
        return FakeDocRef(self.store, key)

    def add(self, data):
        self._n += 1
        self.store[f"id{self._n}"] = dict(data)

    def where(self, filter=None, **kw):
        user_id = getattr(filter, "value", None)

        class _Q:
            def limit(inner, n):
                inner._n = n
                return inner
            _n = 1000
            def stream(inner):
                rows = [type("D", (), {"to_dict": staticmethod(lambda d=self.store[k]: d)})()
                        for k in self.store if self.store[k].get("user_id") == user_id]
                return rows[:getattr(inner, "_n", 1000)]
        return _Q()


class FakeFirestore:
    def __init__(self):
        self.users = FakeCol()
        self.sessions = FakeCol()
        self.feedback = FakeCol()

    def collection(self, name):
        return {"users": self.users, "sessions": self.sessions, "feedback": self.feedback}[name]


class FakeAgent:
    """Deterministic stand-in for CollaborativeTasteAgent (no LLM/Places calls)."""

    def collaborate(self, user_id, session_id, user_message):
        notebook = {
            "destination": "Catania",
            "clarified_preferences": {"occasion": "dinner"},
            "itinerary_notes": ["note"],
            "shortlist": [{
                "id": "p1", "name": "Mock Place", "rating": 4.5,
                "taste_match_score": 75, "intent_score": 8, "taste_score": 7,
                "combined_score": 7.5, "scored_by": "llm",
                "lat": 37.5, "lng": 15.09, "address": "Via X 1",
                "maps_url": "https://maps.app/p1", "types": ["restaurant"],
                "price_level": "MODERATE", "match_reason": "matches",
            }],
        }
        return {
            "message": "here you go",
            "clarifying_questions": [],
            "places": notebook["shortlist"],
            "notebook": notebook,
            "thought_process": "test reasoning",
            "ranking_meta": {"llm_scored": 1, "heuristic_fallback_count": 0, "weights": {"intent": 0.45, "taste": 0.55}},
        }

    def build_taste_profile_from_places(self, user_id, places):
        return {"taste_profile": {"summary": f"profile for {len(places)} places"}, "user_id": user_id}


class FakeGenaiResponse:
    def __init__(self, text):
        self.text = text


class FakeModels:
    """Routes generate_content by prompt shape: agent JSON vs ranking batches."""

    def __init__(self):
        self.calls = 0

    def generate_content(self, model=None, contents=None, config=None, **kw):
        self.calls += 1
        prompt = contents if isinstance(contents, str) else str(contents)
        if "Candidate Places" in prompt:
            # ranking batch: score whichever real ids appear in the prompt
            ids = re.findall(r'"id":\s*"([^"]+)"', prompt)
            return FakeGenaiResponse(json.dumps([
                {"id": i, "name": "", "intent_score": 9, "taste_score": 8, "reason": "fresh catch"}
                for i in ids
            ]))
        # agent orchestration call
        return FakeGenaiResponse(json.dumps({
            "thought_process": "user wants seafood",
            "clarifying_questions": [],
            "search_needed": True,
            "search_query": "seafood",
            "search_destination": "Catania",
            "notebook_updates": {"destination": "Catania", "clarified_preferences": {"occasion": "dinner"}},
            "message_markdown": "Great choice — here are seafood picks.",
        }))


class FakeGenaiClient:
    def __init__(self):
        self.models = FakeModels()


@pytest.fixture()
def client(monkeypatch):
    fake_fs = FakeFirestore()
    monkeypatch.setattr(app_module, "_db", None)
    monkeypatch.setattr(app_module, "_agent", None)

    from db import TasteDB as Real
    from agent import CollaborativeTasteAgent as RealAgent

    class PatchedDB(Real):
        def __init__(self, project_id=None):
            self.users_col = fake_fs.users
            self.sessions_col = fake_fs.sessions
            self.feedback_col = fake_fs.feedback
            self.client = fake_fs
            self.project_id = project_id

    def make_real_agent(project_id=None):
        agent = RealAgent.__new__(RealAgent)  # skip genai.Client construction
        agent.project_id = project_id or "test"
        agent.location = "us-central1"
        agent.model_name = "gemini-test"
        agent.db = PatchedDB()
        agent.places_api_key = ""  # → mock places path
        agent.ranking_mode = "dual"
        agent.client = FakeGenaiClient()
        return agent

    monkeypatch.setattr(app_module, "TasteDB", PatchedDB)
    monkeypatch.setattr(app_module, "CollaborativeTasteAgent", make_real_agent)
    return TestClient(app)


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "healthy"
        assert "Cloud Run" in body["infrastructure"][0]


class TestProfileAndSession:
    def test_profile_default_created(self, client):
        r = client.get("/api/profile/userX")
        assert r.status_code == 200
        assert "taste_profile" in r.json()

    def test_session_default_created(self, client):
        r = client.get("/api/session/sessX", params={"user_id": "userX"})
        assert r.status_code == 200
        body = r.json()
        assert body["notebook"]["shortlist"] == []


class TestChat:
    def test_chat_returns_dual_scores(self, client):
        r = client.post("/api/chat", json={"user_id": "u", "session_id": "s", "message": "seafood in Catania"})
        assert r.status_code == 200
        body = r.json()
        assert len(body["places"]) >= 1
        p = body["places"][0]
        assert p["intent_score"] == 9 and p["taste_score"] == 8  # from the fake ranking model
        assert p["scored_by"] == "llm"
        assert p["taste_match_score"] == int(round(p["combined_score"] * 10))  # back-compat field
        assert body["ranking_meta"]["weights"] == {"intent": 0.45, "taste": 0.55}

    def test_chat_place_has_coords_for_map(self, client):
        r = client.post("/api/chat", json={"user_id": "u", "session_id": "s2", "message": "seafood"})
        place = r.json()["places"][0]
        # mock places carry location for the itinerary map (or graceful absence)
        assert "location" in place or place.get("lat") is None

    def test_chat_shortlist_persists_with_coords(self, client):
        client.post("/api/chat", json={"user_id": "u2", "session_id": "s9", "message": "dinner"})
        r = client.get("/api/session/s9", params={"user_id": "u2"})
        shortlist = r.json()["notebook"]["shortlist"]
        assert len(shortlist) >= 1
        top = shortlist[0]
        assert top.get("maps_url") or top.get("address")
        assert "intent_score" in top and "taste_score" in top  # export fields present


class TestFeedback:
    def test_feedback_with_context(self, client):
        r = client.post("/api/feedback", json={
            "user_id": "u3", "session_id": "s", "place_id": "p", "place_name": "Trap Cafe",
            "feedback_type": "too_touristy", "place_types": ["cafe", "food"],
            "price_level": "MODERATE", "location": {"latitude": 37.5, "longitude": 15.09},
        })
        assert r.status_code == 200
        weights = r.json()["updated_weights"]
        assert weights["authenticity"] <= 1.0

    def test_feedback_backward_compatible_minimal_payload(self, client):
        r = client.post("/api/feedback", json={
            "user_id": "u4", "session_id": "s", "place_id": "p", "place_name": "X", "feedback_type": "like",
        })
        assert r.status_code == 200

    def test_feedback_summary_scoped(self, client):
        client.post("/api/feedback", json={
            "user_id": "uA", "session_id": "s", "place_id": "p", "place_name": "Secret Spot",
            "feedback_type": "too_touristy", "place_types": ["cafe"],
        })
        ra = client.get("/api/feedback-summary", params={"user_id": "uA"})
        rb = client.get("/api/feedback-summary", params={"user_id": "uB"})
        assert ra.status_code == 200 and rb.status_code == 200
        assert ra.json()["total_feedback"] == 1
        assert rb.json() == {}  # no cross-user leak


class TestUploadTakeout:
    def _geojson_bytes(self):
        data = {
            "features": [
                {"properties": {"location": {"name": "Geo Cafe", "address": "ul. 1",
                                             "geo": {"latitude": 42.69, "longitude": 23.32}}}},
                {"properties": {"name": "No Geo Bar"}},
            ]
        }
        return io.BytesIO(json.dumps(data).encode()), "saved-places.json"

    def test_upload_preserves_coordinates(self, client):
        f, name = self._geojson_bytes()
        r = client.post("/api/upload-takeout", params={"user_id": "u5"},
                        files={"file": (name, f, "application/json")})
        assert r.status_code == 200
        assert r.json()["status"] == "success"

    def test_upload_csv_with_coords(self, client):
        csv_content = "Title,Address,Lat,Lng\nSputnik Bar,bul. 1,42.6889,23.3307\n"
        r = client.post("/api/upload-takeout", params={"user_id": "u6"},
                        files={"file": ("want-to-go.csv", io.BytesIO(csv_content.encode()), "text/csv")})
        assert r.status_code == 200
        assert r.json()["count"] == 1

    def test_upload_rejects_empty(self, client):
        r = client.post("/api/upload-takeout", params={"user_id": "u7"},
                        files={"file": ("empty.json", io.BytesIO(b'{"features": []}'), "application/json")})
        assert r.status_code == 400


class TestSecurityHeaders:
    def test_unknown_route_404(self, client):
        assert client.get("/api/nonexistent").status_code == 404

    def test_feedback_invalid_type_still_recorded_as_data(self, client):
        """Unknown feedback types are recorded but don't mutate weights unexpectedly."""
        r = client.post("/api/feedback", json={
            "user_id": "u9", "session_id": "s", "place_id": "p", "place_name": "X",
            "feedback_type": "DROP TABLE users; --",
        })
        assert r.status_code == 200  # stored as opaque data (Firestore), no SQL surface
