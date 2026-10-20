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
    """Loads active disaster telemetry from local storage with remote fallback."""
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


# --- Tool Execution Implementations ---

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


# --- MCP Tool Registrations (Explicit Protocol Schema) ---

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
                "List and filter active global natural disasters from the rolling 24-48 hour telemetry pool. "
                "USE this tool to discover ongoing hazards, search by nation or jurisdiction, or filter by hazard type or severity level. "
                "DO NOT USE this tool if you already possess a specific 'event_id'; use 'get_disaster_by_id' instead. "
                "DO NOT USE this tool for coordinate-based radial proximity queries; use 'find_disasters_near_coordinates' instead. "
                "Pure read-only operation with zero side effects. If no incidents match the criteria, returns 'matched_count': 0 with empty 'events': []."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "event_type": {
                        "type": "string",
                        "enum": ["earthquake", "tsunami", "flood", "cyclone", "wildfire", "volcanic_eruption", "severe_weather"],
                        "description": "Natural hazard category. Allowed values: 'earthquake', 'tsunami', 'flood', 'cyclone', 'wildfire', 'volcanic_eruption', 'severe_weather'. Leave null for all."
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["minor", "moderate", "severe", "catastrophic"],
                        "description": "Alert severity level. Allowed values: 'minor', 'moderate', 'severe', 'catastrophic'. Leave null for all."
                    },
                    "country": {
                        "type": "string",
                        "description": "Case-insensitive country name substring (e.g., 'Japan', 'Philippines', 'United States'). Leave null for worldwide."
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 50,
                        "default": 10,
                        "description": "Maximum number of incidents to return in payload (1 to 50, default: 10)."
                    }
                },
                "additionalProperties": False
            },
            annotations=READ_ONLY_ANNOTATIONS
        ),
        Tool(
            name="get_disaster_by_id",
            description=(
                "Retrieve comprehensive telemetry, impact metrics, casualty estimates, and exposed supply chain infrastructure for a specific disaster ID. "
                "USE exclusively when you already possess a valid 'event_id' from 'list_active_disasters' or 'find_disasters_near_coordinates'. "
                "DO NOT USE to discover or browse active disasters; call 'list_active_disasters' first. "
                "DO NOT USE for radial proximity queries; use 'find_disasters_near_coordinates' instead. "
                "Pure read-only lookup. If 'event_id' is not found, returns an 'error' JSON object without throwing exceptions."
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
                "Locate active natural disasters within a radial distance from target latitude and longitude coordinates. "
                "USE when evaluating geographic hazard exposure for specific facilities, cities, ports, or data centers at known coordinates. "
                "DO NOT USE for country-wide queries; use 'list_active_disasters' instead. "
                "DO NOT USE if you already have an 'event_id'; use 'get_disaster_by_id' instead. "
                "Calculates great-circle distance via Haversine equation. Results are sorted ascending by 'distance_from_query_km'. "
                "Returns 'matched_count': 0 and empty 'results': [] if no incidents fall within radius."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "minimum": -90.0,
                        "maximum": 90.0,
                        "description": "Target location latitude in decimal degrees (-90.0 to 90.0, WGS-84 standard)."
                    },
                    "longitude": {
                        "type": "number",
                        "minimum": -180.0,
                        "maximum": 180.0,
                        "description": "Target location longitude in decimal degrees (-180.0 to 180.0, WGS-84 standard)."
                    },
                    "radius_km": {
                        "type": "number",
                        "minimum": 1.0,
                        "maximum": 5000.0,
                        "default": 500.0,
                        "description": "Search perimeter radius in kilometers (km), from 1.0 to 5000.0 (default: 500.0 km)."
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
