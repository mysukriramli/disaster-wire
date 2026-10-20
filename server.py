#!/usr/bin/env python3
"""
Disaster Intelligence Wire - Stdio MCP Server for Glama Sandbox & Local Agents
Communicates via standard input/output (stdio) using the FastMCP framework.
Provides high-density, hallucination-resistant natural disaster telemetry.
"""

import os
import json
import math
import logging
from typing import Optional, Literal, Annotated
from pydantic import Field
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.ERROR)

mcp = FastMCP("disaster-wire")

LOCAL_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "today.json")
FALLBACK_URL = "https://raw.githubusercontent.com/mysukriramli/disaster-wire/main/data/today.json"


def _load_data():
    """Loads active disaster telemetry from local repository storage with remote fallback."""
    if os.path.exists(LOCAL_DATA_PATH):
        try:
            with open(LOCAL_DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    try:
        import requests
        res = requests.get(FALLBACK_URL, timeout=8)
        if res.status_code == 200:
            return res.json()
    except Exception:
        pass

    return {"metadata": {}, "events": []}


# --- Tool 1: list_active_disasters ---

@mcp.tool()
def list_active_disasters(
    event_type: Annotated[
        Optional[Literal["earthquake", "tsunami", "flood", "cyclone", "wildfire", "volcanic_eruption", "severe_weather"]],
        Field(
            default=None,
            description="Filter events by natural hazard category. Allowed values: 'earthquake', 'tsunami', 'flood', 'cyclone', 'wildfire', 'volcanic_eruption', 'severe_weather'. Leave null or omit to return all incident types."
        )
    ] = None,
    severity: Annotated[
        Optional[Literal["minor", "moderate", "severe", "catastrophic"]],
        Field(
            default=None,
            description="Filter events by alert severity level. Allowed values: 'minor', 'moderate', 'severe', 'catastrophic'. Leave null or omit to include all severity levels."
        )
    ] = None,
    country: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Case-insensitive substring filter matching target country or jurisdiction (e.g., 'Japan', 'Philippines', 'United States'). Leave null or omit to return global events."
        )
    ] = None,
    limit: Annotated[
        int,
        Field(
            default=10,
            ge=1,
            le=50,
            description="Maximum number of active disaster records to return in the payload. Must be an integer between 1 and 50. Defaults to 10."
        )
    ] = 10
) -> str:
    """
    List and filter active global natural disasters from the rolling 24-48 hour pool.

    USAGE ROUTING:
    - USE this tool to discover ongoing disasters, search by nation or jurisdiction, or filter by hazard type or severity level.
    - DO NOT USE this tool if you already possess a specific 'event_id'; use 'get_disaster_by_id' instead for full telemetry.
    - DO NOT USE this tool for coordinate-based radial proximity queries; use 'find_disasters_near_coordinates' instead.

    BEHAVIORAL DISCLOSURE:
    - Pure read-only operation with zero side effects.
    - Data is sourced from authoritative sensors (USGS, GDACS) and dynamic news feeds, updated every 4 hours.
    - If no incidents match the query criteria, returns JSON with 'matched_count': 0 and an empty 'events': [] array (never throws an error).

    RETURNS:
    JSON string containing:
    - 'matched_count' (int): Number of incidents matching filters.
    - 'total_active_pool' (int): Total active events currently monitored globally.
    - 'events' (list): Array of disaster objects including 'event_id', 'title', 'severity_level', 'geohash', and 'summary'.
    """
    data = _load_data()
    events = data.get("events", [])
    filtered = []

    for event in events:
        if event_type and event.get("event_type", "").lower() != event_type.strip().lower():
            continue
        if severity and event.get("severity_level", "").lower() != severity.strip().lower():
            continue
        if country:
            event_country = event.get("location", {}).get("country", "")
            if country.strip().lower() not in event_country.lower():
                continue
        filtered.append(event)

    filtered = filtered[:max(1, min(int(limit), 50))]
    return json.dumps({
        "matched_count": len(filtered),
        "total_active_pool": len(events),
        "events": filtered
    }, indent=2)


# --- Tool 2: get_disaster_by_id ---

