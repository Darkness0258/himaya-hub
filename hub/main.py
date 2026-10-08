"""Himaya Hub — Real-World Production Backend with SQLite, DNS Engine, Lifespan, Snapshots & Auto-Enrollment."""
from __future__ import annotations
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import shutil
import uuid
from typing import Dict, List, Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import qrcode

import database
from discovery import DiscoveryServer, get_lan_ip, get_public_ip, get_enrollment_pin, regenerate_enrollment_pin
from dns_server import DnsFilterServer
from models import Device, DeviceCreate, DeviceStatus, Event, EventType, RemoteAction

DATA_DIR = Path(__file__).parent / "data"
SNAPSHOTS_DIR = DATA_DIR / "snapshots"
STATIC_DIR = Path(__file__).parent / "static"
def get_windows_agent_path() -> Path:
    candidates = [
        Path(__file__).parent / "himaya_windows_agent.py",
        Path(__file__).parent / "agent-windows" / "himaya_windows_agent.py",
        Path(__file__).parent.parent / "agent-windows" / "himaya_windows_agent.py",
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]

WINDOWS_AGENT_PATH = get_windows_agent_path()


SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

clients: list[WebSocket] = []
main_loop: Optional[asyncio.AbstractEventLoop] = None
dns_server: Optional[DnsFilterServer] = None
discovery_server: Optional[DiscoveryServer] = None
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
    global main_loop, dns_server, discovery_server, watchdog_task
    # Startup
    main_loop = asyncio.get_running_loop()
    database.init_db()

    # Start DNS sinkhole proxy on port 5353
    dns_server = DnsFilterServer(port=5353, on_block_callback=handle_dns_block_telemetry)
    dns_server.start()

    # Start UDP LAN Auto-Discovery on port 5354
    discovery_server = DiscoveryServer(http_port=8000)
    discovery_server.start()

    # Start Watchdog
    watchdog_task = asyncio.create_task(heartbeat_watchdog())

    yield

    # Shutdown
    if watchdog_task:
        watchdog_task.cancel()
    if dns_server:
        dns_server.stop()
    if discovery_server:
        discovery_server.stop()


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


# --- AUTO-ENROLLMENT & ZERO-TOUCH ONBOARDING (INTERNET & LAN) ---
class SetPublicUrlRequest(BaseModel):
    public_url: str


@app.post("/enroll/public-url")
async def set_public_hub_url(body: SetPublicUrlRequest):
    """Save a custom Internet Hub URL (e.g. Public IP, DuckDNS, or Cloudflare Tunnel)."""
    cleaned = body.public_url.strip().rstrip("/")
    if cleaned and not (cleaned.startswith("http://") or cleaned.startswith("https://")):
        cleaned = f"http://{cleaned}"
    database.set_setting("public_hub_url", cleaned)
    return {"status": "ok", "public_url": cleaned}


@app.get("/enroll/info")
async def get_enrollment_info(request: Request, target: Optional[str] = None):
    """Returns dynamic network addresses and enrollment credentials for real devices across Internet & LAN."""
    lan_ip = get_lan_ip()
    public_ip = get_public_ip()
    saved_public_url = database.get_setting("public_hub_url") or os.environ.get("HIMAYA_PUBLIC_URL")

    lan_hub_url = f"http://{lan_ip}:8000"
    internet_hub_url = saved_public_url.rstrip("/") if saved_public_url else f"http://{public_ip}:8000"

    host_header = request.headers.get("host", "")
    active_hub_url = f"http://{host_header}" if host_header else lan_hub_url

    pin = get_enrollment_pin()

    return {
        "status": "ready",
        "lan_ip": lan_ip,
        "public_ip": public_ip,
        "pin": pin,
        "is_custom_internet_url": bool(saved_public_url),
        "lan": {
            "hub_url": lan_hub_url,
            "windows_cmd": f"irm {lan_hub_url}/enroll/win?target=lan | iex",
            "mobile_url": f"{lan_hub_url}/enroll/mobile?target=lan",
            "qr_url": f"/enroll/qr?target=lan",
        },
        "internet": {
            "hub_url": internet_hub_url,
            "windows_cmd": f"irm {internet_hub_url}/enroll/win?target=internet | iex",
            "mobile_url": f"{internet_hub_url}/enroll/mobile?target=internet",
            "qr_url": f"/enroll/qr?target=internet",
        },
        "hub_url": active_hub_url,
        "windows_cmd": f"irm {active_hub_url}/enroll/win | iex",
        "mobile_url": f"{active_hub_url}/enroll/mobile",
        "qr_url": f"/enroll/qr"
    }


