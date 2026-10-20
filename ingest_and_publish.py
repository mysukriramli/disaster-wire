#!/usr/bin/env python3
"""
Autonomous Global Disaster Intelligence Wire for AI Agents
Queries authoritative feeds + dynamic news RSS, filters noise via LLM,
and writes structured outputs.
"""

import os
import sys
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import requests
import feedparser
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DisasterWire")

# Paths
DATA_DIR = "data"
SEEN_IDS_FILE = os.path.join(DATA_DIR, "seen_ids.txt")
TODAY_JSON_FILE = os.path.join(DATA_DIR, "today.json")
GEOJSON_FILE = os.path.join(DATA_DIR, "events.geojson")
LLMS_TXT_FILE = os.path.join(DATA_DIR, "llms.txt")

# Ensure storage directory exists
os.makedirs(DATA_DIR, exist_ok=True)


# --- Pydantic Data Structures ---

class EventMetrics(BaseModel):
    magnitude: Optional[float] = None
    depth_km: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    alert_score: Optional[float] = None

class EventLocation(BaseModel):
    country: str
    region_admin1: Optional[str] = None
    place_name: str
    latitude: float
    longitude: float

class EventImpact(BaseModel):
    reported_fatalities: Optional[int] = None
    reported_displaced: Optional[int] = None
    infrastructure_damage: Optional[str] = None

class EventSource(BaseModel):
    source_name: str
    url: str
    retrieved_at: str

class DisasterEvent(BaseModel):
    event_id: str
    event_type: str = Field(description="Must be one of: earthquake, tsunami, flood, cyclone, wildfire, volcanic_eruption, severe_weather")
    severity_level: str = Field(description="Must be one of: minor, moderate, severe, catastrophic")
    title: str
    summary: str
    metrics: EventMetrics = Field(default_factory=EventMetrics)
    location: EventLocation
    impact: EventImpact = Field(default_factory=EventImpact)
    timestamp_utc: str
    sources: List[EventSource]


# --- State Management ---

def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen_ids(seen_ids: set):
    # Keep up to 5,000 most recent records to prevent unbounded growth
    truncated_ids = list(seen_ids)[-5000:]
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        for item in truncated_ids:
            f.write(f"{item}\n")


# --- Ingestion: Authoritative Feeds ---

def fetch_usgs_earthquakes(seen_ids: set) -> List[DisasterEvent]:
    """Ingests M4.5+ earthquakes from the USGS 24h GeoJSON feed."""
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"
    events = []
    try:
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        
        for feature in data.get("features", []):
            usgs_id = feature["id"]
            event_id = f"usgs_{usgs_id}"
            if event_id in seen_ids:
                continue

            props = feature["properties"]
            coords = feature["geometry"]["coordinates"] # [lon, lat, depth]
            mag = float(props["mag"]) if props.get("mag") is not None else 0.0

            # Determine severity
            if mag >= 7.0:
                severity = "catastrophic"
            elif mag >= 6.0:
                severity = "severe"
            elif mag >= 5.0:
                severity = "moderate"
            else:
                severity = "minor"

            event_time = datetime.fromtimestamp(props["time"] / 1000, tz=timezone.utc).isoformat()
            now_iso = datetime.now(timezone.utc).isoformat()

            # Extract broad country/place
            place = props.get("place", "Unknown location")
            country = place.split(",")[-1].strip() if "," in place else place

            event = DisasterEvent(
                event_id=event_id,
                event_type="earthquake",
                severity_level=severity,
                title=props.get("title", f"M {mag} Earthquake"),
                summary=f"A magnitude {mag} earthquake occurred at a depth of {coords[2]} km: {place}.",
                metrics=EventMetrics(
                    magnitude=mag,
                    depth_km=float(coords[2]),
                    alert_score=min(10.0, mag * 1.2)
                ),
                location=EventLocation(
                    country=country,
                    region_admin1=None,
                    place_name=place,
                    latitude=float(coords[1]),
                    longitude=float(coords[0])
                ),
                timestamp_utc=event_time,
                sources=[
                    EventSource(
                        source_name="USGS Earthquake Hazards Program",
                        url=props.get("url", url),
                        retrieved_at=now_iso
                    )
                ]
            )
            events.append(event)
            seen_ids.add(event_id)
        logger.info(f"Fetched {len(events)} new events from USGS.")
    except Exception as e:
        logger.error(f"USGS fetch failed: {e}")
    return events


