"""Himaya Hub — Real-World Production Backend with SQLite, DNS Engine, Lifespan & Snapshots."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
import shutil
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
from dns_server import DnsFilterServer
from models import Device, DeviceCreate, DeviceStatus, Event, EventType, RemoteAction

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
STATIC_DIR = Path(__file__).parent / "static"

SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

clients: list[WebSocket] = []
main_loop: Optional[asyncio.AbstractEventLoop] = None
dns_server: Optional[DnsFilterServer] = None
watchdog_task: Optional[asyncio.Task] = None


def current_time_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def heartbeat_watchdog():
    """Background watchdog that flags devices that miss heartbeats for > 45 seconds."""
    while True:
        try:
            await asyncio.sleep(10)
            now = datetime.now(timezone.utc)
            devices = database.list_devices()
            for dev in devices:
                if dev.get("status") == DeviceStatus.ONLINE.value and dev.get("last_seen"):
                    try:
                        last_seen_dt = datetime.fromisoformat(dev["last_seen"])
                        if (now - last_seen_dt).total_seconds() > 45:
                            database.update_device_status(dev["device_id"], DeviceStatus.OFFLINE.value)
                            emit(Event(
                                device_id=dev["device_id"],
                                type=EventType.DEVICE_WENT_DARK,
                                data={"reason": "heartbeat_timeout_exceeded_45s"},
                                timestamp=now
                            ))
                    except Exception:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as e:
            await asyncio.sleep(5)


def handle_dns_block_telemetry(client_ip: str, domain: str):
    """Callback from DNS engine when a blacklisted domain query is sinkholed."""
    now = datetime.now(timezone.utc)
    # Find matching device by IP or attribute to first registered device / unassigned
    matched_dev_id = "network-client"
    devices = database.list_devices()
    for d in devices:
        if d.get("ip") == client_ip:
            matched_dev_id = d["device_id"]
            break
    if matched_dev_id == "network-client" and devices:
        matched_dev_id = devices[0]["device_id"]

    database.insert_event(matched_dev_id, EventType.DNS_BLOCK.value, {"host": domain, "client_ip": client_ip}, now.isoformat())
    emit(Event(
        device_id=matched_dev_id,
        type=EventType.DNS_BLOCK,
        data={"host": domain, "client_ip": client_ip},
        timestamp=now
    ))


@asynccontextmanager
async def lifespan(app: FastAPI):
    global main_loop, dns_server, watchdog_task
    # Startup
    main_loop = asyncio.get_running_loop()
    database.init_db()

    # Start DNS sinkhole proxy on port 5353
    dns_server = DnsFilterServer(port=5353, on_block_callback=handle_dns_block_telemetry)
    dns_server.start()

    # Start Watchdog
    watchdog_task = asyncio.create_task(heartbeat_watchdog())

    yield

    # Shutdown
    if watchdog_task:
        watchdog_task.cancel()
    if dns_server:
        dns_server.stop()


app = FastAPI(title="Himaya Hub", version="1.0.0", lifespan=lifespan)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    """Broadcast event to all connected dashboard clients and persist in DB."""
    payload = event.model_dump(mode="json")

    # Persist in DB
    event_id = database.insert_event(
        device_id=event.device_id,
        event_type=event.type.value,
        data=event.data,
        timestamp=payload["timestamp"]
    )
    payload["id"] = event_id

    if main_loop and main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast(payload), main_loop)
    else:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_broadcast(payload))
        except RuntimeError:
            pass


# --- Probe & Health Endpoints ---
@app.get("/probe")
@app.get("/probe/")
async def probe():
    return {"status": "ready"}


@app.get("/favicon.ico")
async def favicon():
    return Response(content=b"", media_type="image/x-icon")


@app.get("/")
@app.get("/dashboard")
async def serve_dashboard():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"status": "ok", "message": "Himaya Hub active"}


# --- Device Registry ---
@app.post("/devices")
async def register_device(body: DeviceCreate):
    existing = database.get_device(body.device_id)
    if existing:
        raise HTTPException(status_code=400, detail=f"Device {body.device_id} already registered")

    dev = database.insert_device(
        device_id=body.device_id,
        name=body.name,
        platform=body.platform,
        owner_type=body.owner_type,
        ip=body.ip
    )
    return dev


@app.get("/devices")
async def list_devices():
    return database.list_devices()


@app.get("/devices/{device_id}")
async def get_device(device_id: str):
    dev = database.get_device(device_id)
    if not dev:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    return dev


@app.get("/events")
async def get_events(limit: int = 50):
    return database.list_events(limit=limit)


# --- Live WebSocket Telemetry Feed ---
@app.websocket("/ws")
async def ws_feed(ws: WebSocket):
    await ws.accept()
    clients.append(ws)
    try:
        # Send current snapshot on connect
        devices_list = database.list_devices()
        recent_events = database.list_events(limit=25)
        await ws.send_json({
            "type": "snapshot",
            "devices": devices_list,
            "events": recent_events
        })
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        if ws in clients:
            clients.remove(ws)


# --- Agent-Facing Telemetry Endpoints ---
@app.post("/agents/{device_id}/heartbeat")
async def heartbeat(device_id: str, ip: str = ""):
    now_str = current_time_iso()
    dev = database.get_device(device_id)
    if not dev:
        dev = database.insert_device(
            device_id=device_id,
            name=device_id,
            platform="unknown",
            owner_type="child",
            ip=ip
        )

    current_status = dev.get("status", "online")
    if current_status not in (DeviceStatus.LOCKED.value, DeviceStatus.PAUSED.value):
        current_status = DeviceStatus.ONLINE.value

    database.update_device_status(device_id, status=current_status, ip=ip, last_seen=now_str)

    emit(Event(
        device_id=device_id,
        type=EventType.HEARTBEAT,
        data={"ip": ip or dev.get("ip")},
        timestamp=datetime.now(timezone.utc)
    ))
    return {"status": "ok", "timestamp": now_str}


@app.get("/agents/{device_id}/commands")
async def get_pending_commands(device_id: str):
    """Agent calls this continuously to consume pending remote parent commands."""
    cmds = database.pop_pending_commands(device_id)
    return {"device_id": device_id, "commands": cmds}


@app.post("/agents/{device_id}/dns-block")
async def log_dns_block(device_id: str, host: str = ""):
    now = datetime.now(timezone.utc)
    emit(Event(
        device_id=device_id,
        type=EventType.DNS_BLOCK,
        data={"host": host},
        timestamp=now
    ))
    return {"status": "logged", "host": host}


@app.post("/agents/{device_id}/vpn-attempt")
async def log_vpn_attempt(device_id: str, interface: str = ""):
    now = datetime.now(timezone.utc)
    emit(Event(
        device_id=device_id,
        type=EventType.VPN_ATTEMPT,
        data={"interface": interface},
        timestamp=now
    ))
    return {"status": "logged", "interface": interface}


@app.post("/agents/{device_id}/policy-sync")
async def policy_sync(device_id: str, rules: dict = {}):
    now = datetime.now(timezone.utc)
    emit(Event(
        device_id=device_id,
        type=EventType.POLICY_SYNC,
        data=rules,
        timestamp=now
    ))
    return {"status": "synced"}


# --- Snapshot Storage & Inspection ---
@app.post("/agents/{device_id}/snapshot")
async def upload_snapshot(device_id: str, file: UploadFile = File(...)):
    """Agent uploads captured screen frame via MediaProjection or Windows capture."""
    dev_dir = SNAPSHOTS_DIR / device_id
    dev_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{int(datetime.now(timezone.utc).timestamp())}_{uuid.uuid4().hex[:6]}.jpg"
    dest_path = dev_dir / filename

    with open(dest_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    rec = database.record_snapshot(device_id, filename, str(dest_path))

    emit(Event(
        device_id=device_id,
        type=EventType.SCREENSHOT,
        data={"filename": filename, "url": f"/snapshots/{device_id}/{filename}"},
        timestamp=datetime.now(timezone.utc)
    ))
    return {"status": "uploaded", "snapshot": rec}


@app.get("/snapshots")
async def get_all_snapshots(device_id: Optional[str] = None):
    snaps = database.list_snapshots(device_id=device_id, limit=30)
    for s in snaps:
        s["url"] = f"/snapshots/{s['device_id']}/{s['filename']}"
    return snaps


@app.get("/snapshots/{device_id}/{filename}")
async def serve_snapshot_image(device_id: str, filename: str):
    file_path = SNAPSHOTS_DIR / device_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return FileResponse(file_path, media_type="image/jpeg")


# --- Parent Rules & Curfews ---
@app.get("/rules/{device_id}")
async def fetch_rules(device_id: str):
    return database.get_device_rules(device_id)


@app.post("/rules/{device_id}")
async def update_rules(device_id: str, rules: dict):
    database.save_device_rules(device_id, rules)
    # Queue policy sync command to agent
    database.queue_command(device_id, "policy_sync", rules)
    emit(Event(
        device_id=device_id,
        type=EventType.POLICY_SYNC,
        data=rules,
        timestamp=datetime.now(timezone.utc)
    ))
    return {"status": "saved", "rules": rules}


# --- Parent Remote Actions ---
class ActionRequest(BaseModel):
    action: RemoteAction
    payload: dict = {}


@app.post("/admin/{device_id}/action")
async def remote_action(device_id: str, body: ActionRequest):
    dev = database.get_device(device_id)
    if not dev:
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")

    new_status = dev.get("status", "online")
    if body.action == RemoteAction.LOCK:
        new_status = DeviceStatus.LOCKED.value
        evt_type = EventType.DEVICE_LOCKED
    elif body.action == RemoteAction.UNLOCK:
        new_status = DeviceStatus.ONLINE.value
        evt_type = EventType.DEVICE_UNLOCKED
    elif body.action in (RemoteAction.PAUSE, RemoteAction.BLOCK_INTERNET):
        new_status = DeviceStatus.PAUSED.value
        evt_type = EventType.POLICY_SYNC
    elif body.action in (RemoteAction.UNPAUSE, RemoteAction.UNBLOCK_INTERNET):
        new_status = DeviceStatus.ONLINE.value
        evt_type = EventType.POLICY_SYNC
    else:
        evt_type = EventType.POLICY_SYNC

    database.update_device_status(device_id, status=new_status)
    database.queue_command(device_id, body.action.value, body.payload)

    now = datetime.now(timezone.utc)
    emit(Event(
        device_id=device_id,
        type=evt_type,
        data={"action": body.action, "payload": body.payload},
        timestamp=now
    ))
    return {"status": "dispatched", "action": body.action, "device_status": new_status}


@app.get("/health")
async def health():
    devs = database.list_devices()
    evts = database.list_events()
    return {
        "status": "ok",
        "devices": len(devs),
        "events": len(evts),
        "ts": current_time_iso()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)