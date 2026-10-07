"""Himaya Hub — FastAPI backend with device registry + WebSocket event feed."""
from __future__ import annotations
import asyncio
import json
import time
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from models import Device, DeviceCreate, DeviceStatus, Event, EventType, RemoteAction

app = FastAPI(title="Himaya Hub", version="0.1.0")

# In-memory store (swap for SQLite/Postgres in v2)
devices: Dict[str, Device] = {}
events: list[Event] = []
clients: list[WebSocket] = []
event_counter = 0


def emit(event: Event) -> None:
    """Broadcast event to all connected dashboard clients."""
    global event_counter
    event_counter += 1
    event = event.model_copy(update={"id": event_counter})
    events.append(event)
    payload = event.model_dump()
    dead = []
    for ws in clients:
        asyncio.create_task(ws.send_json(payload) if not ws.client_closed else dead.append(ws))
    for ws in dead:
        clients.remove(ws)


def device_went_dark(device_id: str) -> None:
    """Fire when a device misses consecutive heartbeats."""
    evt = Event(device_id=device_id, type=EventType.DEVICE_WENT_DARK,
                data={"reason": "missed_heartbeats"}, timestamp=datetime.utcnow())
    emit(evt)


@app.post("/devices", response_model=Device)
def register_device(body: DeviceCreate) -> Device:
    if body.device_id in devices:
        raise ValueError(f"Device {body.device_id} already registered")
    now = datetime.utcnow()
    dev = Device(id=len(devices) + 1, **body.model_dump(), status=DeviceStatus.OFFLINE,
                 last_seen=None, created_at=now)
    devices[body.device_id] = dev
    return dev


@app.get("/devices", response_model=list[Device])
def list_devices() -> list[Device]:
    return list(devices.values())


@app.get("/devices/{device_id}", response_model=Device)
def get_device(device_id: str) -> Device:
    if device_id not in devices:
        raise KeyError(f"Device {device_id} not found")
    return devices[device_id]


@app.get("/events", response_model=list[Event])
def get_events(limit: int = 50) -> list[Event]:
    return events[-limit:]


@app.websocket("/ws")
async def ws_feed(ws: WebSocket):
    """Dashboard subscribes here for live event feed."""
    await ws.accept()
    clients.append(ws)
    try:
        # Send current device snapshot on connect
        await ws.send_json({"type": "snapshot", "devices": [d.model_dump() for d in devices.values()]})
        while True:
            await ws.receive_text()  # keep connection alive; dashboard ignores content
    except WebSocketDisconnect:
        clients.remove(ws)


# --- Agent-facing endpoints ---
@app.post("/agents/{device_id}/heartbeat")
def heartbeat(device_id: str, ip: str = ""):
    now = datetime.utcnow()
    if device_id not in devices:
        devices[device_id] = Device(id=len(devices) + 1, name=device_id, platform="unknown",
                                    device_id=device_id, ip=ip)
    d = devices[device_id]
    d.last_seen = now
    d.status = DeviceStatus.ONLINE
    d.ip = ip or d.ip
    emit(Event(device_id=device_id, type=EventType.HEARTBEAT, data={"ip": d.ip}, timestamp=now))
    return {"status": "ok", "timestamp": now.isoformat()}


@app.post("/agents/{device_id}/dns-block")
def dns_block(device_id: str, host: str = ""):
    now = datetime.utcnow()
    emit(Event(device_id=device_id, type=EventType.DNS_BLOCK, data={"host": host}, timestamp=now))
    return {"status": "logged", "host": host}


@app.post("/agents/{device_id}/vpn-attempt")
def vpn_attempt(device_id: str, interface: str = ""):
    now = datetime.utcnow()
    emit(Event(device_id=device_id, type=EventType.VPN_ATTEMPT,
               data={"interface": interface}, timestamp=now))
    return {"status": "logged", "interface": interface}


@app.post("/agents/{device_id}/policy-sync")
def policy_sync(device_id: str, rules: dict = {}):
    now = datetime.utcnow()
    emit(Event(device_id=device_id, type=EventType.POLICY_SYNC, data=rules, timestamp=now))
    return {"status": "synced"}


# --- Admin remote actions ---
class ActionRequest(BaseModel):
    action: RemoteAction
    payload: dict = {}


@app.post("/admin/{device_id}/action")
def remote_action(device_id: str, body: ActionRequest):
    if device_id not in devices:
        raise KeyError(f"Device {device_id} not found")
    now = datetime.utcnow()
    type_map = {
        RemoteAction.LOCK: EventType.DEVICE_LOCKED,
        RemoteAction.UNLOCK: EventType.DEVICE_UNLOCKED,
    }
    evt_type = type_map.get(body.action, EventType.HEARTBEAT)
    emit(Event(device_id=device_id, type=evt_type, data={"action": body.action, "payload": body.payload}, timestamp=now))
    return {"status": "dispatched", "action": body.action}


@app.get("/health")
def health():
    return {"status": "ok", "devices": len(devices), "events": len(events), "ts": datetime.utcnow().isoformat()}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)