"""
CrisisNexus — FastAPI Backend (real-time, multi-user, role-based)
- No fake data. Only real reports submitted by users.
- Roles: volunteer (manager) and civilian (reporter).
- Live online presence via WebSocket connections.
- C-powered geospatial routing for nearest unit.
"""

import asyncio
import ctypes
import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

# ──────────────────────────────────────────────
#  C Geospatial Engine (with pure-Python fallback)
# ──────────────────────────────────────────────
import math as _math

_geo = None
_use_native = False

def _py_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371.0
    dlat = _math.radians(lat2 - lat1)
    dlon = _math.radians(lon2 - lon1)
    a = (_math.sin(dlat / 2) ** 2
         + _math.cos(_math.radians(lat1)) * _math.cos(_math.radians(lat2))
         * _math.sin(dlon / 2) ** 2)
    return R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1 - a))

def _py_find_nearest(inc_lat: float, inc_lon: float, lats: list, lons: list) -> int:
    best, best_d = -1, float("inf")
    for i, (la, lo) in enumerate(zip(lats, lons)):
        d = _py_haversine(inc_lat, inc_lon, la, lo)
        if d < best_d:
            best_d, best = d, i
    return best

def _py_eta(distance_km: float, speed_kmh: float) -> float:
    if speed_kmh <= 0:
        return 0.0
    return (distance_km / speed_kmh) * 60.0


def load_geo_engine():
    global _geo, _use_native
    import platform, shutil
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if platform.system() == "Windows":
        lib_name = "geo_engine.dll"
        compile_cmd = ["gcc", "-shared", "-O2", "-o",
                       os.path.join(base_dir, lib_name),
                       os.path.join(base_dir, "geo_engine.c")]
    else:
        lib_name = "geo_engine.so"
        compile_cmd = ["gcc", "-shared", "-fPIC", "-O2", "-o",
                       os.path.join(base_dir, lib_name),
                       os.path.join(base_dir, "geo_engine.c"), "-lm"]
    so_path = os.path.join(base_dir, lib_name)
    # Try to compile only if gcc is available
    if not os.path.exists(so_path):
        if shutil.which("gcc") is None:
            print("[geo_engine] gcc not found — using pure-Python fallback")
            return
        import subprocess
        subprocess.run(compile_cmd, check=True)
    try:
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
        _geo.estimate_eta_minutes.restype = ctypes.c_double
        _geo.estimate_eta_minutes.argtypes = [ctypes.c_double, ctypes.c_double]
        _use_native = True
        print("[geo_engine] native C library loaded")
    except OSError as exc:
        print(f"[geo_engine] failed to load .so/.dll ({exc}) — using pure-Python fallback")

load_geo_engine()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    if _use_native:
        return _geo.haversine(lat1, lon1, lat2, lon2)
    return _py_haversine(lat1, lon1, lat2, lon2)


def find_nearest(inc_lat: float, inc_lon: float, units: list) -> int:
    n = len(units)
    if n == 0:
        return -1
    if _use_native:
        lats = (ctypes.c_double * n)(*[u["lat"] for u in units])
        lons = (ctypes.c_double * n)(*[u["lon"] for u in units])
        return _geo.find_nearest_unit(inc_lat, inc_lon, lats, lons, n)
    return _py_find_nearest(inc_lat, inc_lon,
                            [u["lat"] for u in units],
                            [u["lon"] for u in units])


# Average urban speeds (km/h) for different responders in Hyderabad traffic
RESPONSE_SPEED = {
    "police": 55.0,      # patrol cars are quick on sirens
    "ambulance": 50.0,   # 108 with sirens
    "fire": 40.0,        # heavier vehicles, slower
    "hospital": 45.0,
}


def eta_minutes(distance_km: float, speed_kmh: float = 45.0) -> float:
    if _use_native:
        return _geo.estimate_eta_minutes(distance_km, speed_kmh)
    return _py_eta(distance_km, speed_kmh)


def nearest_of_type(lat: float, lon: float, svc_type: str) -> Optional[Dict[str, Any]]:
    """Return the nearest service of the given type with distance and ETA."""
    pool = [s for s in EMERGENCY_SERVICES if s["type"] == svc_type]
    if not pool:
        return None
    idx = find_nearest(lat, lon, pool)
    if idx < 0:
        return None
    s = pool[idx]
    dist = haversine_km(lat, lon, s["lat"], s["lon"])
    speed = RESPONSE_SPEED.get(svc_type, 45.0)
    return {
        "id": s["id"],
        "name": s["name"],
        "type": s["type"],
        "lat": s["lat"],
        "lon": s["lon"],
        "distance_km": round(dist, 2),
        "eta_min": round(eta_minutes(dist, speed), 1),
        "speed_kmh": speed,
    }