def fetch_gdacs_alerts(seen_ids: set) -> List[DisasterEvent]:
    """Ingests multi-hazard alerts from the GDACS 24h RSS feed."""
    url = "https://www.gdacs.org/xml/rss.xml"
    events = []
    try:
        feed = feedparser.parse(url)
        now_iso = datetime.now(timezone.utc).isoformat()

        for entry in feed.entries:
            link = getattr(entry, "link", "")
            title = getattr(entry, "title", "")
            raw_hash = hashlib.sha256(f"{link}_{title}".encode()).hexdigest()[:16]
            event_id = f"gdacs_{raw_hash}"

            if event_id in seen_ids:
                continue

            # GDACS exposes georss_point
            geo_point = getattr(entry, "georss_point", None)
            lat, lon = 0.0, 0.0
            if geo_point:
                parts = geo_point.strip().split()
                if len(parts) == 2:
                    lat, lon = float(parts[0]), float(parts[1])

            # Classify event type
            title_lower = title.lower()
            event_type = "severe_weather"
            if "earthquake" in title_lower:
                event_type = "earthquake"
            elif "cyclone" in title_lower or "typhoon" in title_lower or "hurricane" in title_lower:
                event_type = "cyclone"
            elif "flood" in title_lower:
                event_type = "flood"
            elif "volcano" in title_lower:
                event_type = "volcanic_eruption"
            elif "tsunami" in title_lower:
                event_type = "tsunami"

            # Alert level
            severity = "moderate"
            if "red" in title_lower or "high" in title_lower:
                severity = "catastrophic"
            elif "orange" in title_lower:
                severity = "severe"

            event = DisasterEvent(
                event_id=event_id,
                event_type=event_type,
                severity_level=severity,
                title=title,
                summary=getattr(entry, "description", title),
                metrics=EventMetrics(),
                location=EventLocation(
                    country="Global",
                    place_name=title,
                    latitude=lat,
                    longitude=lon
                ),
                timestamp_utc=now_iso,
                sources=[
                    EventSource(
                        source_name="GDACS",
                        url=link,
                        retrieved_at=now_iso
                    )
                ]
            )
            events.append(event)
            seen_ids.add(event_id)
        logger.info(f"Fetched {len(events)} new events from GDACS.")
    except Exception as e:
        logger.error(f"GDACS fetch failed: {e}")
    return events


# --- Dynamic News RSS Ingestion + LLM Extraction Layer ---

def fetch_google_news_rss() -> List[Dict[str, str]]:
    """Fetches high-signal headlines from dynamic Google News queries."""
    query = '(earthquake OR tsunami OR "flash flood" OR "tropical cyclone" OR "volcanic eruption") when:1d'
    encoded_query = requests.utils.quote(query)
    feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    
    articles = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:25]:  # Take the top 25 recent candidate stories
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "published": getattr(entry, "published", "")
            })
    except Exception as e:
        logger.error(f"Google News RSS fetch failed: {e}")
    return articles


