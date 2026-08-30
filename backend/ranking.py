"""Honest Dual-Score Ranking Engine .

Ranking contract:

- heuristic prefilter with a soft quality gate and an LLM rank cap
- deterministic `heuristic_place_score` used both for shortlisting and as the
  labeled fallback for places the LLM never scored
- dual 0-10 intent/taste scores from Gemini JSON batches (with retries)
- config-driven blend weights (INTENT_WEIGHT / TASTE_WEIGHT)
- the hard rule: failed intent (<= 3) caps taste at 4 in specific mode
- **no fabricated scores**: a place the LLM did not score is labeled
  `scored_by="heuristic"` with a deterministic heuristic estimate — never an
  invented LLM score (the old code assigned a default 85/100 on failure).
"""

import asyncio
import json
import logging
import math
import os
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("gmaps-assistant-ranking")

# --- Configuration (env-overridable) ---
PREFILTER_MIN_RATING = float(os.getenv("PREFILTER_MIN_RATING", "3.5"))
PREFILTER_MIN_REVIEWS = int(os.getenv("PREFILTER_MIN_REVIEWS", "5"))
LLM_RANK_CAP = int(os.getenv("LLM_RANK_CAP", "150"))
INTENT_WEIGHT = float(os.getenv("INTENT_WEIGHT", "0.45"))
TASTE_WEIGHT = float(os.getenv("TASTE_WEIGHT", "0.55"))
RANK_BATCH_SIZE = int(os.getenv("RANK_BATCH_SIZE", "10"))
RANK_BATCH_RETRIES = int(os.getenv("RANK_BATCH_RETRIES", "2"))
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "5"))
HEURISTIC_FALLBACK_REASON = "Heuristic shortlist (not LLM-scored)"

# Simple term -> Google Places type mapping used by the intent matcher
# (subset covering common place types).
_TYPE_MAP: Dict[str, List[str]] = {
    "restaurant": ["restaurant", "meal_takeaway", "meal_delivery", "food"],
    "seafood": ["seafood_restaurant", "restaurant", "food"],
    "cafe": ["cafe", "coffee_shop"],
    "coffee": ["cafe", "coffee_shop"],
    "bakery": ["bakery", "cafe"],
    "bar": ["bar", "wine_bar", "night_club"],
    "wine": ["wine_bar", "bar", "restaurant"],
    "beach": ["beach"],
    "trail": ["park", "tourist_attraction", "hiking_area"],
    "hike": ["park", "hiking_area", "tourist_attraction"],
    "museum": ["museum", "art_gallery", "tourist_attraction"],
    "hotel": ["lodging"],
    "park": ["park", "tourist_attraction"],
}

# Category keywords whose presence in the search term signals a *specific*
# intent (drives the strict cap rule).
_SPECIFIC_CATEGORIES = [
    "restaurant", "seafood", "cafe", "coffee", "bakery", "bar", "wine",
    "beach", "trail", "hike", "hiking", "museum", "hotel", "park",
    "pizzeria", "pizza", "sushi", "ramen", "burger", "brunch", "breakfast",
    "dinner", "lunch", "trattoria", "osteria", "bistro", "brewery", "rooftop",
]

_FISH_PATTERN = re.compile(r"\b(fish|seafood|pesce|pescado)\b", re.IGNORECASE)
_FISH_BLOB_PATTERN = re.compile(r"\b(fish|seafood|pesce|marin|sea|oyster|caught)\b", re.IGNORECASE)


def parse_search_intent(user_intent: str, search_query: str = "") -> Dict[str, Any]:
    """Derive a lightweight intent descriptor from the user's message/query.

    Intent semantics, reduced to what ranking needs: mode ('specific'|'browse'), search term, matched category keyword.
    """
    text = f"{search_query or ''} {user_intent or ''}".strip()
    lowered = text.lower()
    category = None
    for cat in _SPECIFIC_CATEGORIES:
        if re.search(rf"\b{re.escape(cat)}\b", lowered):
            category = cat
            break
    if category:
        return {"mode": "specific", "searchTerm": search_query or user_intent or "", "placeType": category}
    if lowered:
        return {"mode": "browse", "searchTerm": search_query or user_intent or "", "placeType": "any"}
    return {"mode": "browse", "searchTerm": "", "placeType": "any"}


