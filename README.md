# Autonomous Global Disaster Intelligence Wire & MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP Server](https://img.shields.io/badge/MCP-Model%20Context%20Protocol-blue.svg)](https://modelcontextprotocol.io/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

An autonomous, 100% hands-off natural disaster intelligence wire engineered specifically for consumption by **AI Agents, Large Language Models (LLMs), and automated RAG pipelines** via the **Model Context Protocol (MCP)**.

The pipeline monitors physical crisis telemetry (earthquakes, tsunamis, floods, tropical cyclones, volcanic eruptions, and severe weather), strips metaphorical news using semantic LLM triage, calculates spatial geohashes, cross-references proximity to critical supply chain infrastructure, and exposes structured tools for downstream AI assistants.

---

## 🛠️ Model Context Protocol (MCP) Tools

This repository implements the Model Context Protocol (MCP) specification to provide real-time tool calling for Claude Desktop, Cursor, and custom agent runtimes.

### 1. `list_active_disasters`
Query active natural disaster events within the rolling 24–48 hour window with deterministic property filtering.
* **Arguments:**
  * `event_type` *(string, optional)*: Filter by event category (`earthquake`, `tsunami`, `flood`, `cyclone`, `wildfire`, `volcanic_eruption`, `severe_weather`).
  * `severity` *(string, optional)*: Filter by alert level (`minor`, `moderate`, `severe`, `catastrophic`).
  * `country` *(string, optional)*: Filter by target jurisdiction (e.g., `Japan`, `Philippines`, `United States`).
  * `limit` *(integer, optional)*: Max incidents to return (default: `10`, max: `50`).
* **Returns:** JSON object containing matched incidents, coordinates, geohashes, lifecycle phases, and recommended autonomous action playbooks.

### 2. `get_disaster_by_id`
Retrieve the full deterministic telemetry, impact stats, and source citations for a specific incident.
* **Arguments:**
  * `event_id` *(string, required)*: The unique incident identifier (e.g., `usgs_nc75001234`, `gdacs_1002341`, or `news_a1b2c3d4`).
* **Returns:** Full JSON payload including raw sensor readings, depth, wind speed, casualty counts, and exposed infrastructure hubs.

### 3. `find_disasters_near_coordinates`
Performs geospatial radial queries using the Haversine great-circle distance formula to detect active threats around specific target locations.
* **Arguments:**
  * `latitude` *(float, required)*: Target latitude between `-90.0` and `90.0`.
  * `longitude` *(float, required)*: Target longitude between `-180.0` and `180.0`.
  * `radius_km` *(float, optional)*: Radial search perimeter in kilometers (default: `500.0`).
* **Returns:** Sorted list of active disasters ordered by proximity to the query coordinates, annotated with calculated distance in kilometers.

---

## 📦 Client Configuration

### Connecting Claude Desktop (Remote SSE)
Add the following to your `claude_desktop_config.json`:
* **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
* **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "disaster-wire": {
      "url": "[https://sukriramli-disaster-wire-mcp.hf.space/gradio_api/mcp/sse](https://sukriramli-disaster-wire-mcp.hf.space/gradio_api/mcp/sse)"
    }
  }
}
