#!/usr/bin/env python3
"""
Autonomous Global Disaster Intelligence Wire for AI Agents
Queries authoritative feeds (USGS, GDACS) and dynamic news RSS, filters noise via LLM,
cross-references critical global infrastructure (ports, air cargo, data centers),
generates spatial and agent-optimized endpoints, and archives historical state.
"""

import os
import sys
import json
import math
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

import requests
import feedparser
from pydantic import BaseModel, Field

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("DisasterWire")

# Directory and File Paths
DATA_DIR = "data"
ARCHIVE_ROOT = os.path.join(DATA_DIR, "archive")
SEEN_IDS_FILE = os.path.join(DATA_DIR, "seen_ids.txt")
TODAY_JSON_FILE = os.path.join(DATA_DIR, "today.json")
GEOJSON_FILE = os.path.join(DATA_DIR, "events.geojson")
LLMS_TXT_FILE = os.path.join(DATA_DIR, "llms.txt")
LLMS_FULL_TXT_FILE = os.path.join(DATA_DIR, "llms-full.txt")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ARCHIVE_ROOT, exist_ok=True)


# --- Embedded Global Critical Infrastructure Knowledge Base ---

CRITICAL_INFRASTRUCTURE = [
    # Top Global Container Ports (UN/LOCODE)
    {"name": "Port of Shanghai", "type": "port", "code": "CNSHG", "country": "China", "lat": 31.2304, "lon": 121.4737},
    {"name": "Port of Singapore", "type": "port", "code": "SGSIN", "country": "Singapore", "lat": 1.2903, "lon": 103.8520},
    {"name": "Port of Ningbo-Zhoushan", "type": "port", "code": "CNNGB", "country": "China", "lat": 29.8683, "lon": 121.5440},
    {"name": "Port of Shenzhen", "type": "port", "code": "CNSZX", "country": "China", "lat": 22.5431, "lon": 114.0579},
    {"name": "Port of Busan", "type": "port", "code": "KRPUS", "country": "South Korea", "lat": 35.1796, "lon": 129.0756},
    {"name": "Port of Rotterdam", "type": "port", "code": "NLRTM", "country": "Netherlands", "lat": 51.9244, "lon": 4.4777},
    {"name": "Port of Los Angeles / Long Beach", "type": "port", "code": "USLAX", "country": "USA", "lat": 33.7431, "lon": -118.2673},
    {"name": "Port of Tokyo / Yokohama", "type": "port", "code": "JPTYO", "country": "Japan", "lat": 35.6528, "lon": 139.8394},
    {"name": "Port Klang", "type": "port", "code": "MYPKG", "country": "Malaysia", "lat": 3.0000, "lon": 101.4000},
    {"name": "Port of Antwerp-Bruges", "type": "port", "code": "BEANR", "country": "Belgium", "lat": 51.2194, "lon": 4.4025},

    # Major Air Cargo Gateways (IATA)
    {"name": "Hong Kong International Cargo Hub", "type": "airport", "code": "HKG", "country": "Hong Kong", "lat": 22.3080, "lon": 113.9185},
    {"name": "Memphis International (FedEx SuperHub)", "type": "airport", "code": "MEM", "country": "USA", "lat": 35.0424, "lon": -89.9767},
    {"name": "Shanghai Pudong Cargo Hub", "type": "airport", "code": "PVG", "country": "China", "lat": 31.1443, "lon": 121.8083},
    {"name": "Anchorage Ted Stevens (Trans-Pacific Cargo)", "type": "airport", "code": "ANC", "country": "USA", "lat": 61.1744, "lon": -149.9964},
    {"name": "Incheon International Airport", "type": "airport", "code": "ICN", "country": "South Korea", "lat": 37.4602, "lon": 126.4407},
    {"name": "Louisville Muhammad Ali (UPS Worldport)", "type": "airport", "code": "SDF", "country": "USA", "lat": 38.1741, "lon": -85.7360},
    {"name": "Frankfurt Airport CargoCity", "type": "airport", "code": "FRA", "country": "Germany", "lat": 50.0379, "lon": 8.5622},
    {"name": "Tokyo Narita Cargo Gateway", "type": "airport", "code": "NRT", "country": "Japan", "lat": 35.7647, "lon": 140.3863},

    # Critical Hyperscale Cloud Regions
    {"name": "Northern Virginia Cloud Corridor (us-east-1)", "type": "datacenter", "code": "US-VA", "country": "USA", "lat": 39.0438, "lon": -77.4874},
    {"name": "Frankfurt Cloud Region (eu-central-1)", "type": "datacenter", "code": "EU-FRA", "country": "Germany", "lat": 50.1109, "lon": 8.6821},
    {"name": "Tokyo Cloud Region (ap-northeast-1)", "type": "datacenter", "code": "AP-TYO", "country": "Japan", "lat": 35.6895, "lon": 139.6917},
    {"name": "Singapore Cloud Region (ap-southeast-1)", "type": "datacenter", "code": "AP-SIN", "country": "Singapore", "lat": 1.3521, "lon": 103.8198},
    {"name": "Dublin Cloud Hub (eu-west-1)", "type": "datacenter", "code": "EU-DUB", "country": "Ireland", "lat": 53.3498, "lon": -6.2603}
]


