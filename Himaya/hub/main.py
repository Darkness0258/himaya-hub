"""Himaya Hub — FastAPI backend with device registry + WebSocket event feed."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional

from pathlib import Path
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from models import Device, DeviceCreate, DeviceStatus, Event, EventType, RemoteAction

app = FastAPI(title="Himaya Hub", version="0.1.0")

STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store (swap for SQLite/Postgres in v2)
devices: Dict[str, Device] = {}
events: list[Event] = []
clients: list[WebSocket] = []
pending_commands: Dict[str, list[dict]] = {}
event_counter = 0
main_loop: Optional[asyncio.AbstractEventLoop] = None


@app.on_event("startup")
async def startup_event():
    global main_loop
    main_loop = asyncio.get_running_loop()


def current_time() -> datetime:
    return datetime.now(timezone.utc)


async def _broadcast(payload: dict) -> None:
    dead = []
    for ws in list(clients):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in clients:
            clients.remove(ws)


def emit(event: Event) -> None:
    """Broadcast event to all connected dashboard clients."""
    global event_counter, main_loop
    event_counter += 1
    event = event.model_copy(update={"id": event_counter})
    events.append(event)
    payload = event.model_dump(mode="json")

    # Broadcast via main event loop across threads or coroutines
    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(payload), main_loop)
    else:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_broadcast(payload))
        except RuntimeError:
            pass


def device_went_dark(device_id: str) -> None:
    """Fire when a device misses consecutive heartbeats."""
    if device_id in devices:
        devices[device_id].status = DeviceStatus.OFFLINE
    evt = Event(
        device_id=device_id,
        type=EventType.DEVICE_WENT_DARK,
        data={"reason": "missed_heartbeats"},
        timestamp=current_time(),
    )
    emit(evt)


@app.get("/")
async def serve_dashboard_root():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "ok", "message": "Himaya Hub active"}


@app.get("/dashboard")
async def serve_dashboard():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "ok", "message": "Himaya Hub active"}


@app.post("/devices", response_model=Device)
async def register_device(body: DeviceCreate) -> Device:
    if body.device_id in devices:
        raise HTTPException(status_code=400, detail=f"Device {body.device_id} already registered")
    now = current_time()
    dev = Device(
        id=len(devices) + 1,
        **body.model_dump(),
        status=DeviceStatus.OFFLINE,
        last_seen=None,
        created_at=now,
    )
    devices[body.device_id] = dev
    if body.device_id not in pending_commands:
        pending_commands[body.device_id] = []
    return dev


@app.get("/devices", response_model=list[Device])
async def list_devices() -> list[Device]:
    return list(devices.values())


@app.get("/devices/{device_id}", response_model=Device)
async def get_device(device_id: str) -> Device:
    if device_id not in devices:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    return devices[device_id]


@app.get("/events", response_model=list[Event])
async def get_events(limit: int = 50) -> list[Event]:
    return events[-limit:]


@app.websocket("/ws")
async def ws_feed(ws: WebSocket):
    """Dashboard subscribes here for live event feed."""
    await ws.accept()
    clients.append(ws)
    try:
        # Send current device snapshot on connect
        await ws.send_json({
            "type": "snapshot",
            "devices": [d.model_dump(mode="json") for d in devices.values()],
            "events": [e.model_dump(mode="json") for e in events[-20:]],
        })
        while True:
            await ws.receive_text()  # keep connection alive
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in clients:
            clients.remove(ws)


# --- Agent-facing endpoints ---
@app.post("/agents/{device_id}/heartbeat")
async def heartbeat(device_id: str, ip: str = ""):
    now = current_time()
    if device_id not in devices:
        devices[device_id] = Device(
            id=len(devices) + 1,
            name=device_id,
            platform="unknown",
            device_id=device_id,
            ip=ip,
            created_at=now,
        )
        if device_id not in pending_commands:
            pending_commands[device_id] = []

    d = devices[device_id]
    d.last_seen = now
    if d.status not in (DeviceStatus.LOCKED, DeviceStatus.PAUSED):
        d.status = DeviceStatus.ONLINE
    d.ip = ip or d.ip
    emit(Event(device_id=device_id, type=EventType.HEARTBEAT, data={"ip": d.ip}, timestamp=now))
    return {"status": "ok", "timestamp": now.isoformat()}


@app.get("/agents/{device_id}/commands")
async def get_pending_commands(device_id: str):
    """Agent polls this to consume queued remote actions."""
    cmds = pending_commands.get(device_id, [])
    pending_commands[device_id] = []
    return {"device_id": device_id, "commands": cmds}


@app.post("/agents/{device_id}/dns-block")
async def dns_block(device_id: str, host: str = ""):
    now = current_time()
    emit(Event(device_id=device_id, type=EventType.DNS_BLOCK, data={"host": host}, timestamp=now))
    return {"status": "logged", "host": host}


@app.post("/agents/{device_id}/vpn-attempt")
async def vpn_attempt(device_id: str, interface: str = ""):
    now = current_time()
    emit(Event(device_id=device_id, type=EventType.VPN_ATTEMPT,
               data={"interface": interface}, timestamp=now))
    return {"status": "logged", "interface": interface}


@app.post("/agents/{device_id}/policy-sync")
async def policy_sync(device_id: str, rules: dict = {}):
    now = current_time()
    emit(Event(device_id=device_id, type=EventType.POLICY_SYNC, data=rules, timestamp=now))
    return {"status": "synced"}


# --- Admin remote actions ---
class ActionRequest(BaseModel):
    action: RemoteAction
    payload: dict = {}


@app.post("/admin/{device_id}/action")
async def remote_action(device_id: str, body: ActionRequest):
    if device_id not in devices:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    now = current_time()
    d = devices[device_id]

    if body.action == RemoteAction.LOCK:
        d.status = DeviceStatus.LOCKED
        evt_type = EventType.DEVICE_LOCKED
    elif body.action == RemoteAction.UNLOCK:
        d.status = DeviceStatus.ONLINE
        evt_type = EventType.DEVICE_UNLOCKED
    elif body.action == RemoteAction.PAUSE or body.action == RemoteAction.BLOCK_INTERNET:
        d.status = DeviceStatus.PAUSED
        evt_type = EventType.POLICY_SYNC
    elif body.action == RemoteAction.UNPAUSE or body.action == RemoteAction.UNBLOCK_INTERNET:
        d.status = DeviceStatus.ONLINE
        evt_type = EventType.POLICY_SYNC
    else:
        evt_type = EventType.POLICY_SYNC

    if device_id not in pending_commands:
        pending_commands[device_id] = []
    command_obj = {
        "action": body.action,
        "payload": body.payload,
        "timestamp": now.isoformat(),
    }
    pending_commands[device_id].append(command_obj)

    emit(Event(
        device_id=device_id,
        type=evt_type,
        data={"action": body.action, "payload": body.payload},
        timestamp=now,
    ))
    return {"status": "dispatched", "action": body.action, "device_status": d.status}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "devices": len(devices),
        "events": len(events),
        "ts": current_time().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)