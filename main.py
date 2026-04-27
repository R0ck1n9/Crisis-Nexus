"""
CrisisNexus — FastAPI Backend
Real-time crisis response platform with WebSocket live updates,
C-powered geospatial routing, and REST API.
"""

import asyncio
import ctypes
import json
import os
import random
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ══════════════════════════════════════════════════════════════
#  Load C Geospatial Engine
# ══════════════════════════════════════════════════════════════

_geo = None

def load_geo_engine():
    global _geo
    so_path = os.path.join(os.path.dirname(__file__), "geo_engine.so")
    if not os.path.exists(so_path):
        import subprocess
        subprocess.run(
            ["gcc", "-shared", "-fPIC", "-O2", "-o", so_path, "geo_engine.c", "-lm"],
            check=True
        )
    _geo = ctypes.CDLL(so_path)
    _geo.haversine.restype = ctypes.c_double
    _geo.haversine.argtypes = [ctypes.c_double, ctypes.c_double,
                                ctypes.c_double, ctypes.c_double]
    _geo.find_nearest_unit.restype = ctypes.c_int
    _geo.find_nearest_unit.argtypes = [
        ctypes.c_double, ctypes.c_double,
        ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double),
        ctypes.c_int
    ]
    _geo.dispatch_score.restype = ctypes.c_double
    _geo.dispatch_score.argtypes = [ctypes.c_double, ctypes.c_int, ctypes.c_double]
    _geo.estimate_eta_minutes.restype = ctypes.c_double
    _geo.estimate_eta_minutes.argtypes = [ctypes.c_double, ctypes.c_double]

load_geo_engine()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return _geo.haversine(lat1, lon1, lat2, lon2)


def find_nearest(inc_lat: float, inc_lon: float, units: list) -> int:
    """Use the C engine to find nearest available unit index."""
    n = len(units)
    if n == 0:
        return -1
    lats = (ctypes.c_double * n)(*[u["lat"] for u in units])
    lons = (ctypes.c_double * n)(*[u["lon"] for u in units])
    return _geo.find_nearest_unit(inc_lat, inc_lon, lats, lons, n)


def eta_minutes(distance_km: float, speed_kmh: float = 55.0) -> float:
    return _geo.estimate_eta_minutes(distance_km, speed_kmh)


# ══════════════════════════════════════════════════════════════
#  In-Memory Data Store
# ══════════════════════════════════════════════════════════════

# Hyderabad area coordinates for realistic simulation
HYD_CENTER = (17.3850, 78.4867)
ZONES = [
    {"name": "Banjara Hills",   "lat": 17.4156, "lon": 78.4347},
    {"name": "Secunderabad",    "lat": 17.4399, "lon": 78.4983},
    {"name": "Jubilee Hills",   "lat": 17.4253, "lon": 78.4074},
    {"name": "Hitec City",      "lat": 17.4435, "lon": 78.3772},
    {"name": "Gachibowli",      "lat": 17.4401, "lon": 78.3489},
    {"name": "Madhapur",        "lat": 17.4483, "lon": 78.3915},
    {"name": "Old City",        "lat": 17.3616, "lon": 78.4747},
    {"name": "Kukatpally",      "lat": 17.4849, "lon": 78.3995},
    {"name": "L B Nagar",       "lat": 17.3494, "lon": 78.5515},
    {"name": "Uppal",           "lat": 17.4040, "lon": 78.5590},
    {"name": "Begumpet",        "lat": 17.4438, "lon": 78.4710},
    {"name": "Ameerpet",        "lat": 17.4374, "lon": 78.4487},
]

CRISIS_TYPES = [
    {"type": "Flood",        "icon": "🌊", "color": "#2979FF"},
    {"type": "Fire",         "icon": "🔥", "color": "#FF6B35"},
    {"type": "Collapse",     "icon": "🏚️", "color": "#FF3B30"},
    {"type": "Accident",     "icon": "🚗", "color": "#FFB800"},
    {"type": "Gas Leak",     "icon": "☁️", "color": "#9B6DFF"},
    {"type": "Medical",      "icon": "🏥", "color": "#00D4AA"},
    {"type": "Explosion",    "icon": "💥", "color": "#FF3B30"},
    {"type": "Landslide",    "icon": "⛰️", "color": "#8B5E3C"},
]