# --- Geospatial and Infrastructure Helpers ---

def compute_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two points via the Haversine formula."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def encode_geohash(latitude: float, longitude: float, precision: int = 5) -> str:
    """Generates standard geohash string without external C dependencies."""
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


def audit_exposed_infrastructure(lat: float, lon: float, threshold_km: float = 150.0) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Identifies critical hubs within disruption range and derives machine actions."""
    exposed = []
    actions = []

    for hub in CRITICAL_INFRASTRUCTURE:
        dist = compute_distance_km(lat, lon, hub["lat"], hub["lon"])
        if dist <= threshold_km:
            exposed.append({
                "name": hub["name"],
                "type": hub["type"],
                "code": hub["code"],
                "country": hub["country"],
                "distance_km": round(dist, 1)
            })

            if hub["type"] == "port":
                actions.append(f"audit_maritime_berth_{hub['code']}")
                actions.append("reroute_container_freight")
            elif hub["type"] == "airport":
                actions.append(f"check_air_cargo_delay_{hub['code']}")
            elif hub["type"] == "datacenter":
                actions.append(f"initiate_cloud_failover_{hub['code']}")

    return exposed, sorted(list(set(actions)))


# --- Pydantic Data Schemas ---

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
    exposed_infrastructure: List[Dict[str, Any]] = Field(default_factory=list)
    recommended_agent_actions: List[str] = Field(default_factory=list)
    timestamp_utc: str
    sources: List[EventSource]


# --- State Deduplication ---

def load_seen_ids() -> set:
    if os.path.exists(SEEN_IDS_FILE):
        with open(SEEN_IDS_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    return set()

def save_seen_ids(seen_ids: set):
    truncated = list(seen_ids)[-5000:]
    with open(SEEN_IDS_FILE, "w", encoding="utf-8") as f:
        for item in truncated:
            f.write(f"{item}\n")


# --- Ingestion: USGS Earthquakes ---

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

            exposed_hubs, suggested_actions = audit_exposed_infrastructure(lat, lon)
            if mag >= 6.5:
                suggested_actions.extend(["monitor_aftershocks", "inspect_maritime_tsunami_bulletins"])

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
                exposed_infrastructure=exposed_hubs,
                recommended_agent_actions=sorted(list(set(suggested_actions))) or ["monitor_telemetry"],
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


# --- Ingestion: GDACS RSS ---

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
            exposed_hubs, suggested_actions = audit_exposed_infrastructure(lat, lon)

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
                exposed_infrastructure=exposed_hubs,
                recommended_agent_actions=suggested_actions or ["monitor_telemetry"],
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


# --- Ingestion: Google News RSS + LLM Semantic Normalization ---

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
        "Filter out metaphorical news ('political earthquake', 'flood of layoffs'). "
        "Estimate approximate latitude and longitude coordinates based on named location. "
        "Assign an ISO-2 country code and provide realistic metrics if mentioned. "
        "Output JSON only in format: {\"events\": [ ... ]}"
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
                exposed_hubs, suggested_actions = audit_exposed_infrastructure(lat, lon)

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
                    exposed_infrastructure=exposed_hubs,
                    recommended_agent_actions=suggested_actions or ["monitor_telemetry"],
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


# --- Serializers and Historical Archival Writers ---

def write_today_json(events: List[DisasterEvent]):
    payload = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_active_events": len(events),
            "schema_version": "2.1.0"
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
                "exposed_infrastructure_count": len(event.exposed_infrastructure),
                "timestamp_utc": event.timestamp_utc
            }
        })
    with open(GEOJSON_FILE, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2)


def write_llms_endpoints(events: List[DisasterEvent]):
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. Standard llms.txt index
    index_content = f"""# Disaster Intelligence Wire