def parse_unstructured_news_via_llm(articles: List[Dict[str, str]], seen_ids: set) -> List[DisasterEvent]:
    """
    Submits raw headlines to an LLM to:
    1. Filter metaphorical usages ('political earthquake', 'flood of tech layoffs').
    2. Extract strict structured JSON with coordinates and metrics.
    """
    api_key = os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        logger.warning("LLM_API_KEY is not set. Skipping unstructured RSS processing.")
        return []

    # Filter out already seen article URLs
    unseen_articles = []
    for art in articles:
        art_hash = hashlib.sha256(art["link"].encode()).hexdigest()[:16]
        if f"news_{art_hash}" not in seen_ids:
            unseen_articles.append(art)

    if not unseen_articles:
        logger.info("No new unseen news headlines to process.")
        return []

    system_prompt = (
        "You are an automated disaster triage agent. Analyze the provided news articles and extract REAL, PHYSICAL "
        "natural disasters (earthquakes, tsunamis, floods, cyclones, volcanic eruptions, wildfires, extreme storms). "
        "Strict Negative Filtering: Filter out metaphorical news ('market earthquake', 'flood of litigation'). "
        "For each valid disaster, output a JSON array of objects conforming to the requested schema. "
        "Estimate approximate latitude and longitude coordinates based on the named location. "
        "If an article is metaphorical, irrelevant, or lacks location specifics, omit it entirely."
    )

    user_prompt = "Process the following news items:\n" + json.dumps(unseen_articles, indent=2)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_name,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt + " Output format: {\"events\": [ ... ]}"},
            {"role": "user", "content": user_prompt}
        ]
    }

    parsed_events = []
    try:
        res = requests.post(f"{api_base}/chat/completions", headers=headers, json=payload, timeout=45)
        res.raise_for_status()
        data = res.json()
        raw_content = data["choices"][0]["message"]["content"]
        extracted_data = json.loads(raw_content)

        now_iso = datetime.now(timezone.utc).isoformat()
        for item in extracted_data.get("events", []):
            try:
                # Deterministic hash of location and title to prevent duplicate news stories
                title = item.get("title", "")
                loc = item.get("location", {})
                lat = float(loc.get("latitude", 0.0))
                lon = float(loc.get("longitude", 0.0))
                
                event_hash = hashlib.sha256(f"{title}_{lat:.2f}_{lon:.2f}".encode()).hexdigest()[:16]
                event_id = f"news_{event_hash}"

                if event_id in seen_ids:
                    continue

                event = DisasterEvent(
                    event_id=event_id,
                    event_type=item.get("event_type", "severe_weather"),
                    severity_level=item.get("severity_level", "moderate"),
                    title=title,
                    summary=item.get("summary", ""),
                    metrics=EventMetrics(
                        magnitude=item.get("metrics", {}).get("magnitude"),
                        wind_speed_kmh=item.get("metrics", {}).get("wind_speed_kmh"),
                        alert_score=item.get("metrics", {}).get("alert_score")
                    ),
                    location=EventLocation(
                        country=loc.get("country", "Unknown"),
                        region_admin1=loc.get("region_admin1"),
                        place_name=loc.get("place_name", "Unknown"),
                        latitude=lat,
                        longitude=lon
                    ),
                    impact=EventImpact(
                        reported_fatalities=item.get("impact", {}).get("reported_fatalities"),
                        reported_displaced=item.get("impact", {}).get("reported_displaced"),
                        infrastructure_damage=item.get("impact", {}).get("infrastructure_damage")
                    ),
                    timestamp_utc=item.get("timestamp_utc", now_iso),
                    sources=[
                        EventSource(
                            source_name="News RSS",
                            url=item.get("source_url", "https://news.google.com"),
                            retrieved_at=now_iso
                        )
                    ]
                )
                parsed_events.append(event)
                seen_ids.add(event_id)
            except Exception as e:
                logger.error(f"Error parsing individual extracted item: {e}")

        logger.info(f"Extracted {len(parsed_events)} valid disaster events from news headlines.")
    except Exception as e:
        logger.error(f"LLM extraction pipeline failed: {e}")

    return parsed_events


# --- Serializers ---

