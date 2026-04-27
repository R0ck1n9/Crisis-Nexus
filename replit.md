# CrisisNexus v2.0 — AI Crisis Response Platform

## Overview
India's AI-powered emergency response command platform. Submission-ready, fully interactive,
professional dark-UI built for production scale.

## Architecture

### Stack
| Layer | Technology |
|-------|-----------|
| Backend | Python 3 + FastAPI + uvicorn (WebSocket) |
| Geospatial | C shared library (geo_engine.so, GCC 14, -O2) via ctypes |
| Frontend | Single-page HTML/CSS/JS (no framework, ~2000 lines) |
| Real-time | WebSocket `/ws` + live simulation background task |
| Maps | Leaflet.js 1.9.4 + CartoDB Dark Matter tiles |
| Charts | Chart.js 4.4 (line, doughnut) |

### Files
```
main.py             FastAPI backend — REST API, WebSocket, C integration
geo_engine.c        Native C geospatial library source
geo_engine.so       Compiled shared library (GCC 14, -O2)
static/index.html   Complete professional frontend (~2200 lines)
replit.md           This file
```

### Run Command
```
uvicorn main:app --host 0.0.0.0 --port 5000
```

## Design System — "NEXUS COMMAND"
- **Typography**: Space Grotesk (display/headings), Inter (body), JetBrains Mono (data/labels)
- **Palette**: Deep navy base (#06090F→#182036), Crimson accent (#B91C1C), Emerald OK (#0D9968), Amber warn (#B45309), Blue info (#1D4ED8)
- **Icons**: Inline SVG sprite (16 custom icons, no external icon library)
- **Animations**: GPU-only (transform/opacity) — no layout reflow
- **Mobile**: Bottom tab nav at <768px, 44px+ touch targets, 16px min inputs

## Pages
1. **Overview (Home)**: Split hero with particle canvas + live WebSocket command panel; 8-feature grid; 4-step workflow; SOS ring; tech stack; footer
2. **Command Center**: Sidebar nav + main with KPI cards, Leaflet map, incident list (clickable detail panel), AI triage feed, resource bars, volunteer list with dispatch
3. **Report Crisis**: Type picker (6 types), language chips (8 languages), voice simulation, photo AI triage (calls /api/triage), full form, auto-dispatch submit
4. **Analytics**: 3 Chart.js charts, Vertex AI prediction cards, AI performance metrics

## C Geospatial Engine
Compiled: `gcc -shared -fPIC -O2 -o geo_engine.so geo_engine.c -lm`

Functions: haversine · find_nearest_unit · dispatch_score · estimate_eta_minutes · coverage_radius · batch_distances

Used for: every SOS alert, incident dispatch, volunteer routing

## REST API
```
GET  /api/health
GET  /api/incidents?status=&severity=
POST /api/incidents          (triggers C dispatch, AI triage)
GET  /api/incidents/{id}
PATCH /api/incidents/{id}/resolve
POST /api/triage             (AI severity classification)
GET  /api/resources
GET  /api/units
GET  /api/volunteers         (sorted by C haversine distance)
POST /api/volunteers/{id}/dispatch
POST /api/sos                (C engine nearest-unit routing)
GET  /api/stats
GET  /api/analytics/incidents-by-type
WS   /ws
```

## WebSocket Events
`init` · `new_incident` · `incident_resolved` · `incident_update` · `ticker` · `kpi_update` · `resource_update` · `sos`

## Key UX Features
- Incident detail slide panel (click any incident → 360px right panel with full data + resolve/map buttons)
- Live ticker auto-updates on new WebSocket events
- Map markers pulse for critical (P1) incidents
- Volunteer dispatch calls real `/api/volunteers/{id}/dispatch` endpoint
- SOS modal with GPS simulation + progress animation
- Toast notification system (top-right, auto-dismiss 5s)
- Scroll-reveal animations (IntersectionObserver, no layout recalc)
- Animated counter heroes on page load
- Sidebar status badges update in real time
