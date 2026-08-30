import os
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from google.cloud import firestore

logger = logging.getLogger("gmaps-assistant-db")

# feedback memory loop tuning (env-overridable)
FEEDBACK_SUMMARY_LIMIT = int(os.getenv("FEEDBACK_SUMMARY_LIMIT", "25"))
FEEDBACK_LIKE_STEP = float(os.getenv("FEEDBACK_LIKE_STEP", "0.02"))
FEEDBACK_DISLIKE_STEP = float(os.getenv("FEEDBACK_DISLIKE_STEP", "0.04"))
FEEDBACK_TOURISTY_STEP = float(os.getenv("FEEDBACK_TOURISTY_STEP", "0.08"))
FEEDBACK_WRONG_VIBE_STEP = float(os.getenv("FEEDBACK_WRONG_VIBE_STEP", "0.05"))
WEIGHT_FLOOR = float(os.getenv("WEIGHT_FLOOR", "0.2"))
WEIGHT_CEILING = float(os.getenv("WEIGHT_CEILING", "1.0"))

class TasteDB:
    def __init__(self, project_id: Optional[str] = None):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")
        self.client = firestore.Client(project=self.project_id)
        self.users_col = self.client.collection("users")
        self.sessions_col = self.client.collection("sessions")
        self.feedback_col = self.client.collection("feedback")

    # User / Taste Profile Operations
    def get_user_profile(self, user_id: str) -> Dict[str, Any]:
        doc = self.users_col.document(user_id).get()
        if doc.exists:
            data = doc.to_dict()
            if data is not None:
                return data
        default_profile: Dict[str, Any] = {
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            # F-07: mark fabrication honestly — this profile is a code default,
            # not something learned about the user. The UI shows an empty state
            # until the user actually chats or imports their Takeout.
            "is_default": True,
            "taste_profile": {
                "summary": "Explorer seeking local, authentic experiences with distinct atmosphere and high culinary standards.",
                "cuisines": ["Seafood", "Local / Regional", "Authentic Bistro", "Artisanal Bakery"],
                "vibes": ["Cozy & Intimate", "Scenic Views", "Lively Neighborhood Gem", "Historic Charm"],
                "price_preference": "$$ - Mid-range / Quality focus",
                "avoid": ["Mass tourist traps", "Generic global chains", "Overly noisy nightclubs"],
                "weights": {
                    "authenticity": 0.9,
                    "culinary_quality": 0.85,
                    "scenic_ambiance": 0.8,
                    "value_for_money": 0.75
                }
            },
            "saved_places_count": 0
        }
        self.users_col.document(user_id).set(default_profile)
        return default_profile

    def update_taste_profile(self, user_id: str, taste_profile: Dict[str, Any], saved_places_count: Optional[int] = None) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "taste_profile": taste_profile,
            "updated_at": datetime.utcnow().isoformat()
        }
        if saved_places_count is not None:
            data["saved_places_count"] = saved_places_count
        self.users_col.document(user_id).set(data, merge=True)
        return self.get_user_profile(user_id)

    # Session & Notebook Operations (Collaborative Partner State)
    def get_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        doc = self.sessions_col.document(session_id).get()
        if doc.exists:
            data = doc.to_dict()
            if data is not None:
                return data
        default_session: Dict[str, Any] = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": datetime.utcnow().isoformat(),
            "updated_at": datetime.utcnow().isoformat(),
            "messages": [],
            "notebook": {
                "destination": None,
                "clarified_preferences": {},
                "itinerary_notes": [],
                "shortlist": []
            }
        }
        self.sessions_col.document(session_id).set(default_session)
        return default_session

    def save_session_message(self, session_id: str, message: Dict[str, Any]):
        session_ref = self.sessions_col.document(session_id)
        session_doc = session_ref.get()
        if session_doc.exists:
            doc_data = session_doc.to_dict() or {}
            messages = doc_data.get("messages", [])
            messages.append(message)
            session_ref.update({
                "messages": messages,
                "updated_at": datetime.utcnow().isoformat()
            })
        else:
            session_ref.set({
                "session_id": session_id,
                "messages": [message],
                "notebook": {
                    "destination": None,
                    "clarified_preferences": {},
                    "itinerary_notes": [],
                    "shortlist": []
                },
                "updated_at": datetime.utcnow().isoformat()
            })

    def update_notebook(self, session_id: str, notebook_data: Dict[str, Any]):
        session_ref = self.sessions_col.document(session_id)
        session_ref.set({
            "notebook": notebook_data,
            "updated_at": datetime.utcnow().isoformat()
        }, merge=True)

    # Collaborative Feedback Loop
    def record_feedback(
        self,
        user_id: str,
        session_id: str,
        place_id: str,
        place_name: str,
        feedback_type: str,
        comment: Optional[str] = None,
        place_types: Optional[List[str]] = None,
        price_level: Optional[str] = None,
        location: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Records feedback (with place context), updates the feedback collection,
        and mutates the user's taste profile bidirectionally with clamps.

        feedback_type: 'like', 'dislike', 'too_touristy', 'wrong_vibe', 'saved_to_itinerary'
        Place context (place_types / price_level / location) is optional —
        callers without it keep working with the default weight behavior.
        """
        feedback_entry = {
            "user_id": user_id,
            "session_id": session_id,
            "place_id": place_id,
            "place_name": place_name,
            "feedback_type": feedback_type,
            "comment": comment,
            "timestamp": datetime.utcnow().isoformat()
        }
        # store place context so feedback can generalize across places
        if place_types:
            feedback_entry["place_types"] = list(place_types)[:10]
        if price_level:
            feedback_entry["price_level"] = price_level
        if location:
            feedback_entry["location"] = location

        self.feedback_col.add(feedback_entry)

        weights_changed = self._mutate_weights(user_id, feedback_type, place_types)
        return {"status": "success", "updated_weights": weights_changed}

    def _mutate_weights(self, user_id: str, feedback_type: str, place_types: Optional[List[str]] = None) -> Dict[str, float]:
        """Deterministic bidirectional weight mutation with clamps .

        Positives nudge the relevant weight up (ceiling 1.0); negatives nudge
        it down (floor 0.2). Weights are code-mutated — the LLM only narrates.
        """
        user_profile = self.get_user_profile(user_id)
        tp = user_profile.get("taste_profile", {})
        weights = tp.get("weights", {"authenticity": 0.8, "culinary_quality": 0.8, "scenic_ambiance": 0.7, "value_for_money": 0.7})

        def clamp(key: str, delta: float) -> float:
            current = float(weights.get(key, 0.75))
            updated = round(max(WEIGHT_FLOOR, min(WEIGHT_CEILING, current + delta)), 2)
            weights[key] = updated
            return updated

        if feedback_type in ("like", "saved_to_itinerary"):
            clamp("authenticity", +FEEDBACK_LIKE_STEP)
            clamp("culinary_quality", +FEEDBACK_LIKE_STEP)
        elif feedback_type == "dislike":
            clamp("culinary_quality", -FEEDBACK_DISLIKE_STEP)
        elif feedback_type == "too_touristy":
            clamp("authenticity", -FEEDBACK_TOURISTY_STEP)
            avoids = set(tp.get("avoid", []))
            avoids.add("Crowded tourist hubs")
            tp["avoid"] = list(avoids)
        elif feedback_type == "wrong_vibe":
            clamp("scenic_ambiance", -FEEDBACK_WRONG_VIBE_STEP)

        tp["weights"] = weights
        self.update_taste_profile(user_id, tp)
        return weights

    def get_feedback_summary(self, user_id: str, limit: Optional[int] = None) -> Dict[str, Any]:
        """Aggregate the user's recent feedback into prompt-ready patterns .

        Strictly user-scoped: the query filters on user_id, so no cross-user
        data can leak into the agent prompt. Returns counts by feedback type,
        category-level patterns (types of places flagged/loved), and recent
        avoid signals.
        """
        max_entries = limit or FEEDBACK_SUMMARY_LIMIT
        try:
            docs = (
                self.feedback_col
                .where(filter=firestore.FieldFilter("user_id", "==", user_id))
                .limit(max_entries)
                .stream()
            )
            entries = [d.to_dict() or {} for d in docs]
        except Exception as exc:  # noqa: BLE001 — feedback memory must never break chat
            logger.warning("Feedback summary read failed: %s", exc)
            entries = []

        if not entries:
            return {}

        type_counts: Dict[str, int] = {}
        category_counts: Dict[str, int] = {}
        avoid_phrases: List[str] = []
        like_phrases: List[str] = []

        for e in entries:
            ftype = e.get("feedback_type") or "unknown"
            type_counts[ftype] = type_counts.get(ftype, 0) + 1
            for t in (e.get("place_types") or [])[:3]:
                if t in ("point_of_interest", "establishment", "food"):
                    continue  # too generic to be a useful pattern
                category_counts[t] = category_counts.get(t, 0) + 1

            if ftype in ("too_touristy", "dislike"):
                phrase = " ".join(filter(None, [e.get("place_name"), "flagged as", ftype.replace("_", " ")]))
                if phrase not in avoid_phrases:
                    avoid_phrases.append(phrase)
            elif ftype in ("like", "saved_to_itinerary"):
                phrase = " ".join(filter(None, [e.get("place_name"), "was loved"]))
                if phrase not in like_phrases:
                    like_phrases.append(phrase)

        top_categories = sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        return {
            "total_feedback": len(entries),
            "type_counts": type_counts,
            "top_categories": [{"type": t, "count": c} for t, c in top_categories],
            "avoid_examples": avoid_phrases[:5],
            "like_examples": like_phrases[:5],
        }

    def build_feedback_block(self, user_id: str, limit: Optional[int] = None) -> str:
        """Deterministic 'learned preferences' text block for the agent prompt.

        Empty string when there is no feedback yet (the block is omitted —
        the prompt never contains an empty section).
        """
        summary = self.get_feedback_summary(user_id, limit)
        if not summary:
            return ""

        lines = ["LEARNED FROM YOUR FEEDBACK (deterministic aggregation of past signals):"]
        tc = summary.get("type_counts", {})
        parts = []
        if tc.get("too_touristy"):
            parts.append(f"flagged {tc['too_touristy']} place(s) as too touristy")
        if tc.get("dislike"):
            parts.append(f"disliked {tc['dislike']} place(s)")
        if tc.get("wrong_vibe"):
            parts.append(f"flagged {tc['wrong_vibe']} vibe mismatch(es)")
        if tc.get("like") or tc.get("saved_to_itinerary"):
            loved = tc.get("like", 0) + tc.get("saved_to_itinerary", 0)
            parts.append(f"loved/saved {loved} place(s)")
        if parts:
            lines.append("- History: user has " + "; ".join(parts) + ".")

        cats = summary.get("top_categories") or []
        if cats:
            lines.append("- Place types involved: " + ", ".join(f"{c['type']} ({c['count']})" for c in cats) + ".")

        if summary.get("avoid_examples"):
            lines.append("- Recent negative signals: " + "; ".join(summary["avoid_examples"]) + ".")
        if summary.get("like_examples"):
            lines.append("- Recent positive signals: " + "; ".join(summary["like_examples"]) + ".")

        lines.append("Use this to avoid repeating disliked patterns and to seek more of what was loved. Adapt retrieval and phrasing accordingly.")
        return "\n".join(lines)