UNIT_POOL = [
    {"id": "AMB-01", "type": "ambulance",  "icon": "🚑", "lat": 17.410, "lon": 78.430, "load": 0.4, "status": "available"},
    {"id": "AMB-02", "type": "ambulance",  "icon": "🚑", "lat": 17.445, "lon": 78.490, "load": 0.7, "status": "busy"},
    {"id": "AMB-03", "type": "ambulance",  "icon": "🚑", "lat": 17.360, "lon": 78.475, "load": 0.2, "status": "available"},
    {"id": "AMB-04", "type": "ambulance",  "icon": "🚑", "lat": 17.485, "lon": 78.395, "load": 0.0, "status": "available"},
    {"id": "FIRE-01","type": "fire",       "icon": "🚒", "lat": 17.425, "lon": 78.450, "load": 0.5, "status": "available"},
    {"id": "FIRE-02","type": "fire",       "icon": "🚒", "lat": 17.440, "lon": 78.380, "load": 0.1, "status": "available"},
    {"id": "FIRE-03","type": "fire",       "icon": "🚒", "lat": 17.350, "lon": 78.510, "load": 0.9, "status": "busy"},
    {"id": "NDRF-01","type": "rescue",     "icon": "🚁", "lat": 17.460, "lon": 78.420, "load": 0.3, "status": "available"},
    {"id": "NDRF-02","type": "rescue",     "icon": "🚁", "lat": 17.390, "lon": 78.460, "load": 0.6, "status": "available"},
    {"id": "HOSP-A", "type": "hospital",   "icon": "🏥", "lat": 17.433, "lon": 78.448, "load": 0.88, "status": "partial"},
    {"id": "HOSP-B", "type": "hospital",   "icon": "🏥", "lat": 17.415, "lon": 78.472, "load": 0.60, "status": "available"},
    {"id": "HOSP-C", "type": "hospital",   "icon": "🏥", "lat": 17.350, "lon": 78.470, "load": 0.45, "status": "available"},
]

VOLUNTEERS = [
    {"id": "V001", "name": "Dr. Priya Sharma",   "avatar": "👨‍⚕️", "skill": "Emergency Medicine",    "years": 8,  "lat": 17.412, "lon": 78.432, "status": "online",   "lang": ["Telugu", "English"]},
    {"id": "V002", "name": "Ravi Kumar",          "avatar": "👷",  "skill": "Structural Engineer",    "years": 12, "lat": 17.445, "lon": 78.495, "status": "online",   "lang": ["Telugu", "Hindi"]},
    {"id": "V003", "name": "Ananya Reddy",        "avatar": "🚑",  "skill": "Paramedic",               "years": 5,  "lat": 17.425, "lon": 78.430, "status": "enroute",  "lang": ["Telugu", "English"]},
    {"id": "V004", "name": "Mohammed Ali",        "avatar": "🧑‍💻", "skill": "Logistics Coordinator",   "years": 7,  "lat": 17.448, "lon": 78.398, "status": "online",   "lang": ["Urdu", "Telugu"]},
    {"id": "V005", "name": "Lakshmi Devi",        "avatar": "👩‍🔬", "skill": "Nurse",                   "years": 9,  "lat": 17.418, "lon": 78.442, "status": "online",   "lang": ["Telugu", "Hindi"]},
    {"id": "V006", "name": "Arjun Nair",          "avatar": "🧑‍🚒", "skill": "Search & Rescue",        "years": 6,  "lat": 17.435, "lon": 78.410, "status": "online",   "lang": ["Malayalam", "English"]},
    {"id": "V007", "name": "Sunita Patel",        "avatar": "👩‍⚕️", "skill": "Trauma Surgeon",         "years": 15, "lat": 17.402, "lon": 78.458, "status": "standby",  "lang": ["Hindi", "English"]},
    {"id": "V008", "name": "Karthik Reddy",       "avatar": "👷",  "skill": "Civil Engineer",          "years": 10, "lat": 17.455, "lon": 78.375, "status": "online",   "lang": ["Telugu", "Kannada"]},
]