> Real-time natural disaster intelligence feed engineered for autonomous agents, LLMs, and RAG pipelines.

## Canonical Endpoints
- [Active Incidents (JSON)](today.json): Filtered feed of ongoing real-world disasters within the last 24-48 hours.
- [Spatial Telemetry (GeoJSON)](events.geojson): RFC 7946 Point feature collection for GIS mapping and spatial vector search.
- [Full Text Briefing (Markdown)](llms-full.txt): Complete, zero-shot context window briefing for direct agent prompt injection.
- [Daily Archive Root](archive/): Daily historical JSON logs and Markdown situational reports partitioned by YYYY/MM.

## Agent Directives
- Match `geohash` prefixes for spatial proximity lookups to eliminate trigonometric calculations in prompts.
- Check `exposed_infrastructure` for direct supply chain, air cargo, and data center disruption vectors.
- Evaluate `recommended_agent_actions` to execute deterministic triage playbooks.
"""
    with open(LLMS_TXT_FILE, "w", encoding="utf-8") as f:
        f.write(index_content)

    # 2. Rich context llms-full.txt
    full_lines = [
        "# Disaster Intelligence Wire - Operational Context Briefing",
        f"Generated: {now_iso}",
        "",
        "## Active Incident Telemetry"
    ]
    for e in events:
        actions = ", ".join(e.recommended_agent_actions) if e.recommended_agent_actions else "None"
        infra = ", ".join([f"{h['name']} ({h['distance_km']}km)" for h in e.exposed_infrastructure]) or "No critical hubs within 150km"

        full_lines.extend([
            f"### [{e.event_type.upper()}] {e.title}",
            f"- **Cluster ID:** `{e.cluster_id}` | **Severity:** `{e.severity_level}` | **Phase:** `{e.lifecycle_phase}`",
            f"- **Location:** {e.location.place_name} ({e.location.country}) | Geohash: `{e.location.geohash}`",
            f"- **Coordinates:** `[{e.location.latitude}, {e.location.longitude}]`",
            f"- **Exposed Infrastructure:** {infra}",
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
            infra_list = item.get("exposed_infrastructure", [])
            infra_str = ", ".join([f"{h['name']} ({h['distance_km']}km)" for h in infra_list]) if infra_list else "None within 150km"

            md_lines.extend([
                f"### {item['title']}",
                f"- **Type / Severity:** `{item['event_type']}` | `{item['severity_level']}`",
                f"- **Location:** {item['location']['place_name']} ({item['location']['country']}) | Geohash: `{item['location'].get('geohash')}`",
                f"- **Coordinates:** `[{item['location']['latitude']}, {item['location']['longitude']}]`",
                f"- **Exposed Supply Chain Hubs:** {infra_str}",
                f"- **Recommended Agent Actions:** {actions}",
                f"- **Summary:** {item['summary']}",
                ""
            ])

    with open(md_archive_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    logger.info(f"Daily archive saved to {json_archive_path} and {md_archive_path}")


def push_to_huggingface_dataset():
    hf_token = os.getenv("HF_TOKEN")
    hf_repo_id = os.getenv("HF_DATASET_REPO")

    if not hf_token or not hf_repo_id:
        return

    try:
        from huggingface_hub import HfApi
        api = HfApi(token=hf_token)
        for filepath in [TODAY_JSON_FILE, GEOJSON_FILE, LLMS_TXT_FILE, LLMS_FULL_TXT_FILE]:
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


# --- Main Pipeline Orchestrator ---

def main():
    logger.info("Starting Disaster Intelligence Wire run...")
    seen_ids = load_seen_ids()

    # Ingestion steps
    usgs_events = fetch_usgs_earthquakes(seen_ids)
    gdacs_events = fetch_gdacs_alerts(seen_ids)
    news_articles = fetch_google_news_rss()
    news_events = parse_unstructured_news_via_llm(news_articles, seen_ids)

    combined_new = usgs_events + gdacs_events + news_events
    logger.info(f"New incidents detected in this cycle: {len(combined_new)}")

    # Merge with active rolling window
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

    # Write public endpoints and historical logs
    write_today_json(sorted_events)
    write_geojson(sorted_events)
    write_llms_endpoints(sorted_events)
    write_daily_archive(sorted_events)
    save_seen_ids(seen_ids)

    # Optional dataset push
    push_to_huggingface_dataset()

    logger.info("Disaster Intelligence Wire finished execution successfully.")


if __name__ == "__main__":
    main()
