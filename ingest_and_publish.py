import os
import json
import logging
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("DisasterWire")

# Geohash approximation without external C-extensions
def encode_geohash(latitude: float, longitude: float, precision: int = 5) -> str:
    """Computes standard geohash string for spatial proximity grouping."""
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


# --- Enriched Event Fields for Agents ---

class EnhancedDisasterEvent(BaseModel):
    event_id: str
    cluster_id: str = Field(description="Deduplication group for aftershocks or secondary news reports")
    lifecycle_phase: str = Field(
        default="emerging",
        description="emerging | escalating | stabilizing | concluded"
    )
    event_type: str
    severity_level: str
    title: str
    summary: str
    geohash: str
    iso_country_code: Optional[str] = "GLB"
    location_name: str
    coordinates: List[float]  # [longitude, latitude]
    recommended_agent_actions: List[str] = Field(default_factory=list)
    timestamp_utc: str
    raw_sources: List[str]


# --- Archival Engine ---

def write_daily_archive(events: List[EnhancedDisasterEvent]):
    """
    Persists data into data/archive/YYYY/MM/YYYY-MM-DD.json and .md
    Maintains an idempotent, append-and-merge log for historical RAG.
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")

    archive_dir = os.path.join("data", "archive", year_str, month_str)
    os.makedirs(archive_dir, exist_ok=True)

    json_archive_path = os.path.join(archive_dir, f"{date_str}.json")
    md_archive_path = os.path.join(archive_dir, f"{date_str}.md")

    # 1. Merge with existing archive if workflow has run earlier today
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

    # 2. Write daily JSON
    with open(json_archive_path, "w", encoding="utf-8") as f:
        json.dump({
            "archive_date": date_str,
            "total_incidents": len(consolidated_events),
            "updated_at": now.isoformat(),
            "events": consolidated_events
        }, f, indent=2)

    # 3. Generate human/agent markdown briefing
    md_lines = [
        f"# Daily Global Disaster Intelligence Brief: {date_str}",
        f"**Consolidated Records:** {len(consolidated_events)} incidents | **Last Synchronized:** {now.isoformat()}",
        "",
        "## Critical & Severe Incidents",
        ""
    ]

    has_high_priority = False
    for item in consolidated_events:
        if item.get("severity_level") in ["severe", "catastrophic"]:
            has_high_priority = True
            actions = ", ".join(item.get("recommended_agent_actions", [])) or "Monitor situation"
            md_lines.extend([
                f"### {item['title']}",
                f"- **Type / Severity:** `{item['event_type']}` | `{item['severity_level']}`",
                f"- **Lifecycle Phase:** `{item.get('lifecycle_phase', 'active')}`",
                f"- **Location:** {item['location_name']} (Geohash: `{item.get('geohash')}`)",
                f"- **Coordinates:** `[{item['coordinates'][1]}, {item['coordinates'][0]}]`",
                f"- **Recommended Agent Actions:** {actions}",
                f"- **Summary:** {item['summary']}",
                ""
            ])

    if not has_high_priority:
        md_lines.append("_No severe or catastrophic incidents recorded for this date._\n")

    md_lines.append("## Minor & Moderate Activity Log\n")
    for item in consolidated_events:
        if item.get("severity_level") in ["minor", "moderate"]:
            md_lines.append(
                f"- `{item['timestamp_utc']}` | **{item['event_type']}** | {item['location_name']} | {item['summary']}"
            )

    with open(md_archive_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    logger.info(f"Daily archive saved to {json_archive_path} and {md_archive_path}")


def write_llms_endpoints(events: List[EnhancedDisasterEvent]):
    """Generates llms.txt (index) and llms-full.txt (rich context) according to the spec."""
    now_iso = datetime.now(timezone.utc).isoformat()
    
    # 1. llms.txt (Specification-compliant index)
    llms_txt_content = f"""# Disaster Intelligence Wire
> Real-time, machine-readable natural disaster intelligence feed engineered for autonomous agents, LLMs, and automated RAG pipelines.

## Canonical Endpoints
- [Active Incidents (JSON)](today.json): Filtered feed of ongoing real-world disasters within the last 24-48 hours.
- [Spatial Telemetry (GeoJSON)](events.geojson): Standard RFC 7946 Point feature collection for GIS mapping.
- [Full Text Briefing (Markdown)](llms-full.txt): Complete, zero-shot context window briefing for direct agent prompt injection.
- [Daily Archive Root](archive/): Daily historical JSON logs and Markdown situational reports partitioned by YYYY/MM.

## Agent Directives
- Prefer `geohash` for spatial cluster searches to avoid coordinate geometry overhead.
- Check `lifecycle_phase` to handle updates and avoid treating repeated reports as multiple occurrences.
"""
    with open(os.path.join("data", "llms.txt"), "w", encoding="utf-8") as f:
        f.write(llms_txt_content)

    # 2. llms-full.txt (Expanded single-file context window payload)
    full_lines = [
        "# Disaster Intelligence Wire - Operational Context Briefing",
        f"Generated: {now_iso}",
        "",
        "## Active Incident Telemetry"
    ]
    for e in events:
        actions = "; ".join(e.recommended_agent_actions) if e.recommended_agent_actions else "None specified"
        full_lines.extend([
            f"### [{e.event_type.upper()}] {e.title}",
            f"- **Cluster ID:** `{e.cluster_id}`",
            f"- **Severity:** `{e.severity_level}` | **Phase:** `{e.lifecycle_phase}`",
            f"- **Location:** {e.location_name} (ISO: `{e.iso_country_code}`, Geohash: `{e.geohash}`)",
            f"- **Coordinates:** `[{e.coordinates[1]}, {e.coordinates[0]}]`",
            f"- **Impact & Actions:** {actions}",
            f"- **Summary:** {e.summary}",
            ""
        ])

    with open(os.path.join("data", "llms-full.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(full_lines) + "\n")
