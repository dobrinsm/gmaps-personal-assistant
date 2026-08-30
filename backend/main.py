import os
import io
import csv
import json
import zipfile
import logging
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv

from db import TasteDB
from agent import CollaborativeTasteAgent

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gmaps-assistant-api")

app = FastAPI(
    title="GMaps Personal Assistant - Collaborative Partner Agent",
    description="Autonomous travel discovery agent that guides step-by-step, keeps an agent notebook, and learns your unique taste profile.",
    version="2.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "your-gcp-project-id")

# TasteDB / CollaborativeTasteAgent require GCP credentials at construction time.
# They are initialized lazily so the module can be imported (and unit-tested)
# without Application Default Credentials; first API request materializes them.
_db: Optional[TasteDB] = None
_agent: Optional[CollaborativeTasteAgent] = None


def get_db() -> TasteDB:
    global _db
    if _db is None:
        _db = TasteDB(project_id=PROJECT_ID)
    return _db


def get_agent() -> CollaborativeTasteAgent:
    global _agent
    if _agent is None:
        _agent = CollaborativeTasteAgent(project_id=PROJECT_ID)
    return _agent


# --- A1: canonical place extraction (preserve coordinates end-to-end) ---
def _extract_geojson_features(features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract places from Takeout GeoJSON 'features', preserving coordinates.

    Google Takeout Saved/GeoJSON places store location either under
    properties.location ({name, address, geo?}) or as a geometry Point. Both
    shapes are handled; coordinates are kept when present so the itinerary
    map/export layer  can use them.
    """
    places: List[Dict[str, Any]] = []
    for f in features or []:
        props = f.get("properties", {}) or {}
        loc = props.get("location", {}) or {}
        lat: Optional[float] = None
        lng: Optional[float] = None

        # Shape 1: properties.location.geo = {latitude, longitude}
        geo = loc.get("geo") or props.get("geo") or {}
        if isinstance(geo, dict):
            lat = geo.get("latitude")
            lng = geo.get("longitude")
        # Shape 2: geometry = {coordinates: [lng, lat]} (GeoJSON Point)
        geometry = f.get("geometry") or {}
        if (lat is None or lng is None) and isinstance(geometry, dict):
            coords = geometry.get("coordinates") or []
            if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                try:
                    lng = float(coords[0])
                    lat = float(coords[1])
                except (TypeError, ValueError):
                    lat = lng = None

        place: Dict[str, Any] = {
            "name": loc.get("name") or props.get("Title") or props.get("name") or "Place",
            "address": loc.get("address") or props.get("Address") or "",
            "comment": props.get("Comment") or props.get("note") or "",
        }
        if lat is not None and lng is not None:
            place["lat"] = lat
            place["lng"] = lng
        places.append(place)
    return places


def _parse_csv_rows(csv_text: str) -> List[Dict[str, Any]]:
    """Parse a Takeout 'Want to go'/saved-places CSV preserving coordinates.

    Takeout CSV exports (and this app's own CSV export) may carry Lat/Lng or
    Latitude/Longitude columns; keep them when present.
    """
    places: List[Dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(csv_text))
    for row in reader:
        title = row.get("Title") or row.get("name") or row.get("Name")
        if not title:
            continue
        place: Dict[str, Any] = {
            "name": title,
            "address": row.get("Address") or row.get("Note") or "",
            "comment": row.get("Comment") or row.get("Tags") or "",
        }
        lat = row.get("Lat") or row.get("Latitude") or row.get("lat")
        lng = row.get("Lng") or row.get("Longitude") or row.get("lng")
        try:
            if lat not in (None, "") and lng not in (None, ""):
                place["lat"] = float(lat)
                place["lng"] = float(lng)
        except (TypeError, ValueError):
            pass
        places.append(place)
    return places

# Pydantic Request Models
class ChatRequest(BaseModel):
    user_id: str = "user_default"
    session_id: str = "session_default"
    message: str

class FeedbackRequest(BaseModel):
    user_id: str = "user_default"
    session_id: str = "session_default"
    place_id: str
    place_name: str
    feedback_type: str  # 'like', 'dislike', 'too_touristy', 'wrong_vibe', 'saved_to_itinerary'
    comment: Optional[str] = None
    # optional place context so feedback can generalize across places
    place_types: Optional[List[str]] = None
    price_level: Optional[str] = None
    location: Optional[Dict[str, Any]] = None

class ProfileUpdateRequest(BaseModel):
    user_id: str = "user_default"
    taste_profile: Dict[str, Any]

# API Endpoints
@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "project": PROJECT_ID,
        "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        "framework": "Google GenAI SDK (google-genai) with Vertex AI",
        "infrastructure": ["Google Cloud Run", "Google Cloud Firestore Native"],
        "track": "Collaborative Partner"
    }

@app.get("/api/profile/{user_id}")
def get_profile(user_id: str):
    return get_db().get_user_profile(user_id)

@app.post("/api/profile/update")
def update_profile(req: ProfileUpdateRequest):
    return get_db().update_taste_profile(req.user_id, req.taste_profile)

@app.get("/api/session/{session_id}")
def get_session(session_id: str, user_id: str = "user_default"):
    return get_db().get_session(session_id, user_id)

@app.post("/api/chat")
def chat(req: ChatRequest):
    try:
        response = get_agent().collaborate(
            user_id=req.user_id,
            session_id=req.session_id,
            user_message=req.message
        )
        return response
    except Exception as e:
        logger.error(f"Chat error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/feedback")
def feedback(req: FeedbackRequest):
    try:
        res = get_db().record_feedback(
            user_id=req.user_id,
            session_id=req.session_id,
            place_id=req.place_id,
            place_name=req.place_name,
            feedback_type=req.feedback_type,
            comment=req.comment,
            place_types=req.place_types,
            price_level=req.price_level,
            location=req.location
        )
        return res
    except Exception as e:
        logger.error(f"Feedback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/feedback-summary")
def feedback_summary(user_id: str = "user_default", session_id: str = "session_default"):
    """deterministic feedback patterns for the user (strictly user-scoped)."""
    try:
        return get_db().get_feedback_summary(user_id)
    except Exception as e:
        logger.error(f"Feedback summary error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/upload-takeout")
async def upload_takeout(user_id: str = "user_default", file: UploadFile = File(...)):
    try:
        content = await file.read()
        places = []
        filename = (file.filename or "").lower()

        if filename.endswith(".zip"):
            # Handle direct Google Takeout ZIP archive
            with zipfile.ZipFile(io.BytesIO(content), "r") as z:
                for entry_name in z.namelist():
                    # 1. GeoJSON format: Takeout/Maps (your places)/Saved Places.json
                    if entry_name.endswith(".json") and ("saved places" in entry_name.lower() or "places" in entry_name.lower()):
                        try:
                            raw_json = json.loads(z.read(entry_name).decode("utf-8"))
                            if isinstance(raw_json, dict) and "features" in raw_json:
                                places.extend(_extract_geojson_features(raw_json["features"]))
                        except Exception as je:
                            logger.warning(f"Error parsing JSON in zip entry {entry_name}: {je}")

                    # 2. CSV format: Takeout/Saved/Want to go.csv or Saved Places.csv
                    elif entry_name.endswith(".csv") and ("want to go" in entry_name.lower() or "saved" in entry_name.lower() or "starred" in entry_name.lower() or "places" in entry_name.lower()):
                        try:
                            csv_text = z.read(entry_name).decode("utf-8", errors="ignore")
                            places.extend(_parse_csv_rows(csv_text))
                        except Exception as ce:
                            logger.warning(f"Error parsing CSV in zip entry {entry_name}: {ce}")

        elif filename.endswith(".csv"):
            places.extend(_parse_csv_rows(content.decode("utf-8", errors="ignore")))

        else:
            # Handle plain JSON / GeoJSON
            data = json.loads(content.decode("utf-8"))
            if isinstance(data, list):
                places = data
            elif isinstance(data, dict):
                if "features" in data:
                    places.extend(_extract_geojson_features(data["features"]))
                elif "saved_places" in data:
                    places = data["saved_places"]
                else:
                    places = [data]

        if not places:
            # Fallback: try to scan any text/json/csv in the zip
            if filename.endswith(".zip"):
                with zipfile.ZipFile(io.BytesIO(content), "r") as z:
                    for name in z.namelist():
                        if name.endswith(".json"):
                            try:
                                d = json.loads(z.read(name).decode("utf-8", errors="ignore"))
                                if isinstance(d, dict) and "features" in d:
                                    places.extend(_extract_geojson_features(d["features"]))
                            except Exception:
                                pass
            if not places:
                raise HTTPException(status_code=400, detail="No saved places found in the uploaded file.")

        logger.info(f"Extracted {len(places)} places from takeout file ({filename}) for user {user_id}")
        profile = get_agent().build_taste_profile_from_places(user_id, places)
        return {"status": "success", "count": len(places), "profile": profile}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=400, detail=f"Failed to process takeout export: {str(e)}")

# Runtime config endpoint + frontend static files
frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")


@app.get("/config.js", include_in_schema=False)
async def config_js():
    """Serve runtime config: the Maps JS key comes from the environment, never the image."""
    key = os.getenv("GMAPS_API_KEY", "")
    parts = [
        'window.GMAPS_API_KEY = "%s";' % key,
        'window.__gmReady = function () { window.__googleMapsLoaded = true; };',
    ]
    if key:
        # Inject the async Maps JS loader only when a key is configured.
        parts.append(
            '(function(){var s=document.createElement("script");'
            's.async=true;'
            's.src="https://maps.googleapis.com/maps/api/js?key=' + key + '&loading=async&callback=window.__gmReady&v=weekly";'
            'document.head.appendChild(s);})();'
        )
    return Response(content="\n".join(parts), media_type="application/javascript")


if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