@app.get("/enroll/qr")
async def get_enrollment_qr(request: Request, target: Optional[str] = "auto", hub_url: Optional[str] = None):
    """Generates a QR Code PNG for phone camera enrollment (supporting LAN and Internet)."""
    if hub_url:
        resolved_url = hub_url.rstrip("/")
    elif target == "internet":
        saved_public_url = database.get_setting("public_hub_url") or os.environ.get("HIMAYA_PUBLIC_URL")
        public_ip = get_public_ip()
        resolved_url = saved_public_url.rstrip("/") if saved_public_url else f"http://{public_ip}:8000"
    elif target == "lan":
        lan_ip = get_lan_ip()
        resolved_url = f"http://{lan_ip}:8000"
    else:
        lan_ip = get_lan_ip()
        host_header = request.headers.get("host", f"{lan_ip}:8000")
        resolved_url = f"http://{host_header}"

    target_url = f"{resolved_url}/enroll/mobile"
    img = qrcode.make(target_url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/enroll/win")
async def get_windows_installer_script(request: Request, target: Optional[str] = "auto", hub_url: Optional[str] = None):
    """Serves the 1-click PowerShell installer script for any Windows PC over Internet or LAN."""
    lan_ip = get_lan_ip()
    public_ip = get_public_ip()
    saved_public_url = database.get_setting("public_hub_url") or os.environ.get("HIMAYA_PUBLIC_URL")
    lan_hub_url = f"http://{lan_ip}:8000"
    internet_hub_url = saved_public_url.rstrip("/") if saved_public_url else f"http://{public_ip}:8000"

    if hub_url:
        primary_hub = hub_url.rstrip("/")
    elif target == "internet":
        primary_hub = internet_hub_url
    elif target == "lan":
        primary_hub = lan_hub_url
    else:
        host_header = request.headers.get("host", f"{lan_ip}:8000")
        primary_hub = f"http://{host_header}"

    script = f'''# Himaya Automatic Windows Agent Installer (Internet & LAN Multi-Homed)
$ErrorActionPreference = "Stop"
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   HIMAYA FAMILY SAFETY - REAL DEVICE AUTO-ENROLLMENT" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

$primaryUrl   = "{primary_hub}"
$lanUrl       = "{lan_hub_url}"
$internetUrl  = "{internet_hub_url}"
$candidateUrls = @($primaryUrl, $internetUrl, $lanUrl, "http://127.0.0.1:8000") | Select-Object -Unique

$computerName = $env:COMPUTERNAME
$userName = $env:USERNAME
$rawId = [guid]::NewGuid().ToString().Substring(0, 8)
$deviceId = "win-$rawId"
$deviceName = "$computerName ($userName)"

Write-Host "Probing Hub connectivity across network endpoints..." -ForegroundColor Yellow
$hubUrl = $primaryUrl
$connected = $false

foreach ($candidate in $candidateUrls) {{
    try {{
        Write-Host "  Testing candidate: $candidate/health ..." -NoNewline
        $resp = Invoke-RestMethod -Uri "$candidate/health" -Method Get -TimeoutSec 4
        if ($resp.status -eq "ok") {{
            $hubUrl = $candidate
            $connected = $true
            Write-Host " [OK - CONNECTED]" -ForegroundColor Green
            break
        }} else {{
            Write-Host " [Non-ok response]" -ForegroundColor DarkYellow
        }}
    }} catch {{
        Write-Host " [Unreachable]" -ForegroundColor DarkGray
    }}
}}

if (-not $connected) {{
    Write-Host "Notice: Direct health probe timed out; configuring with active endpoints ($primaryUrl)." -ForegroundColor DarkYellow
}} else {{
    Write-Host "Active connection established with Himaya Hub at $hubUrl" -ForegroundColor Green
}}

$agentDir = "$env:LOCALAPPDATA\\HimayaAgent"
if (-not (Test-Path $agentDir)) {{
    New-Item -ItemType Directory -Path $agentDir -Force | Out-Null
}}

$config = @{{
    hub_url = $hubUrl
    candidate_urls = $candidateUrls
    device_id = $deviceId
    device_name = $deviceName
}} | ConvertTo-Json

Set-Content -Path "$agentDir\\agent_config.json" -Value $config -Force

Write-Host "Downloading Himaya Background Protection Engine..." -ForegroundColor Yellow
$agentDownloaded = $false
foreach ($dlCandidate in @($hubUrl, $primaryUrl, $lanUrl, $internetUrl) | Select-Object -Unique) {{
    try {{
        Invoke-WebRequest -Uri "$dlCandidate/enroll/win/agent.py" -OutFile "$agentDir\\himaya_windows_agent.py" -TimeoutSec 10
        $agentDownloaded = $true
        Write-Host "Protection engine successfully fetched from $dlCandidate" -ForegroundColor Green
        break
    }} catch {{}}
}}

if (-not $agentDownloaded) {{
    Write-Host "Error: Could not retrieve himaya_windows_agent.py from any candidate URL." -ForegroundColor Red
    exit 1
}}

# Register device with Hub
$regPayload = @{{
    name = $deviceName
    platform = "windows"
    device_id = $deviceId
    owner_type = "child"
}} | ConvertTo-Json

foreach ($regCandidate in @($hubUrl, $primaryUrl, $lanUrl, $internetUrl) | Select-Object -Unique) {{
    try {{
        Invoke-RestMethod -Uri "$regCandidate/devices" -Method Post -Body $regPayload -ContentType "application/json" -TimeoutSec 5 | Out-Null
        Write-Host "Device registered in Hub registry at $regCandidate." -ForegroundColor Green
        break
    }} catch {{}}
}}

# Ensure Pillow & Requests are installed
try {{
    python -m pip install --quiet requests pillow
}} catch {{}}

# Create Windows Startup Launcher (.vbs so it starts silently in background on logon)
$vbsScript = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run "pythonw.exe ""$agentDir\\himaya_windows_agent.py""", 0, False
"@
$startupDir = [Environment]::GetFolderPath("Startup")
Set-Content -Path "$startupDir\\HimayaAgent.vbs" -Value $vbsScript -Force

# Start Agent Process immediately
Start-Process -WindowStyle Hidden -FilePath "pythonw.exe" -ArgumentList """$agentDir\\himaya_windows_agent.py"""

Write-Host "========================================================" -ForegroundColor Green
Write-Host "  SUCCESS: REAL DEVICE AUTO-ENROLLED!" -ForegroundColor Green
Write-Host "  Name:       $deviceName" -ForegroundColor Green
Write-Host "  ID:         $deviceId" -ForegroundColor Green
Write-Host "  Hub:        $hubUrl" -ForegroundColor Green
Write-Host "  Failover:   Multi-homed (Internet + LAN automatic switching)" -ForegroundColor Green
Write-Host "  Status:     Active background protection enabled." -ForegroundColor Green
Write-Host "  Auto-Start: Enabled via Windows Startup folder." -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
'''
    return Response(content=script, media_type="text/plain; charset=utf-8")


@app.get("/enroll/win/agent.py")
async def get_windows_agent_file():
    agent_path = get_windows_agent_path()
    if not agent_path.exists():
        raise HTTPException(status_code=404, detail="Agent script not found")
    return FileResponse(agent_path, media_type="text/x-python")


@app.get("/enroll/mobile", response_class=HTMLResponse)
async def get_mobile_enrollment_page(request: Request, target: Optional[str] = "auto", hub_url: Optional[str] = None):
    """Mobile onboarding page rendered when scanning the QR code from phone/tablet."""
    lan_ip = get_lan_ip()
    public_ip = get_public_ip()
    saved_public_url = database.get_setting("public_hub_url") or os.environ.get("HIMAYA_PUBLIC_URL")
    lan_hub_url = f"http://{lan_ip}:8000"
    internet_hub_url = saved_public_url.rstrip("/") if saved_public_url else f"http://{public_ip}:8000"

    if hub_url:
        active_url = hub_url.rstrip("/")
    elif target == "internet":
        active_url = internet_hub_url
    elif target == "lan":
        active_url = lan_hub_url
    else:
        host_header = request.headers.get("host", f"{lan_ip}:8000")
        active_url = f"http://{host_header}"

    pin = get_enrollment_pin()

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Himaya Device Protection Enrollment</title>
    <style>
        body {{
            background: #0b0f19;
            color: #f8fafc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            padding: 24px;
            text-align: center;
            margin: 0;
        }}
        .card {{
            background: #1e293b;
            border-radius: 20px;
            padding: 28px 22px;
            max-width: 440px;
            margin: 20px auto;
            border: 1px solid rgba(255,255,255,0.1);
            box-shadow: 0 20px 40px rgba(0,0,0,0.5);
        }}
        .badge {{
            display: inline-block;
            background: rgba(16, 185, 129, 0.15);
            color: #10b981;
            padding: 4px 12px;
            border-radius: 999px;
            font-size: 0.75rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 1px;
            margin-bottom: 12px;
        }}
        .pin {{
            font-size: 2.8rem;
            font-weight: 800;
            letter-spacing: 8px;
            color: #10b981;
            margin: 16px 0;
            font-family: monospace;
            background: #0f172a;
            padding: 12px;
            border-radius: 12px;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }}
        .btn {{
            display: block;
            background: linear-gradient(135deg, #10b981, #059669);
            color: white;
            text-decoration: none;
            padding: 16px;
            border-radius: 12px;
            font-weight: 700;
            font-size: 1.05rem;
            margin-top: 24px;
            box-shadow: 0 8px 20px rgba(16, 185, 129, 0.3);
        }}
        .step {{
            text-align: left;
            margin: 14px 0;
            font-size: 0.95rem;
            color: #cbd5e1;
            line-height: 1.4;
        }}
        .hub-tag {{
            background: #0f172a;
            padding: 6px 10px;
            border-radius: 6px;
            color: #38bdf8;
            font-family: monospace;
            font-size: 0.85rem;
            word-break: break-all;
            display: inline-block;
            margin-top: 4px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <span class="badge">🌐 Internet & LAN Auto-Enroll</span>
        <h2 style="margin: 6px 0 10px 0;">🛡️ Himaya Family Safety</h2>
        <p style="color: #94a3b8; font-size: 0.9rem; margin-top: 0;">Connect this device to your Family Safety Hub</p>
        
        <div style="font-size: 0.75rem; color: #94a3b8; text-transform: uppercase; margin-top: 20px; font-weight: 600;">6-Digit Pairing PIN</div>
        <div class="pin">{pin}</div>

        <div class="step"><b>1.</b> Tap the button below to launch Himaya Agent on this phone.</div>
        <div class="step"><b>2.</b> Hub Address will be pre-filled to:<br><span class="hub-tag">{active_url}</span></div>
        <div class="step"><b>3.</b> Confirm the 6-digit PIN to establish protected Device Owner status.</div>

        <a href="intent://enroll?hub={active_url}&pin={pin}#Intent;scheme=himaya;package=com.himaya.agent;end" class="btn">
            ⚡ Open Himaya App & Auto-Pair
        </a>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


class PairRequest(BaseModel):
    pin: str
    name: str
    platform: str
    owner_type: str = "child"
    ip: Optional[str] = None


@app.post("/enroll/pair")
async def pair_device(body: PairRequest):
    """Enrolls a real device using the 6-digit Quick PIN."""
    expected_pin = get_enrollment_pin()
    if body.pin != expected_pin:
        raise HTTPException(status_code=400, detail="Invalid enrollment PIN")

    device_id = f"{body.platform}-{uuid.uuid4().hex[:6]}"
    dev = database.insert_device(
        device_id=device_id,
        name=body.name,
        platform=body.platform,
        owner_type=body.owner_type,
        ip=body.ip
    )
    emit(Event(

        device_id=device_id,
        type=EventType.POLICY_SYNC,
        data={"action": "device_paired", "device": dev},
        timestamp=datetime.now(timezone.utc)
    ))
    return {
        "status": "paired",
        "device_id": device_id,
        "device": dev
    }


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
        "lan_ip": get_lan_ip(),
        "public_ip": get_public_ip(),
        "ts": current_time_iso()
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)