# Active incidents — seeded with realistic data
incidents: List[Dict] = [
    {
        "id": "INC-2026-0001",
        "type": "Flood",
        "icon": "🌊",
        "severity": "P1",
        "location": "Banjara Hills, Road No. 12",
        "lat": 17.4156, "lon": 78.4347,
        "description": "Flash flood with waist-deep water. 6 persons stranded on rooftop. Electrical hazard.",
        "casualties": 6,
        "status": "active",
        "dispatched_units": ["AMB-01", "NDRF-01"],
        "eta_minutes": 4.2,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ai_confidence": 94.2,
        "hazards": ["Electrical", "Drowning"],
        "rescue_type": "Boat + Paramedics",
    },
    {
        "id": "INC-2026-0002",
        "type": "Collapse",
        "icon": "🏚️",
        "severity": "P1",
        "location": "Secunderabad, SP Road",
        "lat": 17.4399, "lon": 78.4983,
        "description": "Partial 3-floor collapse. Estimated 2–4 trapped under debris. Shoring required.",
        "casualties": 4,
        "status": "active",
        "dispatched_units": ["FIRE-01", "NDRF-02", "AMB-02"],
        "eta_minutes": 6.8,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ai_confidence": 87.1,
        "hazards": ["Structural instability", "Gas leak possible"],
        "rescue_type": "Heavy Rescue + Shoring",
    },
    {
        "id": "INC-2026-0003",
        "type": "Gas Leak",
        "icon": "☁️",
        "severity": "P2",
        "location": "Jubilee Hills, Film Nagar",
        "lat": 17.4253, "lon": 78.4074,
        "description": "Industrial gas leak. 200m exclusion zone established. Evacuation in progress.",
        "casualties": 0,
        "status": "active",
        "dispatched_units": ["FIRE-02"],
        "eta_minutes": 3.1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ai_confidence": 91.8,
        "hazards": ["Toxic gas", "Explosion risk"],
        "rescue_type": "HAZMAT Team",
    },
    {
        "id": "INC-2026-0004",
        "type": "Medical",
        "icon": "🏥",
        "severity": "P2",
        "location": "Hitec City, Gachibowli",
        "lat": 17.4435, "lon": 78.3772,
        "description": "Mass casualty incident. 12 patients triaged: 3 Critical, 5 Serious, 4 Minor.",
        "casualties": 12,
        "status": "active",
        "dispatched_units": ["AMB-03", "AMB-04"],
        "eta_minutes": 8.4,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ai_confidence": 89.5,
        "hazards": ["Mass casualty"],
        "rescue_type": "Multiple Ambulances",
    },
    {
        "id": "INC-2026-0005",
        "type": "Accident",
        "icon": "🚗",
        "severity": "P3",
        "location": "Old City, Charminar",
        "lat": 17.3616, "lon": 78.4747,
        "description": "Multi-vehicle collision. 2 injured, road blocked. Crowd control needed.",
        "casualties": 2,
        "status": "resolved",
        "dispatched_units": [],
        "eta_minutes": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ai_confidence": 97.3,
        "hazards": ["Traffic blockage"],
        "rescue_type": "Traffic Police + Ambulance",
    },
]

resources: Dict[str, Dict] = {
    "ambulances":    {"total": 24, "deployed": 17, "pct": 72,  "trend": +3,  "status": "warning"},
    "fire_units":    {"total": 12, "deployed": 5,  "pct": 42,  "trend": 0,   "status": "ok"},
    "hospital_beds": {"total": 450, "deployed": 396, "pct": 88, "trend": +12, "status": "critical"},
    "blood_supply":  {"total": 200, "deployed": 62, "pct": 31,  "trend": -8,  "status": "ok"},
    "rescue_teams":  {"total": 8,  "deployed": 5,  "pct": 62,  "trend": +1,  "status": "warning"},
    "ndrf_units":    {"total": 4,  "deployed": 2,  "pct": 50,  "trend": 0,   "status": "ok"},
}

