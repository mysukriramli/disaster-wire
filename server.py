#!/usr/bin/env python3
"""
Disaster Intelligence Wire - Stdio MCP Server for Glama Sandbox
Communicates via standard input/output (stdio) using FastMCP.
"""

import os
import json
import math
import logging
from typing import Optional
from mcp.server.fastmcp import FastMCP

logging.basicConfig(level=logging.ERROR)

mcp = FastMCP("disaster-wire")

LOCAL_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "today.json")
FALLBACK_URL = "https://raw.githubusercontent.com/mysukriramli/disaster-wire/main/data/today.json"


def _load_data():
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


@mcp.tool()
def list_active_disasters(
    event_type: Optional[str] = None,
    severity: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 10
) -> str:
    """List ongoing natural disasters filtered by type, severity, or geographic jurisdiction."""
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


@mcp.tool()
def get_disaster_by_id(event_id: str) -> str:
    """Fetch exact telemetry, coordinates, and agent directives for an incident ID."""
    data = _load_data()
    for event in data.get("events", []):
        if event.get("event_id") == event_id.strip():
            return json.dumps(event, indent=2)
    return json.dumps({"error": f"Event '{event_id}' not found."})


@mcp.tool()
def find_disasters_near_coordinates(
    latitude: float,
    longitude: float,
    radius_km: float = 500.0
) -> str:
    """Locate active disasters within a radial boundary using the Haversine equation."""
    def haversine(lat1, lon1, lat2, lon2):
        R = 6371.0
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
