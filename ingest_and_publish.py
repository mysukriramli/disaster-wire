#!/usr/bin/env python3
"""
Autonomous Global Disaster Intelligence Wire for AI Agents
Queries authoritative feeds + dynamic news RSS, filters noise via LLM,
writes structured endpoints, and manages historical archives.
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
ARCHIVE_ROOT = os.path.join(DATA_DIR, "archive")
SEEN_IDS_FILE = os.path.join(DATA_DIR, "seen_ids.txt")
TODAY_JSON_FILE = os.path.join(DATA_DIR, "today.json")
GEOJSON_FILE = os.path.join(DATA_DIR, "events.geojson")
LLMS_TXT_FILE = os.path.join(DATA_DIR, "llms.txt")
LLMS_FULL_TXT_FILE = os.path.join(DATA_DIR, "llms-full.txt")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ARCHIVE_ROOT, exist_ok=True)


# --- Spatial Utility ---

def encode_geohash(latitude: float, longitude: float, precision: int = 5) -> str:
    """Computes a standard geohash string for LLM spatial proximity matching."""
    base32 = '0123456789bcdefghjkmnpqrstuvwxyz'
    lat_interval = [-90.0, 90.0]
    lon_interval = [-180.0, 180.0]
    geohash = []
    bits = [16, 8, 4, 2, 1]
    bit = 0
    ch = 0
    even = True

    while len(geohash) < precision:
        if even:
            mid = (lon_interval[0] + lon_interval[1]) / 2
            if longitude > mid:
                ch |= bits[bit]
                lon_interval[0] = mid
            else:
                lon_interval[1] = mid
        else:
            mid = (lat_interval[0] + lat_interval[1]) / 2
            if latitude > mid:
                ch |= bits[bit]
                lat_interval[0] = mid
            else:
                lat_interval[1] = mid

        even = not even
        if bit < 4:
            bit += 1
        else:
            geohash.append(base32[ch])
            bit = 0
            ch = 0

    return ''.join(geohash)


# --- Pydantic Data Structures ---

class EventMetrics(BaseModel):
    magnitude: Optional[float] = None
    depth_km: Optional[float] = None
    wind_speed_kmh: Optional[float] = None
    alert_score: Optional[float] = None

class EventLocation(BaseModel):
    country: str
    iso_country_code: Optional[str] = "GLB"
    region_admin1: Optional[str] = None
    place_name: str
    latitude: float
    longitude: float
    geohash: str

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
    cluster_id: str
    lifecycle_phase: str = Field(default="emerging", description="emerging | escalating | stabilizing | concluded")
    event_type: str = Field(description="earthquake, tsunami, flood, cyclone, wildfire, volcanic_eruption, severe_weather")
    severity_level: str = Field(description="minor, moderate, severe, catastrophic")
    title: str
    summary: str
    metrics: EventMetrics = Field(default_factory=EventMetrics)
    location: EventLocation
    impact: EventImpact = Field(default_factory=EventImpact)
    recommended_agent_actions: List[str] = Field(default_factory=list)
    timestamp_utc: str
    sources: List[EventSource]


# --- State Management ---

def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen_ids(seen_ids: set):
    truncated_ids = list(seen_ids)[-5000:]
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        for item in truncated_ids:
            f.write(f"{item}\n")


# --- Ingestion: USGS Feeds ---

def fetch_usgs_earthquakes(seen_ids: set) -> List[DisasterEvent]:
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
            coords = feature["geometry"]["coordinates"]
            mag = float(props["mag"]) if props.get("mag") is not None else 0.0

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
            place = props.get("place", "Unknown location")
            country = place.split(",")[-1].strip() if "," in place else place
            lon, lat = float(coords[0]), float(coords[1])
            gh = encode_geohash(lat, lon)

            event = DisasterEvent(
                event_id=event_id,
                cluster_id=f"cluster_eq_{gh[:3]}",
                lifecycle_phase="escalating" if mag >= 6.0 else "emerging",
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
                    place_name=place,
                    latitude=lat,
                    longitude=lon,
                    geohash=gh
                ),
                recommended_agent_actions=["monitor_aftershocks", "inspect_maritime_tsunami_bulletins"] if mag >= 6.5 else [],
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


# --- Ingestion: GDACS Feeds ---

def fetch_gdacs_alerts(seen_ids: set) -> List[DisasterEvent]:
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

            geo_point = getattr(entry, "georss_point", None)
            lat, lon = 0.0, 0.0
            if geo_point:
                parts = geo_point.strip().split()
                if len(parts) == 2:
                    lat, lon = float(parts[0]), float(parts[1])

            title_lower = title.lower()
            event_type = "severe_weather"
            if "earthquake" in title_lower:
                event_type = "earthquake"
            elif any(k in title_lower for k in ["cyclone", "typhoon", "hurricane"]):
                event_type = "cyclone"
            elif "flood" in title_lower:
                event_type = "flood"
            elif "volcano" in title_lower:
                event_type = "volcanic_eruption"
            elif "tsunami" in title_lower:
                event_type = "tsunami"

            severity = "moderate"
            if "red" in title_lower or "high" in title_lower:
                severity = "catastrophic"
            elif "orange" in title_lower:
                severity = "severe"

            gh = encode_geohash(lat, lon) if (lat != 0.0 or lon != 0.0) else "00000"

            event = DisasterEvent(
                event_id=event_id,
                cluster_id=f"cluster_{event_type}_{gh[:3]}",
                lifecycle_phase="stabilizing" if "green" in title_lower else "emerging",
                event_type=event_type,
                severity_level=severity,
                title=title,
                summary=getattr(entry, "description", title),
                metrics=EventMetrics(),
                location=EventLocation(
                    country="Global",
                    place_name=title,
                    latitude=lat,
                    longitude=lon,
                    geohash=gh
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


# --- Ingestion: Google News RSS + LLM Extraction ---

def fetch_google_news_rss() -> List[Dict[str, str]]:
    query = '(earthquake OR tsunami OR "flash flood" OR "tropical cyclone" OR "volcanic eruption") when:1d'
    encoded_query = requests.utils.quote(query)
    feed_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en-US&gl=US&ceid=US:en"
    
    articles = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries[:25]:
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "published": getattr(entry, "published", "")
            })
    except Exception as e:
        logger.error(f"Google News RSS fetch failed: {e}")
    return articles


def parse_unstructured_news_via_llm(articles: List[Dict[str, str]], seen_ids: set) -> List[DisasterEvent]:
    api_key = os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")

    if not api_key:
        logger.warning("LLM_API_KEY is not set. Skipping RSS LLM processing.")
        return []

    unseen_articles = []
    for art in articles:
        art_hash = hashlib.sha256(art["link"].encode()).hexdigest()[:16]
        if f"news_{art_hash}" not in seen_ids:
            unseen_articles.append(art)

    if not unseen_articles:
        logger.info("No new news headlines to process.")
        return []

    system_prompt = (
        "You are an automated disaster triage agent. Extract REAL, PHYSICAL natural disasters "
        "(earthquake, tsunami, flood, cyclone, wildfire, volcanic_eruption, severe_weather). "
        "Strictly filter out metaphorical news ('political earthquake', 'flood of tech applications'). "
        "Estimate coordinates, assign standard geohash precision 5, assign an ISO-2 country code, "
        "and provide recommended agent action strings (e.g. 'reroute_shipping', 'audit_power_grid'). "
        "Output JSON only: {\"events\": [ ... ]}"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": model_name,
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(unseen_articles)}
        ]
    }

    parsed_events = []
    try:
        res = requests.post(f"{api_base}/chat/completions", headers=headers, json=payload, timeout=45)
        res.raise_for_status()
        raw_content = res.json()["choices"][0]["message"]["content"]
        extracted_data = json.loads(raw_content)

        now_iso = datetime.now(timezone.utc).isoformat()
        for item in extracted_data.get("events", []):
            try:
                title = item.get("title", "")
                loc = item.get("location", {})
                lat = float(loc.get("latitude", 0.0))
                lon = float(loc.get("longitude", 0.0))
                
                event_hash = hashlib.sha256(f"{title}_{lat:.2f}_{lon:.2f}".encode()).hexdigest()[:16]
                event_id = f"news_{event_hash}"

                if event_id in seen_ids:
                    continue

                gh = encode_geohash(lat, lon) if (lat != 0.0 or lon != 0.0) else "00000"

                event = DisasterEvent(
                    event_id=event_id,
                    cluster_id=f"cluster_{gh[:3]}",
                    lifecycle_phase=item.get("lifecycle_phase", "emerging"),
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
                        iso_country_code=loc.get("iso_country_code", "GLB"),
                        region_admin1=loc.get("region_admin1"),
                        place_name=loc.get("place_name", "Unknown"),
                        latitude=lat,
                        longitude=lon,
                        geohash=gh
                    ),
                    impact=EventImpact(
                        reported_fatalities=item.get("impact", {}).get("reported_fatalities"),
                        reported_displaced=item.get("impact", {}).get("reported_displaced"),
                        infrastructure_damage=item.get("impact", {}).get("infrastructure_damage")
                    ),
                    recommended_agent_actions=item.get("recommended_agent_actions", []),
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
                logger.error(f"Error parsing news item: {e}")

        logger.info(f"Extracted {len(parsed_events)} valid disaster events from news.")
    except Exception as e:
        logger.error(f"LLM extraction pipeline failed: {e}")

    return parsed_events


# --- Serialization & Archival Writers ---

def write_today_json(events: List[DisasterEvent]):
    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_active_events": len(events),
            "schema_version": "2.0.0"
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
                "cluster_id": event.cluster_id,
                "geohash": event.location.geohash,
                "title": event.title,
                "country": event.location.country,
                "magnitude": event.metrics.magnitude,
                "timestamp_utc": event.timestamp_utc
            }
        })
    with open(GEOJSON_FILE, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2)


def write_llms_endpoints(events: List[DisasterEvent]):
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. llms.txt index
    index_content = f"""# Disaster Intelligence Wire