stats_history = {
    "incidents_per_hour": [12, 8, 15, 22, 18, 31, 24, 19, 27, 33, 29, 41],
    "response_times":     [6.2, 5.8, 5.1, 4.9, 4.7, 4.4, 4.3, 4.2, 4.1, 4.2, 4.1, 4.2],
    "ai_triage_speed":    [3.1, 2.9, 2.8, 2.6, 2.5, 2.4, 2.4, 2.3, 2.3, 2.3, 2.3, 2.3],
    "labels": ["1h", "2h", "3h", "4h", "5h", "6h", "7h", "8h", "9h", "10h", "11h", "12h"],
}

# ══════════════════════════════════════════════════════════════
#  Pydantic Models
# ══════════════════════════════════════════════════════════════

class IncidentCreate(BaseModel):
    type: str
    location: str
    lat: Optional[float] = HYD_CENTER[0]
    lon: Optional[float] = HYD_CENTER[1]
    severity: Optional[str] = "P2"
    description: str
    casualties: Optional[int] = 0
    contact: Optional[str] = ""

class TriageRequest(BaseModel):
    crisis_type: str
    description: str
    casualties: int = 0
    location: str = ""

class SOSRequest(BaseModel):
    lat: float
    lon: float
    message: Optional[str] = "Emergency SOS"

class VolunteerDispatch(BaseModel):
    incident_id: str

# ══════════════════════════════════════════════════════════════
#  WebSocket Connection Manager
# ══════════════════════════════════════════════════════════════

class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active_connections.discard(ws)

    async def broadcast(self, data: dict):
        dead = set()
        msg = json.dumps(data)
        for ws in self.active_connections:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.active_connections.discard(ws)

    @property
    def count(self) -> int:
        return len(self.active_connections)


manager = ConnectionManager()

# ══════════════════════════════════════════════════════════════
#  Background Live Simulation
# ══════════════════════════════════════════════════════════════

_sim_running = False