def intent_type_match_score(place: Dict[str, Any], intent: Optional[Dict[str, Any]]) -> float:
    """0..1 heuristic match between a place and the parsed intent.

    Heuristic intent match (type alignment + token hits + seafood special
    case). Returns 1.0 (neutral) in browse mode.
    """
    if not intent or intent.get("mode") == "browse" or not intent.get("searchTerm"):
        return 1.0

    types = [str(t).lower() for t in (place.get("types") or [])]
    blob = " ".join([
        str(place.get("name") or ""),
        str(place.get("summary") or place.get("editorial_summary") or ""),
        str(place.get("address") or ""),
        " ".join(types),
    ]).lower()

    term = str(intent.get("searchTerm") or "").lower()
    tokens = [t for t in re.split(r"\s+", term) if len(t) > 2]
    score = 0.0

    place_type = intent.get("placeType") or "any"
    mapped = _TYPE_MAP.get(str(place_type).lower())
    if mapped:
        if any(t in types for t in mapped) or any(t.split("_")[0] in blob for t in mapped):
            score += 0.45
        else:
            score -= 0.25

    if tokens:
        hits = sum(1 for t in tokens if t in blob)
        score += 0.4 * (hits / len(tokens))

    if _FISH_PATTERN.search(term):
        if _FISH_BLOB_PATTERN.search(blob) or "seafood_restaurant" in types:
            score += 0.35
        if "coffee_shop" in types or "cafe" in types:
            score -= 0.5
        if "bar" in types and not re.search(r"\bwine|cocktail\b", term):
            score -= 0.15

    return max(0.0, min(1.0, score))


def heuristic_place_score(place: Dict[str, Any], intent: Optional[Dict[str, Any]]) -> float:
    """Deterministic 0..1 quality+intent score (port of `heuristicPlaceScore`)."""
    raw_rating = place.get("rating")
    raw_reviews = place.get("review_count")
    try:
        rating = 3.8 if raw_rating is None else float(raw_rating)
    except (TypeError, ValueError):
        rating = 3.8
    try:
        reviews = 20 if raw_reviews is None else int(raw_reviews)
    except (TypeError, ValueError):
        reviews = 20
    rating_n = max(0.0, min(1.0, (rating - 3) / 2))
    reviews_n = max(0.0, min(1.0, math.log10(reviews + 1) / 3))
    intent_n = intent_type_match_score(place, intent)
    return intent_n * 0.55 + rating_n * 0.3 + reviews_n * 0.15


def prefilter_candidates(
    candidates: List[Dict[str, Any]], intent: Optional[Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, int]]:
    """Soft quality gate + heuristic shortlist for LLM ranking.

    Soft quality gate + heuristic shortlist. Returns
    `(for_llm, heuristic_only, stats)`; `for_llm` is capped at LLM_RANK_CAP.
    """
    kept: List[Dict[str, Any]] = []
    soft_dropped = 0

    for c in candidates:
        name = c.get("name") or ""
        if not name or len(name) < 3:
            soft_dropped += 1
            continue
        rating = c.get("rating")
        reviews = c.get("review_count")
        # Soft quality gate: only drop when rating AND reviews both look weak
        if (
            rating is not None
            and float(rating) < PREFILTER_MIN_RATING
            and (reviews is None or int(reviews) < PREFILTER_MIN_REVIEWS * 4)
        ):
            soft_dropped += 1
            continue
        kept.append(c)

    scored = sorted(
        kept,
        key=lambda p: heuristic_place_score(p, intent),
        reverse=True,
    )
    for_llm = scored[:LLM_RANK_CAP]
    heuristic_only = scored[LLM_RANK_CAP:]

    stats = {
        "input": len(candidates),
        "after_quality": len(kept),
        "soft_dropped": soft_dropped,
        "llm_ranked": len(for_llm),
        "heuristic_only": len(heuristic_only),
    }
    return for_llm, heuristic_only, stats


def compact_profile_summary(taste_profile: Dict[str, Any]) -> str:
    """Compact taste-profile JSON sent to the ranking model.

    Avoids dumping the full stored document (weights/ids) — sends only the
    descriptive facets the scorer needs. Falls back to the raw dict keys that
    exist so custom profiles still work.
    """
    keys = [
        "summary", "cuisines", "vibes", "travel_style", "price_preference",
        "avoid", "cuisine_preferences", "vibe_preferences", "drink_preferences",
        "outdoor_interests", "cultural_interests", "design_sensibility",
        "price_range", "key_patterns",
    ]
    compact = {k: taste_profile[k] for k in keys if taste_profile.get(k)}
    return json.dumps(compact, indent=2, default=str)


