# CrisisNexus v2.0 — AI Crisis Response Platform

## Architecture

### Stack
- **Backend**: Python 3 + FastAPI + uvicorn (WebSocket support)
- **Geospatial Engine**: C shared library (`geo_engine.so`) via ctypes
- **Frontend**: Single-page HTML/CSS/JS (`static/index.html`)
- **Real-time**: WebSocket at `/ws` with live simulation background task
- **Maps**: Leaflet.js + CartoDB Dark Matter tiles (Hyderabad area)
- **Charts**: Chart.js 4.4 (line, doughnut, response time)

### File Structure
```
main.py          — FastAPI backend: REST API, WebSocket, C integration
geo_engine.c     — Native C geospatial library (haversine, dispatch scoring)
geo_engine.so    — Compiled C shared library (GCC 14, -O2)
static/
  index.html     — Full professional frontend (Leaflet, Chart.js, WebSocket)
replit.md        — This file
```

### Run Command
```
uvicorn main:app --host 0.0.0.0 --port 5000
```

## C Geospatial Engine (`geo_engine.c`)
Compiled with: `gcc -shared -fPIC -O2 -o geo_engine.so geo_engine.c -lm`

Exported functions:
- `haversine(lat1, lon1, lat2, lon2) -> double` — great-circle distance in km
- `find_nearest_unit(inc_lat, inc_lon, lats[], lons[], n) -> int` — index of nearest unit
- `dispatch_score(distance_km, severity, unit_load) -> double` — dispatch priority
- `estimate_eta_minutes(distance_km, speed_kmh) -> double` — arrival time
- `coverage_radius(area_sq_km, num_units) -> double` — zone sizing
- `batch_distances(src, targets[], n, out[])` — batch haversine computation

## REST API Endpoints
```
GET  /api/health                          Health check + geo engine status
GET  /api/incidents?status=&severity=     List incidents (filterable)
POST /api/incidents                       Create incident (triggers C dispatch)
GET  /api/incidents/{id}                  Single incident
PATCH /api/incidents/{id}/resolve         Mark resolved
POST /api/triage                          Gemini AI triage simulation
GET  /api/resources                       Resource allocation levels
GET  /api/units                           Emergency units
GET  /api/volunteers                      Volunteers sorted by distance (C engine)
POST /api/volunteers/{id}/dispatch        Dispatch volunteer (computes ETA via C)
POST /api/sos                             SOS alert (C engine finds nearest unit)
GET  /api/stats                           KPI stats + 12h history
GET  /api/analytics/incidents-by-type     Type distribution
WS   /ws                                  WebSocket live updates
```

## WebSocket Event Types
| Type | Direction | Description |
|------|-----------|-------------|
| `init` | Server→Client | Full initial state on connect |
| `new_incident` | Server→Client | New incident created |
| `incident_resolved` | Server→Client | Incident resolved |
| `incident_update` | Server→Client | Incident data changed |
| `ticker` | Server→Client | Live ticker message |
| `kpi_update` | Server→Client | KPI dashboard values |
| `resource_update` | Server→Client | Resource level changed |
| `sos` | Server→Client | SOS broadcast |

## Frontend Pages
1. **Overview (Home)**: Hero with particle canvas, feature grid, how-it-works, SOS section
2. **Command Center**: Leaflet map, KPI cards, incident list, AI triage feed, resource bars, volunteer list
3. **Report Crisis**: Crisis type picker, voice simulation (8 Indian languages), AI photo triage form
4. **Analytics**: Chart.js line/doughnut charts, Vertex AI predictions, AI stack metrics

## Key Design Decisions
- Same-origin API calls (no CORS needed)
- In-memory data store (intentional — demo-friendly)
- Live simulation background task generates events every 12–20 seconds
- C engine called via ctypes for nearest-unit routing (all dispatch & SOS calls)
- WebSocket reconnects automatically every 3s on disconnect
