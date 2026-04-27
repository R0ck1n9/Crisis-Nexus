# CrisisNexus v3.0 — Live Crisis Response Platform

## Overview
Real-time, multi-user crisis coordination platform for Hyderabad, India.
Civilians submit reports; volunteers triage, dispatch, and resolve them.
Everything is broadcast live via WebSocket — no fake data, no demo simulation.

## Architecture
| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11 + FastAPI + uvicorn (WebSocket) |
| Geospatial | C shared library (`geo_engine.so`, GCC -O2) via ctypes |
| Frontend | Single-page HTML + vanilla JS (Leaflet, Chart.js) |
| Real-time | WebSocket `/ws` with role-based presence tracking |
| Maps | Leaflet + CARTO Dark tiles (free, no API key) |
| Geocoding | Nominatim (OpenStreetMap) for address search |
| Voice | Web Speech API (browser-native, English) |

## Files
```
main.py             FastAPI backend — REST + WebSocket + audit log
geo_engine.c/.so    Native C geospatial library (haversine, nearest, ETA)
static/index.html   Full SPA with role-based UI
```

## Roles
- **Civilian** — simple home with two cards: Report Incident and SOS
- **Volunteer / Manager** — full access: Overview, Command Center, Active Reports, Report, Analytics

Selected on first visit via onboarding modal; stored in localStorage.

## Live Features
- Real online presence count via WebSocket connections (no fake numbers)
- Reports created on any device appear instantly on every connected client
- SOS broadcasts caller's GPS location as a P1 incident with desktop notification
- Voice → text via browser SpeechRecognition (English, free, mic permission)
- Click-to-pin location picker in report form (or "use my location" / address search)
- Hyderabad emergency services pre-marked: hospitals, fire, police, ambulance hubs
- Fullscreen map toggle, recenter, service-layer toggle
- Incidents sorted P1 → P2 → P3, then by recency
- Volunteers can mark Dispatched (with units + note), Resolved, or Delete
- Audit log captures every action with actor + timestamp
- Charts (type, severity) update from real reports only
- Live ticker shows only real events (no fake messages, no emojis)

## REST API
```
GET  /api/health
GET  /api/services             list of Hyderabad emergency services
GET  /api/incidents?status=    sorted P1-first
POST /api/incidents            create report
POST /api/sos                  trigger SOS (auto P1)
GET  /api/incidents/{id}
POST /api/incidents/{id}/dispatch  mark dispatched (volunteer)
POST /api/incidents/{id}/resolve   mark resolved (volunteer)
DELETE /api/incidents/{id}         delete (volunteer)
GET  /api/audit                latest 200 audit entries
GET  /api/stats                live aggregate stats
GET  /api/presence             online users
WS   /ws?name=&role=
```

## Run
Workflow `Start application`:
```
uvicorn main:app --host 0.0.0.0 --port 5000
```