> Real-time natural disaster intelligence feed engineered for autonomous agents, LLMs, and RAG pipelines.

## Canonical Endpoints
- [Active Incidents (JSON)](today.json): Filtered feed of ongoing real-world disasters within the last 24-48 hours.
- [Spatial Telemetry (GeoJSON)](events.geojson): RFC 7946 Point feature collection for GIS mapping.
- [Full Text Briefing (Markdown)](llms-full.txt): Complete, zero-shot context window briefing for direct agent prompt injection.
- [Daily Archive Root](archive/): Daily historical JSON logs and Markdown situational reports partitioned by YYYY/MM.

## Agent Directives
- Prefer `geohash` for spatial cluster searches to avoid coordinate geometry overhead.
- Check `lifecycle_phase` to handle updates and avoid treating repeated reports as multiple occurrences.
"""
    with open(LLMS_TXT_FILE, "w", encoding="utf-8") as f:
        f.write(index_content)

    # 2. llms-full.txt context payload
    full_lines = [
        "# Disaster Intelligence Wire - Operational Context Briefing",
        f"Generated: {now_iso}",
        "",
        "## Active Incident Telemetry"
    ]
    for e in events:
        actions = ", ".join(e.recommended_agent_actions) if e.recommended_agent_actions else "Monitor situation"
        full_lines.extend([
            f"### [{e.event_type.upper()}] {e.title}",
            f"- **Cluster ID:** `{e.cluster_id}` | **Severity:** `{e.severity_level}` | **Phase:** `{e.lifecycle_phase}`",
            f"- **Location:** {e.location.place_name} ({e.location.country}) | Geohash: `{e.location.geohash}`",
            f"- **Coordinates:** `[{e.location.latitude}, {e.location.longitude}]`",
            f"- **Recommended Agent Actions:** {actions}",
            f"- **Summary:** {e.summary}",
            ""
        ])
    with open(LLMS_FULL_TXT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(full_lines) + "\n")


def write_daily_archive(events: List[DisasterEvent]):
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")

    archive_dir = os.path.join(ARCHIVE_ROOT, year_str, month_str)
    os.makedirs(archive_dir, exist_ok=True)

    json_archive_path = os.path.join(archive_dir, f"{date_str}.json")
    md_archive_path = os.path.join(archive_dir, f"{date_str}.md")

    existing_events = {}
    if os.path.exists(json_archive_path):
        try:
            with open(json_archive_path, "r", encoding="utf-8") as f:
                prior_data = json.load(f)
                for item in prior_data.get("events", []):
                    existing_events[item["event_id"]] = item
        except Exception as e:
            logger.warning(f"Could not read existing daily archive: {e}")

    for event in events:
        existing_events[event.event_id] = event.model_dump()

    consolidated_events = sorted(
        existing_events.values(),
        key=lambda x: x["timestamp_utc"],
        reverse=True
    )

    with open(json_archive_path, "w", encoding="utf-8") as f:
        json.dump({
            "archive_date": date_str,
            "total_incidents": len(consolidated_events),
            "updated_at": now.isoformat(),
            "events": consolidated_events
        }, f, indent=2)

    md_lines = [
        f"# Daily Global Disaster Intelligence Brief: {date_str}",
        f"**Consolidated Records:** {len(consolidated_events)} incidents | **Last Synchronized:** {now.isoformat()}",
        "",
        "## Critical & Severe Incidents",
        ""
    ]
    for item in consolidated_events:
        if item.get("severity_level") in ["severe", "catastrophic"]:
            actions = ", ".join(item.get("recommended_agent_actions", [])) or "Monitor situation"
            md_lines.extend([
                f"### {item['title']}",
                f"- **Type / Severity:** `{item['event_type']}` | `{item['severity_level']}`",
                f"- **Location:** {item['location']['place_name']} ({item['location']['country']}) | Geohash: `{item['location'].get('geohash')}`",
                f"- **Coordinates:** `[{item['location']['latitude']}, {item['location']['longitude']}]`",
                f"- **Recommended Agent Actions:** {actions}",
                f"- **Summary:** {item['summary']}",
                ""
            ])

    with open(md_archive_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    logger.info(f"Daily archive persisted to {json_archive_path} and {md_archive_path}")


# --- Main ---

def main():
    logger.info("Starting Disaster Wire execution...")
    seen_ids = load_seen_ids()

    usgs_events = fetch_usgs_earthquakes(seen_ids)
    gdacs_events = fetch_gdacs_alerts(seen_ids)
    news_articles = fetch_google_news_rss()
    news_events = parse_unstructured_news_via_llm(news_articles, seen_ids)

    combined_new = usgs_events + gdacs_events + news_events
    logger.info(f"New incidents detected in this cycle: {len(combined_new)}")

    existing_events = []
    if os.path.exists(TODAY_JSON_FILE):
        try:
            with open(TODAY_JSON_FILE, "r", encoding="utf-8") as f:
                old_data = json.load(f)
                existing_events = [DisasterEvent(**e) for e in old_data.get("events", [])]
        except Exception:
            existing_events = []

    merged = {e.event_id: e for e in (existing_events + combined_new)}
    sorted_events = sorted(merged.values(), key=lambda x: x.timestamp_utc, reverse=True)[:100]

    # Write all endpoints
    write_today_json(sorted_events)
    write_geojson(sorted_events)
    write_llms_endpoints(sorted_events)
    write_daily_archive(sorted_events)
    save_seen_ids(seen_ids)

    logger.info("Run completed successfully.")


if __name__ == "__main__":
    main()
