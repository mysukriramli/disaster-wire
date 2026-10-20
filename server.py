#!/usr/bin/env python3
"""
Disaster Intelligence Wire - Production Stdio MCP Server for Glama
Built using explicit MCP protocol definitions for 100% TDQS schema coverage,
verified tool annotations, and deterministic agent usage routing.
"""

import asyncio
import os
import json
import math
import logging
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ToolAnnotations

logging.basicConfig(level=logging.ERROR)

app = Server("disaster-wire")

LOCAL_DATA_PATH = os.path.join(os.path.dirname(__file__), "data", "today.json")
FALLBACK_URL = "https://raw.githubusercontent.com/mysukriramli/disaster-wire/main/data/today.json"


def _load_data() -> dict:
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


# --- Tool Handlers ---

def execute_list_active_disasters(event_type=None, severity=None, country=None, limit=10) -> str:
    data = _load_data()
    events = data.get("events", [])
    filtered = []

    for event in events:
        if event_type and event.get("event_type", "").lower() != str(event_type).strip().lower():
            continue
        if severity and event.get("severity_level", "").lower() != str(severity).strip().lower():
            continue
        if country:
            event_country = event.get("location", {}).get("country", "")
            if str(country).strip().lower() not in event_country.lower():
                continue
        filtered.append(event)

    filtered = filtered[:max(1, min(int(limit or 10), 50))]
    return json.dumps({
        "matched_count": len(filtered),
        "total_active_pool": len(events),
        "events": filtered
    }, indent=2)


def execute_get_disaster_by_id(event_id: str) -> str:
    data = _load_data()
    for event in data.get("events", []):
        if event.get("event_id") == str(event_id).strip():
            return json.dumps(event, indent=2)
    return json.dumps({"error": f"Event '{event_id}' not found in active telemetry pool."})


def execute_find_disasters_near_coordinates(latitude: float, longitude: float, radius_km: float = 500.0) -> str:
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

        distance = haversine(float(latitude), float(longitude), float(e_lat), float(e_lon))
        if distance <= float(radius_km):
            copy_e = dict(event)
            copy_e["distance_from_query_km"] = round(distance, 1)
            matches.append(copy_e)

    matches.sort(key=lambda x: x["distance_from_query_km"])
    return json.dumps({
        "query_center": [float(latitude), float(longitude)],
        "search_radius_km": float(radius_km),
        "matched_count": len(matches),
        "results": matches
    }, indent=2)


# --- Explicit Protocol Registrations ---

READ_ONLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False
)

@app.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="list_active_disasters",
            description=(
                "List and filter real-time global natural disasters from the active 24-48 hour monitoring pool. "
                "Use to discover ongoing hazards, search by nation, or filter by hazard type or severity level. "
                "Do not use if you already possess a specific event_id (use get_disaster_by_id instead) or to evaluate coordinate proximity (use find_disasters_near_coordinates instead). "
                "Pure read-only operation with zero side effects. Returns {'matched_count': 0, 'events': []} when no incidents match filter criteria without raising errors."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": ["earthquake", "tsunami", "flood", "cyclone", "wildfire", "volcanic_eruption", "severe_weather"],
                        "description": "Natural hazard category. Allowed values: 'earthquake', 'tsunami', 'flood', 'cyclone', 'wildfire', 'volcanic_eruption', 'severe_weather'. Default is null (all types)."
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["minor", "moderate", "severe", "catastrophic"],
                        "description": "Alert severity level. Allowed values: 'minor', 'moderate', 'severe', 'catastrophic'. Default is null (all severities)."
                    },
                    "country": {
                        "type": "string",
                        "description": "Case-insensitive country name substring (e.g., 'Japan', 'Philippines', 'United States'). Default is null (worldwide)."
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                        "description": "Maximum number of disaster records to return in payload (integer between 1 and 50, defaults to 10)."
                    }
                },
                "additionalProperties": False
            },
            annotations=READ_ONLY_ANNOTATIONS
        ),
        Tool(
            name="get_disaster_by_id",
            description=(
                "Retrieve comprehensive technical telemetry, impact metrics, casualty estimates, and exposed infrastructure for a specific disaster ID. "
                "Use exclusively when you already hold a valid event_id obtained from list_active_disasters or find_disasters_near_coordinates. "
                "Do not use to browse or discover active disasters (use list_active_disasters instead) or for coordinate proximity queries (use find_disasters_near_coordinates instead). "
                "Pure read-only lookup. If the requested event_id is not in the active pool, returns an {'error': '...'} JSON object without raising exceptions."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "event_id": {
                        "type": "string",
                        "description": "Unique incident identifier string (e.g., 'usgs_nc75001234', 'gdacs_1002341', or 'news_e5f6g7h8')."
                    }
                },
                "required": ["event_id"],
                "additionalProperties": False
            },
            annotations=READ_ONLY_ANNOTATIONS
        ),
        Tool(
            name="find_disasters_near_coordinates",
            description=(
                "Locate active natural disasters within a radial distance (km) of target latitude and longitude coordinates. "
                "Use when evaluating geographic hazard exposure for specific facilities, cities, ports, or data centers at known coordinates. "
                "Do not use for country-wide or categorical queries (use list_active_disasters instead) or if you already hold an event_id (use get_disaster_by_id instead). "
                "Calculates great-circle distance via Haversine formula. Results are sorted ascending by distance_from_query_km. Returns {'matched_count': 0, 'results': []} if no incidents fall within radius."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "minimum": -90.0,
                        "maximum": 90.0,
                        "description": "Target latitude in decimal degrees (-90.0 to 90.0, WGS-84 standard)."
                    },
                    "longitude": {
                        "type": "number",
                        "minimum": -180.0,
                        "maximum": 180.0,
                        "description": "Target longitude in decimal degrees (-180.0 to 180.0, WGS-84 standard)."
                    },
                    "radius_km": {
                        "type": "number",
                        "minimum": 1.0,
                        "maximum": 5000.0,
                        "default": 500.0,
                        "description": "Radial search perimeter measured in kilometers (km) from target coordinates (1.0 to 5000.0, defaults to 500.0 km)."
                    }
                },
                "required": ["latitude", "longitude"],
                "additionalProperties": False
            },
            annotations=READ_ONLY_ANNOTATIONS
        )
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "list_active_disasters":
        result = execute_list_active_disasters(
            event_type=arguments.get("event_type"),
            severity=arguments.get("severity"),
            country=arguments.get("country"),
            limit=arguments.get("limit", 10)
        )
    elif name == "get_disaster_by_id":
        result = execute_get_disaster_by_id(
            event_id=arguments.get("event_id", "")
        )
    elif name == "find_disasters_near_coordinates":
        result = execute_find_disasters_near_coordinates(
            latitude=arguments.get("latitude", 0.0),
            longitude=arguments.get("longitude", 0.0),
            radius_km=arguments.get("radius_km", 500.0)
        )
    else:
        result = json.dumps({"error": f"Unknown tool: {name}"})

    return [TextContent(type="text", text=result)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