def nearest_by_all_types(lat: float, lon: float) -> Dict[str, Any]:
    return {
        "police":    nearest_of_type(lat, lon, "police"),
        "fire":      nearest_of_type(lat, lon, "fire"),
        "ambulance": nearest_of_type(lat, lon, "ambulance"),
        "hospital":  nearest_of_type(lat, lon, "hospital"),
    }


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


# ──────────────────────────────────────────────
#  Hyderabad Emergency Services (real coordinates)
# ──────────────────────────────────────────────
EMERGENCY_SERVICES = [
    # Hospitals
    {"id": "HOSP-NIMS",   "name": "NIMS Hospital",                "type": "hospital", "lat": 17.4239, "lon": 78.4502},
    {"id": "HOSP-APOLLO", "name": "Apollo Hospital Jubilee Hills","type": "hospital", "lat": 17.4126, "lon": 78.4071},
    {"id": "HOSP-CARE",   "name": "CARE Hospital Banjara Hills",  "type": "hospital", "lat": 17.4202, "lon": 78.4471},
    {"id": "HOSP-YASHODA","name": "Yashoda Hospital Secunderabad","type": "hospital", "lat": 17.4426, "lon": 78.4892},
    {"id": "HOSP-KIMS",   "name": "KIMS Hospital Kondapur",       "type": "hospital", "lat": 17.4677, "lon": 78.3624},
    {"id": "HOSP-CONTL",  "name": "Continental Hospital",         "type": "hospital", "lat": 17.4178, "lon": 78.3499},
    {"id": "HOSP-OSMA",   "name": "Osmania General Hospital",     "type": "hospital", "lat": 17.3713, "lon": 78.4731},
    {"id": "HOSP-GANDHI", "name": "Gandhi Hospital",              "type": "hospital", "lat": 17.4544, "lon": 78.4994},
    # Fire stations
    {"id": "FIRE-SECBAD", "name": "Secunderabad Fire Station",    "type": "fire",     "lat": 17.4399, "lon": 78.4983},
    {"id": "FIRE-BANJ",   "name": "Banjara Hills Fire Station",   "type": "fire",     "lat": 17.4156, "lon": 78.4347},
    {"id": "FIRE-GACH",   "name": "Gachibowli Fire Station",      "type": "fire",     "lat": 17.4400, "lon": 78.3489},
    {"id": "FIRE-OLDC",   "name": "Old City Fire Station",        "type": "fire",     "lat": 17.3616, "lon": 78.4747},
    {"id": "FIRE-KUKA",   "name": "Kukatpally Fire Station",      "type": "fire",     "lat": 17.4849, "lon": 78.3995},
    # Police
    {"id": "POL-CYBER",   "name": "Cyberabad Police HQ",          "type": "police",   "lat": 17.4474, "lon": 78.3762},
    {"id": "POL-COMM",    "name": "Hyderabad Police Commissionerate","type": "police","lat": 17.4055, "lon": 78.4748},
    {"id": "POL-BANJ",    "name": "Banjara Hills Police Station", "type": "police",   "lat": 17.4126, "lon": 78.4292},
    {"id": "POL-SEC",     "name": "Secunderabad Police Station",  "type": "police",   "lat": 17.4398, "lon": 78.4983},
    {"id": "POL-MAD",     "name": "Madhapur Police Station",      "type": "police",   "lat": 17.4483, "lon": 78.3915},
    # Ambulance dispatch hubs
    {"id": "AMB-CENTRAL", "name": "108 Ambulance Central",        "type": "ambulance","lat": 17.3850, "lon": 78.4867},
    {"id": "AMB-WEST",    "name": "108 Ambulance West Hub",       "type": "ambulance","lat": 17.4435, "lon": 78.3772},
    {"id": "AMB-EAST",    "name": "108 Ambulance East Hub",       "type": "ambulance","lat": 17.4040, "lon": 78.5590},
    {"id": "AMB-NORTH",   "name": "108 Ambulance North Hub",      "type": "ambulance","lat": 17.4849, "lon": 78.3995},
]

CRISIS_TYPES = ["Flood", "Fire", "Collapse", "Accident", "Gas Leak", "Medical", "Explosion", "Landslide", "Other"]
SEVERITY_RANK = {"P1": 0, "P2": 1, "P3": 2}


