"""Contract tests for the Feedback Memory Loop .

Uses a fake Firestore to validate: bidirectional weight mutation with clamps,
feedback summary aggregation, user scoping, and prompt-block injection.
No GCP credentials required.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
import db as db_module
from db import TasteDB


class FakeDoc:
    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class FakeStream:
    def __init__(self, docs):
        self._docs = docs

    def __iter__(self):
        return iter(self._docs)


class FakeFeedbackQuery:
    def __init__(self, store, user_id, limit):
        self._store = store
        self._user_id = user_id
        self._limit = limit

    def where(self, **kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def stream(self):
        rows = [FakeDoc(dict(v, _id=k)) for k, v in self._store.items() if v.get("user_id") == self._user_id]
        return FakeStream(rows[: self._limit])


class FakeCollection:
    def __init__(self, store=None):
        self.store = store if store is not None else {}
        self._counter = 0

    def add(self, data):
        self._counter += 1
        self.store[f"auto_{self._counter}"] = dict(data)
        return None, None

    def where(self, filter=None, **kwargs):
        # capture user_id from the FieldFilter
        user_id = getattr(filter, "value", kwargs.get("user_id"))
        return FakeFeedbackQuery(self.store, user_id, 1000)


class FakeUsersDoc:
    def __init__(self, store, key):
        self._store = store
        self._key = key

    @property
    def exists(self):
        return self._key in self._store

    def get(self):
        return self

    def to_dict(self):
        return self._store.get(self._key)

    def set(self, data, merge=False):
        if merge and self._key in self._store:
            self._store[self._key].update(data)
        else:
            self._store[self._key] = dict(data)

    def update(self, data):
        self._store.setdefault(self._key, {}).update(data)


class FakeUsersCol(FakeCollection):
    def document(self, key):
        return FakeUsersDoc(self.store, key)


class FakeClient:
    def __init__(self):
        self.users_col = FakeUsersCol()
        self.feedback_col = FakeCollection()


def make_db(with_default_profile=True) -> TasteDB:
    database = TasteDB.__new__(TasteDB)
    fake = FakeClient()
    database.client = fake
    database.users_col = fake.users_col
    database.sessions_col = FakeCollection()
    database.feedback_col = fake.feedback_col
    database.project_id = "test-project"
    if with_default_profile:
        database.users_col.document("u1").set({
            "taste_profile": {
                "summary": "test",
                "avoid": [],
                "weights": {"authenticity": 0.8, "culinary_quality": 0.8, "scenic_ambiance": 0.7, "value_for_money": 0.7},
            }
        })
    return database


FEEDBACK_BASE = dict(user_id="u1", session_id="s1", place_id="p1", place_name="Osteria Test")


class TestWeightMutation:
    def test_like_increases_authenticity(self):
        database = make_db()
        res = database.record_feedback(**FEEDBACK_BASE, feedback_type="like")
        assert res["updated_weights"]["authenticity"] == pytest.approx(0.82, abs=1e-9)
        assert res["updated_weights"]["culinary_quality"] == pytest.approx(0.82, abs=1e-9)

    def test_too_touristy_decreases_authenticity_and_adds_avoid(self):
        """The mirror: was +0.08 increase-only, now decreases with the avoid entry kept."""
        database = make_db()
        res = database.record_feedback(**FEEDBACK_BASE, feedback_type="too_touristy")
        assert res["updated_weights"]["authenticity"] == pytest.approx(0.72, abs=1e-9)
        profile = database.get_user_profile("u1")
        assert "Crowded tourist hubs" in profile["taste_profile"]["avoid"]

    def test_dislike_decreases_culinary(self):
        database = make_db()
        res = database.record_feedback(**FEEDBACK_BASE, feedback_type="dislike")
        assert res["updated_weights"]["culinary_quality"] == pytest.approx(0.76, abs=1e-9)

    def test_wrong_vibe_decreases_ambiance(self):
        database = make_db()
        res = database.record_feedback(**FEEDBACK_BASE, feedback_type="wrong_vibe")
        assert res["updated_weights"]["scenic_ambiance"] == pytest.approx(0.65, abs=1e-9)

    def test_floor_clamp(self):
        database = make_db()
        database.users_col.document("u1").set({
            "taste_profile": {"weights": {"authenticity": 0.21, "culinary_quality": 0.8,
                                          "scenic_ambiance": 0.7, "value_for_money": 0.7}, "avoid": []}
        })
        database.record_feedback(**FEEDBACK_BASE, feedback_type="too_touristy")
        w = database.get_user_profile("u1")["taste_profile"]["weights"]
        assert w["authenticity"] == 0.2  # floored, never below
        assert w["authenticity"] >= db_module.WEIGHT_FLOOR

    def test_ceiling_clamp(self):
        database = make_db()
        database.users_col.document("u1").set({
            "taste_profile": {"weights": {"authenticity": 0.99, "culinary_quality": 0.99,
                                          "scenic_ambiance": 0.7, "value_for_money": 0.7}, "avoid": []}
        })
        database.record_feedback(**FEEDBACK_BASE, feedback_type="like")
        w = database.get_user_profile("u1")["taste_profile"]["weights"]
        assert w["authenticity"] == 1.0
        assert w["culinary_quality"] == 1.0

    def test_minimal_payload_without_context_still_works(self):
        database = make_db()
        res = database.record_feedback(user_id="u1", session_id="s1", place_id="p", place_name="X", feedback_type="like")
        assert res["status"] == "success"


class TestFeedbackStorage:
    def test_place_context_stored(self):
        database = make_db()
        database.record_feedback(**FEEDBACK_BASE, feedback_type="like",
                                 place_types=["seafood_restaurant", "food"],
                                 price_level="MODERATE", location={"latitude": 1.0, "longitude": 2.0})
        entry = next(iter(database.feedback_col.store.values()))
        assert entry["place_types"] == ["seafood_restaurant", "food"]
        assert entry["price_level"] == "MODERATE"
        assert entry["location"] == {"latitude": 1.0, "longitude": 2.0}

    def test_types_capped_at_ten(self):
        database = make_db()
        database.record_feedback(**FEEDBACK_BASE, feedback_type="like", place_types=[f"t{i}" for i in range(20)])
        entry = next(iter(database.feedback_col.store.values()))
        assert len(entry["place_types"]) == 10


class TestSummary:
    def test_empty_when_no_feedback(self):
        database = make_db()
        assert database.get_feedback_summary("u1") == {}
        assert database.build_feedback_block("u1") == ""

    def test_aggregation_counts(self):
        database = make_db()
        for i in range(3):
            database.record_feedback(user_id="u1", session_id="s", place_id=f"p{i}",
                                     place_name=f"Touristy Place {i}", feedback_type="too_touristy",
                                     place_types=["restaurant", "tourist_attraction"])
        database.record_feedback(user_id="u1", session_id="s", place_id="pl",
                                 place_name="Loved Osteria", feedback_type="like",
                                 place_types=["seafood_restaurant"])
        summary = database.get_feedback_summary("u1")
        assert summary["total_feedback"] == 4
        assert summary["type_counts"]["too_touristy"] == 3
        assert summary["type_counts"]["like"] == 1
        types = {c["type"] for c in summary["top_categories"]}
        assert "restaurant" in types and "seafood_restaurant" in types

    def test_user_scoping_no_cross_user_leak(self):
        """Hardening requirement: user B's summary must never contain user A's feedback."""
        database = make_db()
        database.record_feedback(user_id="userA", session_id="s", place_id="p", place_name="A SECRET PLACE", feedback_type="too_touristy")
        # B sees nothing of A's
        assert database.get_feedback_summary("userB") == {}
        assert database.build_feedback_block("userB") == ""
        assert "A SECRET PLACE" not in database.build_feedback_block("userB")
        # A still sees their own (scoping works both ways)
        assert "A SECRET PLACE" in database.build_feedback_block("userA")

    def test_generic_types_filtered(self):
        database = make_db()
        database.record_feedback(user_id="u1", session_id="s", place_id="p", place_name="X",
                                 feedback_type="like", place_types=["point_of_interest", "food", "establishment"])
        summary = database.get_feedback_summary("u1")
        assert summary["top_categories"] == []

    def test_summary_never_raises_on_bad_entries(self):
        database = make_db()
        database.feedback_col.store["bad1"] = {"user_id": "u1"}  # no feedback_type
        summary = database.get_feedback_summary("u1")
        assert summary["total_feedback"] == 1
        assert summary["type_counts"]["unknown"] == 1


class TestPromptBlock:
    def test_block_contains_learned_patterns(self):
        database = make_db()
        database.record_feedback(user_id="u1", session_id="s", place_id="p", place_name="Trap Cafe",
                                 feedback_type="too_touristy", place_types=["cafe"])
        block = database.build_feedback_block("u1")
        assert "LEARNED FROM YOUR FEEDBACK" in block
        assert "too touristy" in block
        assert "cafe" in block
        assert "Trap Cafe" in block

    def test_block_omitted_when_empty(self):
        database = make_db()
        assert database.build_feedback_block("u1") == ""


class TestReadFailureResilience:
    def test_firestore_failure_degrades_to_empty(self):
        class BrokenCol:
            def where(self, **kw):
                raise RuntimeError("firestore unavailable")

        database = make_db(with_default_profile=False)
        database.feedback_col = BrokenCol()
        assert database.get_feedback_summary("u1") == {}
        assert database.build_feedback_block("u1") == ""
