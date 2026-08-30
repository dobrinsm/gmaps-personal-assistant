import os
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
import requests
from google import genai
from google.genai import types

from db import TasteDB
from ranking import rank_places

logger = logging.getLogger("gmaps-assistant-agent")

class CollaborativeTasteAgent:
    def __init__(self, project_id: Optional[str] = None, location: str = "us-central1"):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")
        self.location = location
        self.client = genai.Client(vertexai=True, project=self.project_id, location=self.location)
        # Support Gemini 3.5+ (gemini-3.5-flash / gemini-2.5-flash fallback configurable via env)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.db = TasteDB(project_id=self.project_id)
        self.places_api_key = os.getenv("GOOGLE_PLACES_API_KEY", "")
        # honest dual-score ranking by default; RANKING_MODE="legacy" restores
        # the simpler single-shot 0-100 ranking (rollback flag).
        self.ranking_mode = os.getenv("RANKING_MODE", "dual")

    # 1. Profile Synthesis from Google Takeout Export
    def build_taste_profile_from_places(self, user_id: str, places_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Processes saved / starred places from Google Takeout to extract multi-dimensional taste profile.
        """
        # Truncate / sample if large
        sample_places = places_data[:150]
        places_summary = []
        for p in sample_places:
            title = p.get("title") or p.get("name") or "Unknown"
            address = p.get("address") or p.get("formatted_address") or ""
            note = p.get("comment") or p.get("note") or ""
            places_summary.append(f"- {title} ({address}) {note}")

        places_text = "\n".join(places_summary)

        prompt = f"""You are an elite Travel & Culinary Profiling Agent.
Analyze the following list of places saved/starred by a user from their Google Maps:

{places_text}

Synthesize a comprehensive, nuanced 'Taste Profile' JSON with exact keys:
1. "summary": A 2-sentence description of their travel & culinary personality.
2. "cuisines": Top 5 preferred cuisine styles / food categories.
3. "vibes": Top 5 preferred ambiance & atmosphere traits (e.g. cozy neighborhood gem, historic terrace, minimalist third-wave coffee).
4. "price_preference": Typical price range and spending tendency ($ to $$$$).
5. "travel_style": E.g., slow explorer, culinary purist, off-the-beaten-path wanderer.
6. "avoid": 3-4 types of places they dislike (e.g. tourist traps, generic chains).
7. "weights": JSON object with scores 0.0-1.0 for:
   - "authenticity"
   - "culinary_quality"
   - "scenic_ambiance"
   - "value_for_money"

Return ONLY valid JSON matching this structure.
"""
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.2
            )
        )
        try:
            profile_json = json.loads(response.text or "{}")
        except Exception as e:
            logger.error(f"Failed to parse profile JSON: {e}")
            profile_json = {
                "summary": "Culinary explorer favoring authentic local spots and atmospheric neighborhood gems.",
                "cuisines": ["Local Regional", "Seafood", "Artisanal Bakeries"],
                "vibes": ["Cozy & Intimate", "Historic Charm", "Scenic"],
                "price_preference": "$$",
                "avoid": ["Mass tourist traps", "Global chains"],
                "weights": {"authenticity": 0.9, "culinary_quality": 0.85, "scenic_ambiance": 0.8, "value_for_money": 0.75}
            }

        return self.db.update_taste_profile(user_id, profile_json, saved_places_count=len(places_data))

    # 2. Live Google Places Search
    def search_google_places(self, query: str, destination: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Uses Google Places API (New) Text Search.
        """
        if not self.places_api_key:
            logger.warning("No GOOGLE_PLACES_API_KEY found, returning mock places")
            return self._mock_places(query, destination or "Destination")

        # Explicitly enforce destination in search query string
        if destination and destination.lower() not in query.lower():
            search_text = f"{query} in {destination}"
        else:
            search_text = query

        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.places_api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.priceLevel,places.editorialSummary,places.types,places.googleMapsUri,places.location"
        }
        body = {"textQuery": search_text, "maxResultCount": 10}

        try:
            resp = requests.post(url, headers=headers, json=body, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                results = []
                for p in data.get("places", []):
                    results.append({
                        "id": p.get("id"),
                        "name": p.get("displayName", {}).get("text", "Unknown"),
                        "address": p.get("formattedAddress", ""),
                        "rating": p.get("rating"),
                        "review_count": p.get("userRatingCount"),
                        "price_level": p.get("priceLevel"),
                        "summary": p.get("editorialSummary", {}).get("text", ""),
                        "types": p.get("types", []),
                        "maps_url": p.get("googleMapsUri", f"https://www.google.com/maps/search/?api=1&query={p.get('displayName', {}).get('text', '')}"),
                        "location": p.get("location")
                    })
                return results
            else:
                logger.error(f"Places API error: {resp.status_code} {resp.text}")
                return self._mock_places(query, destination or "Destination")
        except Exception as e:
            logger.error(f"Places API exception: {e}")
            return self._mock_places(query, destination or "Destination")

    def _mock_places(self, query: str, destination: str) -> List[Dict[str, Any]]:
        return [
            {
                "id": "mock_place_1",
                "name": f"Osteria da nonna ({destination})",
                "address": f"Via Roma 14, {destination}",
                "rating": 4.8,
                "review_count": 520,
                "price_level": "PRICE_LEVEL_MODERATE",
                "summary": "Authentic regional trattoria serving fresh local catch and handmade pasta in a rustic setting.",
                "types": ["restaurant", "food", "point_of_interest"],
                "maps_url": f"https://www.google.com/maps/search/?api=1&query=Osteria+{destination}"
            },
            {
                "id": "mock_place_2",
                "name": "Caffè del Porto & Vini",
                "address": f"Piazza Marina 3, {destination}",
                "rating": 4.7,
                "review_count": 310,
                "price_level": "PRICE_LEVEL_INEXPENSIVE",
                "summary": "Cozy seaside bar known for artisan espresso in the morning and natural wines with local aperitivo at dusk.",
                "types": ["bar", "cafe", "food"],
                "maps_url": f"https://www.google.com/maps/search/?api=1&query=Bar+{destination}"
            }
        ]

    # 3. Collaborative Step-by-Step Discovery & Notebook Management
    def collaborate(self, user_id: str, session_id: str, user_message: str) -> Dict[str, Any]:
        """
        Collaborative Partner logic:
        1. Retrieves user taste profile + session history + notebook.
        2. Gemini 2.5 Flash acts as a proactive partner:
           - Leads the discovery step-by-step
           - Asks clarifying questions (vibes, budget, occasion)
           - Searches Places API when intent is clear
           - Matches & ranks places against Taste Profile
           - Automatically updates the 'Agent Notebook' with decisions/itinerary notes.
        """
        user_profile_doc = self.db.get_user_profile(user_id)
        taste_profile = user_profile_doc.get("taste_profile", {})
        session = self.db.get_session(session_id, user_id)
        messages = session.get("messages", [])
        notebook = session.get("notebook", {
            "destination": None,
            "clarified_preferences": {},
            "itinerary_notes": [],
            "shortlist": []
        })

        # close the feedback memory loop — the agent finally reads back
        # its own memory. Empty when no feedback exists (block omitted).
        feedback_block = self.db.build_feedback_block(user_id)

        system_instruction = f"""You are 'Taste Partner', an autonomous AI Travel & Culinary Discovery Agent built for the Collaborative Partner track.
Your mission is to be a proactive co-pilot for trip discovery:
1. Lead the conversation and guide the user step-by-step (destination -> vibe/occasion -> specific recommendations -> curated notebook).
2. Ask 1-2 focused, clarifying questions when requirements are ambiguous or could be narrowed down for better personalization.
3. Keep and update an organized 'Agent Notebook' (itinerary notes, confirmed preferences, key highlights).
4. Respect and leverage the user's learned Taste Profile.

USER'S TASTE PROFILE:
{json.dumps(taste_profile, indent=2)}

{feedback_block}
CURRENT AGENT NOTEBOOK:
{json.dumps(notebook, indent=2)}

Decide if you need to search Google Places now.
You MUST output your response in JSON format with the following schema:
{{
  "thought_process": "Short internal reasoning about user intent, taste alignment, and next steps.",
  "clarifying_questions": ["Question 1", "Question 2"] (empty list if no clarification is needed),
  "search_needed": true/false,
  "search_query": "search terms for Google Places if search_needed is true",
  "search_destination": "city/region for Google Places if known",
  "notebook_updates": {{
    "destination": "detected destination or null",
    "clarified_preferences": {{"key": "value"}},
    "new_itinerary_notes": ["Note or recommendation added to notebook"]
  }},
  "message_markdown": "The friendly, proactive markdown response to the user. Guide them, present options clearly, highlight why spots match their unique taste."
}}
"""

        # Construct conversation prompt
        chat_history_str = ""
        for m in messages[-6:]:
            role = m.get("role", "user")
            content = m.get("content", "")
            chat_history_str += f"{role.upper()}: {content}\n"

        full_prompt = f"{chat_history_str}USER: {user_message}\n\nProvide the JSON response:"

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=[
                types.Content(role="user", parts=[types.Part.from_text(text=system_instruction + "\n\n" + full_prompt)])
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.4
            )
        )

        try:
            agent_output = json.loads(response.text or "{}")
        except Exception as e:
            logger.error(f"Failed to parse agent JSON output: {e}")
            agent_output = {
                "thought_process": "General conversational response",
                "clarifying_questions": [],
                "search_needed": False,
                "notebook_updates": {},
                "message_markdown": response.text or "I am here to help you discover places matching your unique taste profile!"
            }

        # Handle Places Search & Taste Matching
        recommended_places = []
        ranking_meta: Dict[str, Any] = {}
        if agent_output.get("search_needed"):
            query = agent_output.get("search_query") or user_message
            dest = agent_output.get("search_destination") or notebook.get("destination")

            # Strict destination scoping: ensure queries always append the active city/destination context
            if dest and dest.lower() not in query.lower():
                query = f"{query} in {dest}"

            raw_places = self.search_google_places(query, dest)

            # Rank & Score Places against Taste Profile
            if raw_places:
                if self.ranking_mode == "legacy":
                    # Rollback path: single-shot ranking
                    recommended_places = self._rank_and_explain_places_legacy(raw_places, taste_profile, user_message, destination=dest)
                    ranking_meta = {"mode": "legacy"}
                else:
                    recommended_places, ranking_meta = self._rank_and_explain_places(
                        raw_places, taste_profile, user_message, destination=dest, search_query=query
                    )

        # Update Notebook State in Firestore
        nb_updates = agent_output.get("notebook_updates", {})
        if nb_updates.get("destination"):
            notebook["destination"] = nb_updates["destination"]
        if nb_updates.get("clarified_preferences"):
            notebook.setdefault("clarified_preferences", {}).update(nb_updates["clarified_preferences"])
        if nb_updates.get("new_itinerary_notes"):
            notebook.setdefault("itinerary_notes", []).extend(nb_updates["new_itinerary_notes"])
        if recommended_places:
            for rp in recommended_places[:3]:
                if rp["name"] not in [p.get("name") for p in notebook.setdefault("shortlist", [])]:
                    loc = rp.get("location") or {}
                    notebook["shortlist"].append({
                        "id": rp.get("id"),
                        "name": rp.get("name"),
                        "rating": rp.get("rating"),
                        "taste_match_score": rp.get("taste_match_score"),
                        # dual scores + coordinates so the itinerary map/export works
                        "intent_score": rp.get("intent_score"),
                        "taste_score": rp.get("taste_score"),
                        "combined_score": rp.get("combined_score"),
                        "scored_by": rp.get("scored_by"),
                        "lat": loc.get("latitude"),
                        "lng": loc.get("longitude"),
                        "address": rp.get("address", ""),
                        "maps_url": rp.get("maps_url", ""),
                        "types": rp.get("types", []),
                        "price_level": rp.get("price_level"),
                        "match_reason": rp.get("match_reason")
                    })

        self.db.update_notebook(session_id, notebook)

        # Record messages in Firestore
        self.db.save_session_message(session_id, {"role": "user", "content": user_message, "timestamp": datetime.utcnow().isoformat()})
        assistant_record = {
            "role": "assistant",
            "content": agent_output.get("message_markdown", ""),
            "clarifying_questions": agent_output.get("clarifying_questions", []),
            "recommended_places": recommended_places,
            "timestamp": datetime.utcnow().isoformat()
        }
        self.db.save_session_message(session_id, assistant_record)

        # surface honest-ranking telemetry (heuristic fallback counts etc.)
        # in thought_process so the honesty is visible, never hidden.
        thought = agent_output.get("thought_process", "")
        if ranking_meta and ranking_meta.get("warning"):
            thought = f"{thought}\n\n[RANKING] {ranking_meta['warning']}".strip()

        return {
            "message": agent_output.get("message_markdown", ""),
            "clarifying_questions": agent_output.get("clarifying_questions", []),
            "places": recommended_places,
            "notebook": notebook,
            "thought_process": thought,
            "ranking_meta": ranking_meta,
        }

    def _rank_and_explain_places(self, places: List[Dict[str, Any]], taste_profile: Dict[str, Any], user_intent: str, destination: Optional[str] = None, search_query: str = "") -> tuple:
        """Honest dual-score ranking .

        Delegates to `ranking.rank_places` — the dual-score contract:
        heuristic prefilter → Gemini dual 0–10 intent/taste batches with
        retries → merge with labeled heuristic fallback. **No fabricated
        scores**: places the model never scored carry deterministic heuristic
        estimates labeled `scored_by="heuristic"`.

        Returns `(ranked_places, ranking_meta)` so honesty telemetry reaches
        the response; callers that only need places can index [0].
        """
        async def _llm(system: str, user: str, temperature: float) -> str:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    temperature=temperature,
                ),
            )
            return response.text or ""

        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # Called from an async context (not the case in this FastAPI app)
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    ranked, meta = pool.submit(
                        asyncio.run, rank_places(places, taste_profile, user_intent, search_query, _llm)
                    ).result()
            else:
                ranked, meta = loop.run_until_complete(
                    rank_places(places, taste_profile, user_intent, search_query, _llm)
                )
        except RuntimeError:
            ranked, meta = asyncio.run(
                rank_places(places, taste_profile, user_intent, search_query, _llm)
            )

        if meta.get("warning"):
            logger.warning("Ranking fallback active: %s", meta["warning"])
        return ranked, meta

    def _rank_and_explain_places_legacy(self, places: List[Dict[str, Any]], taste_profile: Dict[str, Any], user_intent: str, destination: Optional[str] = None) -> List[Dict[str, Any]]:
        """Single-shot 0-100 ranking (kept for RANKING_MODE=legacy rollback).

        Known defect preserved deliberately: on LLM failure or missing id this
        fabricates a default score of 85 — do not use unless rolling back.
        """
        dest_filter_note = f"The active destination is {destination}. All recommended places MUST be physically located in {destination}." if destination else ""

        scoring_prompt = f"""You are a Taste & Intent Scoring Engine.
Given the user's Taste Profile:
{json.dumps(taste_profile, indent=2)}

User Intent: "{user_intent}"
{dest_filter_note}

Places Candidate List:
{json.dumps(places, indent=2)}

Score each place from 0 to 100 for:
1. Intent Match (does it satisfy what they asked for)
2. Taste Match (does it match their preferred vibes, culinary quality, and avoidance of tourist traps)
3. Overall Match Score = (0.5 * Intent Match) + (0.5 * Taste Match)
4. A 1-sentence personalized 'match_reason' explaining why it suits their taste.

Return a JSON list of objects with keys:
"id": place id,
"taste_match_score": integer 0-100,
"match_reason": "why this matches their taste"
"""
        try:
            res = self.client.models.generate_content(
                model=self.model_name,
                contents=scoring_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            scores = json.loads(res.text or "[]")
            score_map = {s.get("id"): s for s in scores}
            for p in places:
                sc = score_map.get(p.get("id"), {})
                p["taste_match_score"] = sc.get("taste_match_score", 85)
                p["match_reason"] = sc.get("match_reason", "Strong alignment with your preference for authentic local experiences.")
            places.sort(key=lambda x: x.get("taste_match_score", 0), reverse=True)
            return places
        except Exception as e:
            logger.error(f"Ranking error: {e}")
            for p in places:
                p["taste_match_score"] = 85
                p["match_reason"] = "Matches your local authenticity preferences."
            return places