@mcp.tool()
def get_disaster_by_id(
    event_id: Annotated[
        str,
        Field(
            description="The exact, unique incident identifier string (e.g., 'usgs_nc75001234', 'gdacs_1002341', or 'news_e5f6g7h8'). Obtain valid IDs by first calling 'list_active_disasters' or 'find_disasters_near_coordinates'."
        )
    ]
) -> str:
    """
    Retrieve comprehensive telemetry, impact figures, and supply chain exposure for a specific disaster ID.

    USAGE ROUTING:
    - USE this tool exclusively when you already hold a valid 'event_id' and require complete technical metrics, casualty estimates, affected ports/airports, or recommended triage actions.
    - DO NOT USE this tool for discovering active disasters; call 'list_active_disasters' first to obtain incident IDs.
    - DO NOT USE this tool to check geographic perimeters; use 'find_disasters_near_coordinates' instead.

    BEHAVIORAL DISCLOSURE:
    - Pure read-only lookup with zero side effects.
    - If the requested 'event_id' is not present in the active pool (e.g., expired or invalid), returns a JSON object with an 'error' key describing the missing ID.

    RETURNS:
    JSON string of the complete disaster record containing:
    - 'metrics': Physical measurements ('magnitude', 'depth_km', 'wind_speed_kmh', 'alert_score').
    - 'location': Decimal coordinates ('latitude', 'longitude', 'geohash', 'country').
    - 'exposed_infrastructure': Critical container ports, cargo airports, and cloud regions within 150 km.
    - 'recommended_agent_actions': Deterministic machine action directives (e.g., 'audit_maritime_berth', 'initiate_cloud_failover').
    """
    data = _load_data()
    for event in data.get("events", []):
        if event.get("event_id") == event_id.strip():
            return json.dumps(event, indent=2)
    return json.dumps({"error": f"Event '{event_id}' not found in active telemetry pool."})


# --- Tool 3: find_disasters_near_coordinates ---

@mcp.tool()
def find_disasters_near_coordinates(
    latitude: Annotated[
        float,
        Field(
            ge=-90.0,
            le=90.0,
            description="Target location latitude in decimal degrees (WGS-84 standard). Must be between -90.0 and 90.0 (e.g., 35.6762 for Tokyo, Japan)."
        )
    ],
    longitude: Annotated[
        float,
        Field(
            ge=-180.0,
            le=180.0,
            description="Target location longitude in decimal degrees (WGS-84 standard). Must be between -180.0 and 180.0 (e.g., 139.6503 for Tokyo, Japan)."
        )
    ],
    radius_km: Annotated[
        float,
        Field(
            default=500.0,
            ge=1.0,
            le=5000.0,
            description="Radial search perimeter measured in kilometers (km) from the target coordinates. Must be between 1.0 and 5000.0 km. Defaults to 500.0 km."
        )
    ] = 500.0
) -> str:
    """
    Locate active natural disasters within a radial distance from target latitude/longitude coordinates.

    USAGE ROUTING:
    - USE this tool whenever evaluating geographic exposure for a specific location, city, supply chain facility, or data center.
    - DO NOT USE this tool for national or categorical queries (e.g., 'all cyclones in Japan'); use 'list_active_disasters' instead.
    - DO NOT USE this tool if you already have an 'event_id'; use 'get_disaster_by_id' instead.

    BEHAVIORAL DISCLOSURE:
    - Calculates spherical great-circle distance using the Haversine formula against all active events in the pool.
    - Results are sorted in ascending order by physical distance ('distance_from_query_km'), placing closest threats first.
    - If no disasters fall within the requested radial boundary, returns JSON with 'matched_count': 0 and an empty 'results': [] array.

    RETURNS:
    JSON string containing:
    - 'query_center': [latitude, longitude] echoing the input coordinates.
    - 'search_radius_km' (float): The radial boundary applied in kilometers.
    - 'matched_count' (int): Total number of incidents within the boundary.
    - 'results' (list): Array of incident objects annotated with 'distance_from_query_km' (float rounded to 1 decimal).
    """
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371.0  # Earth's mean radius in km
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (math.sin(dlat / 2) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    data = _load_data()
    matches = []

    for event in data.get("events", []):
        loc = event.get("location", {})
        e_lat = loc.get("latitude")
        e_lon = loc.get("longitude")
        if e_lat is None or e_lon is None:
            continue

        distance = haversine(float(latitude), float(longitude), e_lat, e_lon)
        if distance <= float(radius_km):
            copy_e = dict(event)
            copy_e["distance_from_query_km"] = round(distance, 1)
            matches.append(copy_e)

    matches.sort(key=lambda x: x["distance_from_query_km"])
    return json.dumps({
        "query_center": [latitude, longitude],
        "search_radius_km": radius_km,
        "matched_count": len(matches),
        "results": matches
    }, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")