# ──────────────────────────────────────────────
#  In-memory stores
# ──────────────────────────────────────────────
incidents: List[Dict] = []
audit_log: List[Dict] = []
_inc_counter = 0


# ──────────────────────────────────────────────
#  Pydantic models
# ──────────────────────────────────────────────
class IncidentCreate(BaseModel):
    type: str
    location: str = Field(max_length=200)
    lat: float
    lon: float
    description: str = Field(default="", max_length=1000)
    casualties: int = Field(default=0, ge=0, le=10000)
    contact: str = Field(default="", max_length=100)
    photo_data_url: Optional[str] = None  # validated below
    reporter_name: str = Field(default="Anonymous", max_length=80)
    reporter_role: str = "civilian"

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in CRISIS_TYPES:
            raise ValueError(f"type must be one of {CRISIS_TYPES}")
        return v

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("lon must be between -180 and 180")
        return v

    @field_validator("reporter_role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        if v not in ("volunteer", "civilian"):
            return "civilian"
        return v

    @field_validator("photo_data_url")
    @classmethod
    def validate_photo(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 2_097_152:  # ~1.5 MB binary limit
            raise ValueError("photo_data_url exceeds 2 MB limit")
        return v


class SOSRequest(BaseModel):
    lat: float
    lon: float
    reporter_name: str = Field(default="Anonymous", max_length=80)

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not (-90.0 <= v <= 90.0):
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not (-180.0 <= v <= 180.0):
            raise ValueError("lon must be between -180 and 180")
        return v


class DispatchUnitOrder(BaseModel):
    type: str  # 'police' | 'fire' | 'ambulance' | 'hospital'
    count: int = 1


class DispatchRequest(BaseModel):
    orders: List[DispatchUnitOrder] = []
    note: str = Field(default="", max_length=500)
    actor_name: str = Field(default="Unknown", max_length=80)


class ResolveRequest(BaseModel):
    actor_name: str = Field(default="Unknown", max_length=80)
    note: str = Field(default="", max_length=500)


class SessionRegister(BaseModel):
    name: str
    role: str  # 'volunteer' or 'civilian'


# ──────────────────────────────────────────────
#  Connection / Presence Manager
# ──────────────────────────────────────────────
class ConnectionManager:
    def __init__(self):
        self.connections: Dict[str, Dict[str, Any]] = {}  # client_id -> {ws, name, role}

    async def connect(self, ws: WebSocket, client_id: str, name: str, role: str):
        await ws.accept()
        self.connections[client_id] = {"ws": ws, "name": name, "role": role}

    def disconnect(self, client_id: str):
        self.connections.pop(client_id, None)

    async def broadcast(self, data: dict):
        msg = json.dumps(data)
        dead = []
        for cid, conn in self.connections.items():
            try:
                await conn["ws"].send_text(msg)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self.connections.pop(cid, None)

    @property
    def total(self) -> int:
        return len(self.connections)

    def volunteers_online(self) -> List[Dict[str, str]]:
        return [
            {"name": c["name"], "id": cid}
            for cid, c in self.connections.items()
            if c["role"] == "volunteer"
        ]

    def civilians_online(self) -> int:
        return sum(1 for c in self.connections.values() if c["role"] == "civilian")


manager = ConnectionManager()


# ──────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────
def severity_from(crisis_type: str, casualties: int, is_sos: bool) -> str:
    if is_sos:
        return "P1"
    if crisis_type in ("Fire", "Collapse", "Explosion", "Landslide", "Flood"):
        return "P1" if casualties >= 1 else "P2"
    if crisis_type in ("Gas Leak", "Medical"):
        return "P1" if casualties >= 3 else "P2"
    return "P2" if casualties > 0 else "P3"


def sort_incidents(items: List[Dict]) -> List[Dict]:
    return sorted(
        items,
        key=lambda i: (SEVERITY_RANK.get(i["severity"], 9), i["timestamp"]),
    )


def add_audit(action: str, incident_id: str, actor: str, detail: str = ""):
    entry = {
        "id": f"AUD-{uuid.uuid4().hex[:8].upper()}",
        "action": action,
        "incident_id": incident_id,
        "actor": actor,
        "detail": detail,
        "timestamp": _ts(),
    }
    audit_log.append(entry)
    return entry


async def presence_broadcast():
    await manager.broadcast({
        "type": "presence",
        "volunteers": manager.volunteers_online(),
        "civilians": manager.civilians_online(),
        "total": manager.total,
        "ts": _ts(),
    })


def stats_snapshot() -> Dict[str, Any]:
    active = [i for i in incidents if i["status"] != "resolved"]
    by_type: Dict[str, int] = {}
    by_severity = {"P1": 0, "P2": 0, "P3": 0}
    for i in incidents:
        by_type[i["type"]] = by_type.get(i["type"], 0) + 1
        by_severity[i["severity"]] = by_severity.get(i["severity"], 0) + 1
    resolved = [i for i in incidents if i["status"] == "resolved"]
    return {
        "active_incidents": len(active),
        "critical_p1": len([i for i in active if i["severity"] == "P1"]),
        "resolved_total": len(resolved),
        "total_incidents": len(incidents),
        "volunteers_online": len(manager.volunteers_online()),
        "civilians_online": manager.civilians_online(),
        "ws_clients": manager.total,
        "by_type": by_type,
        "by_severity": by_severity,
    }


# ──────────────────────────────────────────────
#  FastAPI
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="CrisisNexus API", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/", response_class=FileResponse)
async def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/api/health")
async def health():
    return {"status": "operational", "version": "3.0.0", "ws_clients": manager.total, "uptime_s": int(time.time())}


@app.get("/api/services")
async def services():
    return {"services": EMERGENCY_SERVICES}


@app.get("/api/incidents")
async def list_incidents(status: Optional[str] = None):
    items = incidents
    if status:
        items = [i for i in items if i["status"] == status]
    return {"incidents": sort_incidents(items), "total": len(items)}


@app.post("/api/incidents", status_code=201)
async def create_incident(body: IncidentCreate):
    global _inc_counter
    _inc_counter += 1
    sev = severity_from(body.type, body.casualties, is_sos=False)

    # Find nearest emergency service for suggestion
    suggested = None
    nearest_idx = find_nearest(body.lat, body.lon, EMERGENCY_SERVICES)
    if nearest_idx >= 0:
        s = EMERGENCY_SERVICES[nearest_idx]
        dist = haversine_km(body.lat, body.lon, s["lat"], s["lon"])
        suggested = {"id": s["id"], "name": s["name"], "type": s["type"],
                     "distance_km": round(dist, 2), "eta_min": round(eta_minutes(dist), 1)}

    inc = {
        "id": f"INC-{datetime.now().year}-{_inc_counter:04d}",
        "type": body.type,
        "severity": sev,
        "location": body.location,
        "lat": body.lat,
        "lon": body.lon,
        "description": body.description.strip(),
        "casualties": max(0, body.casualties),
        "contact": body.contact.strip(),
        "photo_data_url": body.photo_data_url,
        "reporter_name": body.reporter_name,
        "reporter_role": body.reporter_role,
        "status": "active",   # active -> dispatched -> resolved
        "dispatched_resources": [],
        "dispatch_note": "",
        "suggested_unit": suggested,
        "nearest_by_type": nearest_by_all_types(body.lat, body.lon),
        "is_sos": False,
        "timestamp": _ts(),
        "resolved_at": None,
        "resolved_by": None,
    }
    incidents.append(inc)
    add_audit("created", inc["id"], body.reporter_name, f"{body.type} @ {body.location}")

    await manager.broadcast({"type": "new_incident", "incident": inc, "stats": stats_snapshot(), "ts": _ts()})
    return {"incident": inc}


@app.post("/api/sos", status_code=201)
async def sos(body: SOSRequest):
    global _inc_counter
    _inc_counter += 1

    nearest_idx = find_nearest(body.lat, body.lon, EMERGENCY_SERVICES)
    suggested = None
    if nearest_idx >= 0:
        s = EMERGENCY_SERVICES[nearest_idx]
        dist = haversine_km(body.lat, body.lon, s["lat"], s["lon"])
        suggested = {"id": s["id"], "name": s["name"], "type": s["type"],
                     "distance_km": round(dist, 2), "eta_min": round(eta_minutes(dist), 1)}

    inc = {
        "id": f"SOS-{datetime.now().year}-{_inc_counter:04d}",
        "type": "SOS",
        "severity": "P1",
        "location": "GPS pin (SOS)",
        "lat": body.lat,
        "lon": body.lon,
        "description": "Emergency SOS — no further detail provided.",
        "casualties": 0,
        "contact": "",
        "photo_data_url": None,
        "reporter_name": body.reporter_name,
        "reporter_role": "civilian",
        "status": "active",
        "dispatched_resources": [],
        "dispatch_note": "",
        "suggested_unit": suggested,
        "nearest_by_type": nearest_by_all_types(body.lat, body.lon),
        "is_sos": True,
        "timestamp": _ts(),
        "resolved_at": None,
        "resolved_by": None,
    }
    incidents.append(inc)
    add_audit("sos", inc["id"], body.reporter_name, "SOS triggered")

    await manager.broadcast({"type": "sos", "incident": inc, "stats": stats_snapshot(), "ts": _ts()})
    return {"incident": inc}


@app.get("/api/incidents/{incident_id}")
async def get_incident(incident_id: str):
    inc = next((i for i in incidents if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    return inc


@app.post("/api/incidents/{incident_id}/dispatch")
async def dispatch(incident_id: str, body: DispatchRequest):
    inc = next((i for i in incidents if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    if inc["status"] == "resolved":
        raise HTTPException(400, "Already resolved")

    valid_types = {"police", "fire", "ambulance", "hospital"}
    resources: List[Dict[str, Any]] = []
    summary_parts: List[str] = []
    for order in body.orders:
        t = order.type.lower().strip()
        if t not in valid_types:
            continue
        n = max(0, min(int(order.count), 10))
        if n <= 0:
            continue
        nearest = nearest_of_type(inc["lat"], inc["lon"], t)
        if not nearest:
            continue
        resources.append({
            "type": t,
            "count": n,
            "station_id": nearest["id"],
            "station_name": nearest["name"],
            "station_lat": nearest["lat"],
            "station_lon": nearest["lon"],
            "distance_km": nearest["distance_km"],
            "eta_min": nearest["eta_min"],
            "speed_kmh": nearest["speed_kmh"],
            "status": "en_route",
            "dispatched_at": _ts(),
        })
        summary_parts.append(f"{n}× {t} from {nearest['name']} (ETA {nearest['eta_min']}m)")

    if not resources:
        raise HTTPException(400, "No valid units selected")

    inc["status"] = "dispatched"
    inc["dispatched_resources"] = resources
    inc["dispatch_note"] = body.note
    add_audit("dispatched", incident_id, body.actor_name,
              " | ".join(summary_parts) + (f" — {body.note}" if body.note else ""))
    await manager.broadcast({"type": "incident_update", "incident": inc, "stats": stats_snapshot(), "ts": _ts()})
    return {"incident": inc}


@app.post("/api/incidents/{incident_id}/resolve")
async def resolve(incident_id: str, body: ResolveRequest):
    inc = next((i for i in incidents if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    inc["status"] = "resolved"
    inc["resolved_at"] = _ts()
    inc["resolved_by"] = body.actor_name
    add_audit("resolved", incident_id, body.actor_name, body.note)
    await manager.broadcast({"type": "incident_resolved", "incident": inc, "stats": stats_snapshot(), "ts": _ts()})
    return {"incident": inc}


@app.delete("/api/incidents/{incident_id}")
async def delete_incident(incident_id: str, actor: str = "Unknown"):
    global incidents
    inc = next((i for i in incidents if i["id"] == incident_id), None)
    if not inc:
        raise HTTPException(404, "Incident not found")
    incidents = [i for i in incidents if i["id"] != incident_id]
    add_audit("deleted", incident_id, actor, f"{inc['type']} @ {inc['location']}")
    await manager.broadcast({"type": "incident_deleted", "id": incident_id, "stats": stats_snapshot(), "ts": _ts()})
    return {"deleted": incident_id}


@app.get("/api/audit")
async def audit():
    return {"audit": list(reversed(audit_log[-200:]))}


@app.get("/api/stats")
async def stats():
    return stats_snapshot()


@app.get("/api/presence")
async def presence():
    return {
        "volunteers": manager.volunteers_online(),
        "civilians": manager.civilians_online(),
        "total": manager.total,
    }


# ──────────────────────────────────────────────
#  WebSocket
# ──────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket, name: str = "Anonymous", role: str = "civilian"):
    if role not in ("volunteer", "civilian"):
        role = "civilian"
    client_id = uuid.uuid4().hex
    safe_name = (name or "Anonymous").strip()[:40] or "Anonymous"
    await manager.connect(ws, client_id, safe_name, role)
    try:
        await ws.send_text(json.dumps({
            "type": "init",
            "client_id": client_id,
            "incidents": sort_incidents(incidents),
            "audit": list(reversed(audit_log[-200:])),
            "services": EMERGENCY_SERVICES,
            "stats": stats_snapshot(),
            "presence": {
                "volunteers": manager.volunteers_online(),
                "civilians": manager.civilians_online(),
                "total": manager.total,
            },
            "ts": _ts(),
        }))
        await presence_broadcast()
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(client_id)
        try:
            await presence_broadcast()
        except Exception:
            pass


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