async def live_simulation():
    """Generates realistic live events and broadcasts via WebSocket."""
    global _sim_running
    _sim_running = True
    inc_counter = len(incidents) + 1
    ticker_msgs = [
        "🌊 Water level rising in Madhapur — monitoring active",
        "🚑 Ambulance AMB-02 arrived at Secunderabad collapse site",
        "🔮 Vertex AI: Hospital bed shortage predicted in 32 minutes",
        "📡 Offline mesh sync: 7 new reports received from Kukatpally",
        "✅ Gas leak in Jubilee Hills — HAZMAT team on scene",
        "🚁 NDRF-01 conducting aerial assessment over Banjara Hills",
        "⚡ Vertex AI: Secondary flooding risk elevated in Gachibowli",
        "🏥 NIMS Hospital: 18 beds pre-allocated for incoming casualties",
        "🤖 Gemini Vision processed 3 new scene photos — avg 2.1s",
        "👥 12 volunteers auto-matched to active incident zones",
        "🩸 Blood supply: O+ve requisition sent to 3 donor banks",
        "📱 SOS received — GPS lock acquired, unit dispatched",
    ]
    ticker_idx = 0

    while _sim_running:
        await asyncio.sleep(random.uniform(12, 20))

        event_type = random.choices(
            ["ticker", "incident_update", "kpi_update", "new_incident", "resource_update"],
            weights=[40, 25, 20, 8, 7]
        )[0]

        if event_type == "ticker":
            msg = ticker_msgs[ticker_idx % len(ticker_msgs)]
            ticker_idx += 1
            await manager.broadcast({"type": "ticker", "message": msg, "ts": _ts()})

        elif event_type == "kpi_update":
            await manager.broadcast({
                "type": "kpi_update",
                "data": {
                    "active_incidents": len([i for i in incidents if i["status"] == "active"]),
                    "avg_response_time": round(random.uniform(3.8, 4.8), 1),
                    "triage_speed": round(random.uniform(2.1, 2.5), 1),
                    "volunteers_online": random.randint(43, 52),
                    "clients_connected": manager.count,
                },
                "ts": _ts()
            })

        elif event_type == "resource_update":
            key = random.choice(list(resources.keys()))
            resources[key]["pct"] = max(5, min(98, resources[key]["pct"] + random.randint(-3, 3)))
            await manager.broadcast({"type": "resource_update", "resource": key, "data": resources[key], "ts": _ts()})

        elif event_type == "incident_update" and incidents:
            inc = random.choice(incidents)
            if inc["status"] == "active" and random.random() > 0.7:
                inc["status"] = "resolved"
                await manager.broadcast({"type": "incident_resolved", "id": inc["id"], "location": inc["location"], "ts": _ts()})
            else:
                await manager.broadcast({"type": "incident_update", "incident": inc, "ts": _ts()})

        elif event_type == "new_incident":
            zone = random.choice(ZONES)
            ctype = random.choice(CRISIS_TYPES)
            sev = random.choices(["P1", "P2", "P3"], weights=[30, 45, 25])[0]
            cas = random.randint(0, 8) if sev == "P1" else random.randint(0, 3)

            # Use C engine to find nearest unit
            avail = [u for u in UNIT_POOL if u["status"] == "available"]
            nearest_idx = find_nearest(zone["lat"], zone["lon"], avail) if avail else -1
            nearest_unit = avail[nearest_idx]["id"] if nearest_idx >= 0 else None
            dist = haversine_km(zone["lat"], zone["lon"],
                                avail[nearest_idx]["lat"], avail[nearest_idx]["lon"]) if nearest_idx >= 0 else 5.0
            eta = eta_minutes(dist)

            new_inc = {
                "id": f"INC-2026-{inc_counter:04d}",
                "type": ctype["type"],
                "icon": ctype["icon"],
                "severity": sev,
                "location": f"{zone['name']}",
                "lat": zone["lat"] + random.uniform(-0.01, 0.01),
                "lon": zone["lon"] + random.uniform(-0.01, 0.01),
                "description": f"{ctype['type']} incident reported in {zone['name']}.",
                "casualties": cas,
                "status": "active",
                "dispatched_units": [nearest_unit] if nearest_unit else [],
                "eta_minutes": round(eta, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ai_confidence": round(random.uniform(82, 97), 1),
                "hazards": [],
                "rescue_type": "Pending AI Analysis",
            }
            incidents.append(new_inc)
            inc_counter += 1
            await manager.broadcast({"type": "new_incident", "incident": new_inc, "ts": _ts()})


def _ts():
    return datetime.now(timezone.utc).isoformat()


# ══════════════════════════════════════════════════════════════
#  AI Triage Simulation
# ══════════════════════════════════════════════════════════════

TRIAGE_PROFILES = {
    "Flood":    {"severity": "P1", "hazards": ["Drowning", "Electrical"], "rescue": "Boat + Paramedics", "conf": (88, 97)},
    "Fire":     {"severity": "P1", "hazards": ["Burns", "Smoke inhalation"], "rescue": "Fire Unit + Medics", "conf": (85, 96)},
    "Collapse": {"severity": "P1", "hazards": ["Structural instability", "Dust"], "rescue": "Heavy Rescue", "conf": (80, 93)},
    "Accident": {"severity": "P2", "hazards": ["Trauma", "Traffic"], "rescue": "Ambulance", "conf": (90, 99)},
    "Gas Leak": {"severity": "P2", "hazards": ["Toxic gas", "Explosion"], "rescue": "HAZMAT Team", "conf": (83, 95)},
    "Medical":  {"severity": "P2", "hazards": ["Mass casualty"], "rescue": "Multi-Ambulance", "conf": (88, 98)},
    "Explosion":{"severity": "P1", "hazards": ["Blast", "Fire", "Debris"], "rescue": "NDRF + Medics", "conf": (82, 94)},
    "Landslide":{"severity": "P1", "hazards": ["Buried", "Secondary slide"], "rescue": "NDRF + Excavation", "conf": (79, 92)},
}

def ai_triage(crisis_type: str, description: str, casualties: int) -> dict:
    profile = TRIAGE_PROFILES.get(crisis_type, TRIAGE_PROFILES["Medical"])
    conf = round(random.uniform(*profile["conf"]), 1)
    sev = profile["severity"]
    if casualties > 8:
        sev = "P1"
    elif casualties == 0 and sev == "P1":
        sev = "P2"
    return {
        "severity": sev,
        "hazards": profile["hazards"],
        "rescue_type": profile["rescue"],
        "confidence": conf,
        "casualties_estimated": casualties,
        "processing_time_ms": random.randint(1800, 2900),
        "model": "Gemini 1.5 Pro Vision",
    }


# ══════════════════════════════════════════════════════════════
#  FastAPI Application
# ══════════════════════════════════════════════════════════════

app = FastAPI(title="CrisisNexus API", version="2.0.0")


@app.on_event("startup")
async def startup():
    asyncio.create_task(live_simulation())


# Serve static files
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=FileResponse)
async def index():
    return FileResponse("static/index.html")