def _clamp(value: Any, low: float = 0.0, high: float = 10.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    return max(low, min(high, v))


def _batch_prompt(batch: List[Dict[str, Any]], profile_summary: str, intent: Dict[str, Any]) -> Tuple[str, str]:
    """System + user prompt for one ranking batch (port of `rankBatch`)."""
    system = (
        "You score places for a taste-matching engine. Always return dual scores.\n"
        "intent_score 0-10: how well the place matches the user's search intent (dish/type/activity).\n"
        "taste_score 0-10: how well it matches the person's long-term taste profile.\n"
        "If intent is specific and the place does not match intent, intent_score MUST be 0-3."
    )

    if intent.get("mode") == "specific" and intent.get("searchTerm"):
        intent_block = (
            f"\n## User search intent\n- query: \"{intent.get('searchTerm')}\"\n"
            f"- place_type: {intent.get('placeType', 'any')}\nRules:\n"
            "- intent_score 7-10 only if place clearly matches the search intent\n"
            "- intent_score 0-3 if wrong category (e.g. cafe when user asked for seafood)\n"
            "- taste_score independent of intent, but final usefulness needs both"
        )
    else:
        intent_block = (
            "\n## Open browse (no specific dish)\n"
            "- intent_score: set 7-9 for generally recommendable places, lower for tourist traps"
        )

    places_text = "\n".join(
        json.dumps(
            {
                "id": p.get("id"),
                "name": p.get("name"),
                "address": p.get("address"),
                "types": p.get("types", [])[:6],
                "rating": p.get("rating"),
                "reviews": p.get("review_count"),
                "price_level": p.get("price_level"),
                "summary": (p.get("summary") or "")[:140],
            },
            ensure_ascii=False,
        )
        for p in batch
    )

    user = (
        f"## Taste Profile\n{profile_summary}\n{intent_block}\n\n"
        f"## Candidate Places\n{places_text}\n\n"
        "Return JSON array (same names/ids):\n"
        '[{"id":"","name":"","intent_score":0,"taste_score":0,"reason":"short","tags":[]}]\n\n'
        "CRITICAL: ONLY the JSON array. No markdown, no code fences. Start with [ end with ]."
    )
    return system, user


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    """Parse the model output as a JSON array with a braces fallback."""
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [s for s in data if isinstance(s, dict)]
        if isinstance(data, dict):
            # tolerate {"scores": [...]} style wrappers
            for v in data.values():
                if isinstance(v, list):
                    return [s for s in v if isinstance(s, dict)]
        return None
    except json.JSONDecodeError:
        start, end = text.find("["), text.rfind("]")
        if start != -1 and end > start:
            try:
                data = json.loads(text[start:end + 1])
                if isinstance(data, list):
                    return [s for s in data if isinstance(s, dict)]
            except json.JSONDecodeError:
                return None
    return None


async def rank_batch(
    batch: List[Dict[str, Any]],
    profile_summary: str,
    intent: Dict[str, Any],
    llm_call,
) -> List[Dict[str, Any]]:
    """Score one batch with retries; returns [] on total failure (never fabricates).

    `llm_call(system, user, temperature)` must return the raw model text and is
    injected so this module stays testable without real credentials.
    """
    system, user = _batch_prompt(batch, profile_summary, intent)
    last_err: Optional[str] = None
    for attempt in range(RANK_BATCH_RETRIES + 1):
        try:
            response = await llm_call(system, user, 0.15)
            scores = _extract_json_array(response or "")
            if scores:
                # normalize the single `score` field if a model returns it
                for s in scores:
                    if s.get("taste_score") is None and s.get("score") is not None:
                        s["taste_score"] = s["score"]
                    if s.get("intent_score") is None and s.get("score") is not None:
                        s["intent_score"] = s["score"] if intent.get("mode") == "specific" else 8
                return scores
            last_err = "empty/invalid JSON"
            logger.warning("Rank batch attempt %d: bad JSON", attempt + 1)
        except Exception as exc:  # noqa: BLE001 — model errors must not break ranking
            last_err = str(exc)
            logger.warning("Rank batch attempt %d failed: %s", attempt + 1, exc)
        if attempt < RANK_BATCH_RETRIES:
            await asyncio.sleep(0.4 * (attempt + 1))
    logger.warning("Rank batch failed after retries: %s", last_err)
    return []


def merge_one(
    place: Dict[str, Any],
    llm_score: Optional[Dict[str, Any]],
    intent: Dict[str, Any],
    heuristic_fallback: bool,
) -> Dict[str, Any]:
    """Merge a place with its score → dual scores + labeled fallback.

    Merge including the cap rule (specific intent with intent_score <= 3
    caps taste at 4).
    """
    if llm_score is not None and any(
        llm_score.get(k) is not None for k in ("intent_score", "taste_score", "score")
    ):
        intent_score = _clamp(llm_score.get("intent_score", 8 if intent.get("mode") == "browse" else 5))
        taste_score = _clamp(llm_score.get("taste_score", llm_score.get("score", 0)))
        scored_by = "llm"
        reason = llm_score.get("reason") or ""
    elif heuristic_fallback:
        h = heuristic_place_score(place, intent)
        im = intent_type_match_score(place, intent)
        intent_score = round(im * 10, 1)
        base = h * 6 + ((float(place["rating"]) - 3) / 2) * 4 if place.get("rating") is not None else h * 6 + 3
        taste_score = max(0.0, min(10.0, round(float(base), 1)))
        scored_by = "heuristic"
        reason = HEURISTIC_FALLBACK_REASON
    else:
        intent_score, taste_score, scored_by, reason = 0.0, 0.0, "heuristic", HEURISTIC_FALLBACK_REASON

    # Hard rule: failed intent cannot keep a high combined score
    if intent.get("mode") == "specific" and intent.get("searchTerm") and intent_score <= 3:
        taste_score = min(taste_score, 4.0)

    combined = round(intent_score * INTENT_WEIGHT + taste_score * TASTE_WEIGHT, 1)
    out = dict(place)
    out.update({
        "intent_score": intent_score,
        "taste_score": taste_score,
        "combined_score": combined,
        # back-compat: the 0-100 taste_match_score field is kept for older clients
        "taste_match_score": int(round(combined * 10)),
        "scored_by": scored_by,
        "match_reason": reason or HEURISTIC_FALLBACK_REASON if scored_by == "heuristic" else reason,
    })
    return out


async def rank_places(
    places: List[Dict[str, Any]],
    taste_profile: Dict[str, Any],
    user_intent: str,
    search_query: str = "",
    llm_call=None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Full honest ranking pipeline. Returns (ranked_places, metadata).

    `llm_call` is an async callable `(system, user, temperature) -> str`.
    When None (or on total LLM failure) all places are ranked with the
    deterministic heuristic and labeled `scored_by="heuristic"`.
    """
    intent = parse_search_intent(user_intent, search_query)
    for_llm, heuristic_only, stats = prefilter_candidates(places, intent)
    profile_summary = compact_profile_summary(taste_profile)

    all_scores: List[Dict[str, Any]] = []
    llm_error: Optional[str] = None

    if llm_call is not None and for_llm:
        batches = [for_llm[i:i + RANK_BATCH_SIZE] for i in range(0, len(for_llm), RANK_BATCH_SIZE)]
        semaphore = asyncio.Semaphore(max(1, LLM_CONCURRENCY))

        async def run_batch(batch: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            async with semaphore:
                return await rank_batch(batch, profile_summary, intent, llm_call)

        results = await asyncio.gather(*[run_batch(b) for b in batches])
        for scores in results:
            all_scores.extend(scores)

    score_by_id: Dict[str, Dict[str, Any]] = {}
    score_by_name: Dict[str, Dict[str, Any]] = {}
    for s in all_scores:
        if s.get("id"):
            score_by_id[str(s["id"])] = s
        if s.get("name"):
            score_by_name[str(s["name"]).lower()] = s

    ranked_llm: List[Dict[str, Any]] = []
    unscored: List[Dict[str, Any]] = []
    for p in for_llm:
        s = score_by_id.get(str(p.get("id"))) or score_by_name.get(str(p.get("name") or "").lower())
        if s is None:
            unscored.append(p)
            ranked_llm.append(merge_one(p, None, intent, heuristic_fallback=True))
        else:
            ranked_llm.append(merge_one(p, s, intent, heuristic_fallback=False))

    ranked_rest = [merge_one(p, None, intent, heuristic_fallback=True) for p in heuristic_only]

    ranked = sorted(ranked_llm + ranked_rest, key=lambda x: x.get("combined_score", 0), reverse=True)

    meta: Dict[str, Any] = {
        **stats,
        "llm_scored": len(all_scores),
        "heuristic_fallback_count": len(unscored) + len(ranked_rest),
        "weights": {"intent": INTENT_WEIGHT, "taste": TASTE_WEIGHT},
    }
    if llm_call is None:
        llm_error = "no LLM callable configured"
        meta["warning"] = "LLM ranking unavailable — heuristic-only ranking used"
    elif not all_scores and for_llm:
        llm_error = "LLM ranking failed after retries"
        meta["warning"] = "LLM ranking failed after retries — heuristic-only ranking used"
    meta["llm_error"] = llm_error
    return ranked, meta