def write_today_json(events: List[DisasterEvent]):
    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_active_events": len(events),
            "schema_version": "1.0.0"
        },
        "events": [event.model_dump() for event in events]
    }
    with open(TODAY_JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def write_geojson(events: List[DisasterEvent]):
    features = []
    for event in events:
        features.append({
            "type": "Feature",
            "id": event.event_id,
            "geometry": {
                "type": "Point",
                "coordinates": [event.location.longitude, event.location.latitude]
            },
            "properties": {
                "event_type": event.event_type,
                "severity_level": event.severity_level,
                "title": event.title,
                "summary": event.summary,
                "country": event.location.country,
                "place_name": event.location.place_name,
                "magnitude": event.metrics.magnitude,
                "depth_km": event.metrics.depth_km,
                "timestamp_utc": event.timestamp_utc
            }
        })

    geojson_payload = {
        "type": "FeatureCollection",
        "features": features
    }
    with open(GEOJSON_FILE, "w", encoding="utf-8") as f:
        json.dump(geojson_payload, f, indent=2)


def write_llms_txt(events: List[DisasterEvent]):
    lines = [
        "# Real-Time Global Disaster Intelligence Feed",
        f"Generated: {datetime.now(timezone.utc).isoformat()} | Agent Direct Ingestion Wire",
        "",
        "## Active Verified Incidents"
    ]
    for event in events:
        coords = f"[{event.location.latitude:.4f}, {event.location.longitude:.4f}]"
        mag_str = f" | Mag: {event.metrics.magnitude}" if event.metrics.magnitude else ""
        lines.append(
            f"- [{event.event_type.upper()}] {event.location.place_name} ({event.location.country}) "
            f"| Severity: {event.severity_level.capitalize()}{mag_str} | UTC: {event.timestamp_utc} "
            f"| Coords: {coords} | Summary: {event.summary}"
        )

    with open(LLMS_TXT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def push_to_huggingface_dataset():
    """Syncs the latest data files to a Hugging Face Dataset if tokens exist."""
    hf_token = os.getenv("HF_TOKEN")
    hf_repo_id = os.getenv("HF_DATASET_REPO")  # e.g., "username/disaster-intelligence-wire"

    if not hf_token or not hf_repo_id:
        logger.info("HF_TOKEN or HF_DATASET_REPO not configured. Skipping HF dataset sync.")
        return

    try:
        from huggingface_hub import HfApi
        api = HfApi(token=hf_token)
        for filepath in [TODAY_JSON_FILE, GEOJSON_FILE, LLMS_TXT_FILE]:
            api.upload_file(
                path_or_fileobj=filepath,
                path_in_repo=os.path.basename(filepath),
                repo_id=hf_repo_id,
                repo_type="dataset",
                commit_message=f"Autonomous update: {datetime.now(timezone.utc).isoformat()}"
            )
        logger.info("Successfully pushed outputs to Hugging Face Dataset.")
    except Exception as e:
        logger.error(f"Hugging Face upload failed: {e}")


# --- Main Orchestration ---

def main():
    logger.info("Beginning Disaster Wire run...")
    seen_ids = load_seen_ids()

    # Step 1: Collect Authoritative Ground Truth
    usgs_events = fetch_usgs_earthquakes(seen_ids)
    gdacs_events = fetch_gdacs_alerts(seen_ids)

    # Step 2: Ingest & Clean Open-Web RSS
    news_articles = fetch_google_news_rss()
    news_events = parse_unstructured_news_via_llm(news_articles, seen_ids)

    # Aggregate active events
    combined_new_events = usgs_events + gdacs_events + news_events
    logger.info(f"Aggregated {len(combined_new_events)} new events in this run.")

    # Step 3: Maintain rolling state (load past events from today.json if present)
    existing_events = []
    if os.path.exists(TODAY_JSON_FILE):
        try:
            with open(TODAY_JSON_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                existing_events = [DisasterEvent(**e) for e in old_data.get("events", [])]
        except Exception:
            existing_events = []

    # Merge and preserve chronological ordering (latest first)
    all_events = {e.event_id: e for e in (existing_events + combined_new_events)}
    sorted_events = sorted(
        all_events.values(),
        key=lambda x: x.timestamp_utc,
        reverse=True
    )[:100]  # Retain top 100 most recent active incidents

    # Step 4: Write endpoints
    write_today_json(sorted_events)
    write_geojson(sorted_events)
    write_llms_txt(sorted_events)
    save_seen_ids(seen_ids)

    # Step 5: Optional sync to Hugging Face
    push_to_huggingface_dataset()

    logger.info("Run finished successfully. Endpoints refreshed.")


if __name__ == "__main__":
    main()