# ── Health ──
@app.get("/api/health")
async def health():
    return {
        "status": "operational",
        "version": "2.0.0",
        "geo_engine": "C/ctypes active",
        "ws_clients": manager.count,
        "uptime_s": int(time.time()),
    }


# ── Incidents ──
@app.get("/api/incidents")
async def get_incidents(status: Optional[str] = None, severity: Optional[str] = None):
    result = incidents
    if status:
        result = [i for i in result if i["status"] == status]
    if severity:
        result = [i for i in result if i["severity"] == severity]
    return {"incidents": result, "total": len(result)}


@app.post("/api/incidents", status_code=201)
async def create_incident(body: IncidentCreate):
    ctype = next((c for c in CRISIS_TYPES if c["type"] == body.type), CRISIS_TYPES[0])

    # C engine: find nearest available unit
    avail = [u for u in UNIT_POOL if u["status"] == "available"]
    nearest_idx = find_nearest(body.lat, body.lon, avail)
    nearest_unit = avail[nearest_idx] if nearest_idx >= 0 else None
    dist = haversine_km(body.lat, body.lon,
                        nearest_unit["lat"], nearest_unit["lon"]) if nearest_unit else 5.0
    eta = round(eta_minutes(dist), 1)

    # AI triage
    triage = ai_triage(body.type, body.description, body.casualties)

    new_inc = {
        "id": f"INC-2026-{len(incidents)+1:04d}",
        "type": body.type,
        "icon": ctype["icon"],
        "severity": triage["severity"],
        "location": body.location,
        "lat": body.lat,
        "lon": body.lon,
        "description": body.description,
        "casualties": body.casualties,
        "status": "active",
        "dispatched_units": [nearest_unit["id"]] if nearest_unit else [],
        "eta_minutes": eta,
        "timestamp": _ts(),
        "ai_confidence": triage["confidence"],
        "hazards": triage["hazards"],
        "rescue_type": triage["rescue_type"],
        "contact": body.contact,
    }
    incidents.append(new_inc)

    await manager.broadcast({"type": "new_incident", "incident": new_inc, "ts": _ts()})
    await manager.broadcast({"type": "ticker", "message": f"🚨 New {body.type} incident reported — {body.location} ({triage['severity']})", "ts": _ts()})

    return {"incident": new_inc, "triage": triage,
            "nearest_unit": nearest_unit, "eta_minutes": eta}


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = next((i for i in incidents if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    return inc


@app.patch("/api/incidents/{incident_id}/resolve")
async def resolve_incident(incident_id: str):
    inc = next((i for i in incidents if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    inc["status"] = "resolved"
    await manager.broadcast({"type": "incident_resolved", "id": incident_id, "location": inc["location"], "ts": _ts()})
    return {"status": "resolved", "id": incident_id}


# ── Triage ──
@app.post("/api/triage")
async def triage_endpoint(body: TriageRequest):
    await asyncio.sleep(random.uniform(1.8, 2.9))  # simulate processing time
    result = ai_triage(body.crisis_type, body.description, body.casualties)
    return result


# ── Resources ──
@app.get("/api/resources")
async def get_resources():
    return {"resources": resources}


# ── Units ──
@app.get("/api/units")
async def get_units():
    return {"units": UNIT_POOL}


# ── Volunteers ──
@app.get("/api/volunteers")
async def get_volunteers():
    vols = []
    for v in VOLUNTEERS:
        # C engine: compute distance from HYD center (commander's position)
        dist = haversine_km(HYD_CENTER[0], HYD_CENTER[1], v["lat"], v["lon"])
        vols.append({**v, "distance_km": round(dist, 2)})
    vols.sort(key=lambda x: x["distance_km"])
    return {"volunteers": vols}


@app.post("/api/volunteers/{vol_id}/dispatch")
async def dispatch_volunteer(vol_id: str, body: VolunteerDispatch):
    vol = next((v for v in VOLUNTEERS if v["id"] == vol_id), None)
    if not vol:
        raise HTTPException(404, "Volunteer not found")
    inc = next((i for i in incidents if i["id"] == body.incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")

    dist = haversine_km(vol["lat"], vol["lon"], inc["lat"], inc["lon"])
    eta = round(eta_minutes(dist), 1)
    vol["status"] = "enroute"

    await manager.broadcast({
        "type": "ticker",
        "message": f"👤 {vol['name']} dispatched → {inc['location']} (ETA {eta:.0f} min)",
        "ts": _ts()
    })
    return {"dispatched": True, "volunteer": vol["name"], "eta_minutes": eta, "distance_km": round(dist, 2)}


# ── SOS ──
@app.post("/api/sos")
async def sos_endpoint(body: SOSRequest):
    # C engine: find nearest unit to SOS location
    avail = [u for u in UNIT_POOL if u["status"] == "available"]
    nearest_idx = find_nearest(body.lat, body.lon, avail)
    nearest = avail[nearest_idx] if nearest_idx >= 0 else None
    dist = haversine_km(body.lat, body.lon,
                        nearest["lat"], nearest["lon"]) if nearest else 3.0
    eta = round(eta_minutes(dist), 1)

    sos_id = f"SOS-{uuid.uuid4().hex[:6].upper()}"

    if nearest:
        nearest["status"] = "dispatched"

    await manager.broadcast({
        "type": "sos",
        "sos_id": sos_id,
        "lat": body.lat,
        "lon": body.lon,
        "message": body.message,
        "nearest_unit": nearest["id"] if nearest else None,
        "eta_minutes": eta,
        "ts": _ts()
    })
    await manager.broadcast({
        "type": "ticker",
        "message": f"🆘 SOS ALERT — GPS confirmed. {nearest['id'] if nearest else 'Unit'} dispatched. ETA {eta:.0f} min.",
        "ts": _ts()
    })

    return {"sos_id": sos_id, "eta_minutes": eta, "nearest_unit": nearest, "status": "transmitted"}


# ── Stats ──
@app.get("/api/stats")
async def get_stats():
    active = [i for i in incidents if i["status"] == "active"]
    return {
        "active_incidents": len(active),
        "critical_p1": len([i for i in active if i["severity"] == "P1"]),
        "total_casualties": sum(i["casualties"] for i in active),
        "avg_response_time": 4.2,
        "ai_triage_speed": 2.3,
        "volunteers_online": len([v for v in VOLUNTEERS if v["status"] == "online"]),
        "volunteers_enroute": len([v for v in VOLUNTEERS if v["status"] == "enroute"]),
        "ws_clients": manager.count,
        "prediction_accuracy": 91.0,
        "lives_assisted": 1240,
        "offline_synced": 183,
        "history": stats_history,
    }


# ── Analytics ──
@app.get("/api/analytics/incidents-by-type")
async def incidents_by_type():
    type_counts = {}
    for inc in incidents:
        type_counts[inc["type"]] = type_counts.get(inc["type"], 0) + 1
    return type_counts


# ── WebSocket ──
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send initial state
        await ws.send_text(json.dumps({
            "type": "init",
            "incidents": incidents,
            "resources": resources,
            "volunteers": VOLUNTEERS,
            "stats": {
                "active_incidents": len([i for i in incidents if i["status"] == "active"]),
                "ws_clients": manager.count,
            },
            "ts": _ts()
        }))
        while True:
            await ws.receive_text()  # keep alive
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ══════════════════════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=5000, reload=False)
