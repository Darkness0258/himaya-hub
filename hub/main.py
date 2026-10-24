"""Himaya Hub - local-first family device safety.

Run:   python main.py          (or)   uvicorn main:app --host 0.0.0.0 --port 8000

The application is built by :func:`create_app` so tests can create isolated hubs.
See ``docs/SECURITY.md`` for the threat model and ``docs/API.md`` for the routes.
"""
from __future__ import annotations

import asyncio
import io
import ipaddress
import json
import logging
import re
import secrets
import shutil
import socket
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    Path as PathParam,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

import config
import database
import security
import templates
from discovery import DiscoveryServer, get_lan_ip, get_public_ip
from dns_server import DnsFilterServer
from filtering import FilterEngine, normalize_domain
from models import (
    DEVICE_ID_PATTERN,
    ActionRequest,
    AgentEventIn,
    DeviceCreate,
    DevicePatch,
    DnsBlockIn,
    EventType,
    HeartbeatIn,
    PairRequest,
    PublicUrlIn,
    RemoteAction,
    RulesIn,
    VpnAttemptIn,
)

log = logging.getLogger("himaya.hub")

FILENAME_PATTERN = r"^[A-Za-z0-9_.-]{1,100}\.jpg$"
APP_NAME_RE = re.compile(r"^[A-Za-z0-9_. -]{1,80}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
ALERT_TYPES = {"vpn_attempt", "device_went_dark", "agent_stopped"}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def safe_join(base: Path, *parts: str) -> Optional[Path]:
    """Resolve ``base/parts`` and make sure it cannot escape ``base``."""
    base = base.resolve()
    target = base.joinpath(*parts).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        return None
    return target


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # never follow redirects (SSRF hardening)
        return None


def _resolves_to_public_ips(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    addresses = {info[4][0] for info in infos}
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


def ping_public_url(url: str) -> bool:
    """Keep-alive ping for free cloud hosts. Only public https hosts, no redirects."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not _resolves_to_public_ips(parsed.hostname):
        return False
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(url.rstrip("/") + "/health", headers={"User-Agent": "himaya-keepalive"})
    try:
        with opener.open(request, timeout=10) as response:  # noqa: S310 - validated above
            return response.status == 200
    except Exception:
        return False


class Hub:
    """All mutable state of one hub instance (kept off module globals so tests can isolate it)."""

    def __init__(self, settings: config.Settings):
        self.settings = settings
        self.auth = security.AuthService(settings.data_dir, settings.admin_key)
        self.pin = security.PinManager()
        self.auth_failures = security.RateLimiter(10, 60)
        self.ws_clients: set = set()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.engine = FilterEngine(settings.blocklist_dir, settings.timezone, settings.dns_always_allow)
        self.dns: Optional[DnsFilterServer] = None
        self.discovery: Optional[DiscoveryServer] = None
        self.tasks: List[asyncio.Task] = []
        self.dns_block_seen: Dict[Any, float] = {}
        self.last_push: Dict[str, float] = {}
        self.new_admin_key: Optional[str] = None
        self.started_at = time.time()


def create_app(settings: Optional[config.Settings] = None) -> FastAPI:
    if settings is None:
        config.load_dotenv()
        settings = config.load_settings()
    hub = Hub(settings)

    expose_docs = config.env_bool("HIMAYA_DOCS", False)

    # ------------------------------------------------------------------ #
    # Broadcasting / events
    # ------------------------------------------------------------------ #
    async def _broadcast(message: Dict[str, Any]) -> None:
        dead = []
        for ws in list(hub.ws_clients):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            hub.ws_clients.discard(ws)

    def broadcast(message: Dict[str, Any]) -> None:
        """Thread-safe: callable from request threads, the DNS thread and the event loop."""
        if hub.loop is not None and hub.ws_clients:
            try:
                asyncio.run_coroutine_threadsafe(_broadcast(message), hub.loop)
            except RuntimeError:
                pass

    def signed_snapshot_url(device_id: str, filename: str, ttl_s: int = 900) -> str:
        path = f"/snapshots/{device_id}/{filename}"
        exp, sig = hub.auth.sign(path, ttl_s)
        return f"{path}?exp={exp}&sig={sig}"

    def decorate_event(event: Dict[str, Any]) -> Dict[str, Any]:
        if event.get("type") == "screenshot":
            filename = (event.get("data") or {}).get("filename")
            if filename and re.match(FILENAME_PATTERN, filename):
                event = {**event, "data": {**event["data"], "url": signed_snapshot_url(event["device_id"], filename)}}
        return event

    def emit(device_id: str, event_type: str, data: Optional[Dict[str, Any]] = None, persist: bool = True) -> Dict[str, Any]:
        data = data or {}
        timestamp = database.now_iso()
        event: Dict[str, Any] = {"id": None, "device_id": device_id, "type": event_type, "data": data, "timestamp": timestamp}
        if persist:
            try:
                event["id"] = database.insert_event(device_id, event_type, data, timestamp)
            except Exception:
                log.exception("Could not store event %s", event_type)
        event = decorate_event(event)
        broadcast({"type": "event", "event": event})
        return event

    def device_out(device: Dict[str, Any]) -> Dict[str, Any]:
        out = {key: device.get(key) for key in (
            "id", "device_id", "name", "platform", "ip", "owner_type", "status", "last_seen",
            "created_at", "locked", "paused", "caps", "agent_version")}
        out["state"] = "locked" if device["locked"] else "paused" if device["paused"] else device["status"]
        return out

    def push_device(device: Dict[str, Any]) -> None:
        broadcast({"type": "device", "device": device_out(device)})

    def refresh_filter() -> None:
        hub.engine.refresh(database.list_devices(), database.list_all_rules())

    def agent_state(device: Dict[str, Any], rules: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        rules = rules or database.get_device_rules(device["device_id"])
        return {
            "locked": bool(device["locked"]),
            "paused": bool(device["paused"]),
            "bedtime_active": hub.engine.bedtime_active(rules),
        }

    def rules_out(device: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
        out = dict(rules)
        out["bedtime_active"] = hub.engine.bedtime_active(rules)
        out["paused"] = bool(device["paused"])
        out["locked"] = bool(device["locked"])
        out["effective_blocked_domains"] = hub.engine.effective_blocked_domains(rules)
        return out

    def effective_public_url() -> Optional[str]:
        return database.get_setting("public_url") or hub.settings.public_url

    # ------------------------------------------------------------------ #
    # DNS telemetry
    # ------------------------------------------------------------------ #
    def decide(client_ip: str, domain: str):
        return hub.engine.decide(client_ip, domain)

    def on_dns_block(client_ip: str, domain: str, decision) -> None:
        if decision.reason in ("paused", "bedtime"):
            return  # the device is known to be paused; logging every lookup would only be noise
        key = (decision.device_id or client_ip, domain)
        now = time.time()
        if now - hub.dns_block_seen.get(key, 0) < 60:
            return
        hub.dns_block_seen[key] = now
        if len(hub.dns_block_seen) > 5000:
            cutoff = now - 60
            hub.dns_block_seen = {k: v for k, v in hub.dns_block_seen.items() if v > cutoff}
        device_id = decision.device_id or f"network-{client_ip}"
        emit(device_id, "dns_block", {"host": domain, "reason": decision.reason, "source": "hub-dns", "client_ip": client_ip})

    # ------------------------------------------------------------------ #
    # Background loops
    # ------------------------------------------------------------------ #
    def check_dark_devices() -> None:
        now = datetime.now(timezone.utc)
        for device in database.list_devices():
            if device["status"] != "online":
                continue
            seen = parse_ts(device["last_seen"])
            if seen is None or (now - seen).total_seconds() > hub.settings.heartbeat_timeout_s:
                updated = database.update_device(device["device_id"], status="offline")
                emit(device["device_id"], "device_went_dark", {"name": device["name"], "last_seen": device["last_seen"]})
                if updated:
                    push_device(updated)

    async def heartbeat_watchdog() -> None:
        ticks = 0
        while True:
            await asyncio.sleep(hub.settings.watchdog_interval_s)
            ticks += 1
            try:
                await asyncio.to_thread(check_dark_devices)
                if ticks % 3 == 0:  # also keeps DNS policy (device IPs, bedtime) fresh
                    await asyncio.to_thread(refresh_filter)
            except Exception:
                log.exception("Watchdog error")

    def run_retention() -> Dict[str, int]:
        now = datetime.now(timezone.utc)
        event_cutoff = (now - timedelta(days=hub.settings.event_retention_days)).isoformat()
        command_cutoff = (now - timedelta(days=7)).isoformat()
        removed = database.prune(event_cutoff, command_cutoff)
        snapshot_cutoff = (now - timedelta(days=hub.settings.snapshot_retention_days)).isoformat()
        doomed = database.snapshots_older_than(snapshot_cutoff)
        for device_id in database.snapshot_device_ids():
            doomed.extend(database.snapshots_beyond_limit(device_id, hub.settings.snapshot_max_per_device))
        seen_ids = set()
        for row in doomed:
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            target = safe_join(hub.settings.snapshots_dir, row["device_id"], row["filename"])
            if target and target.exists():
                try:
                    target.unlink()
                except OSError:
                    pass
        database.delete_snapshot_rows(list(seen_ids))
        removed["snapshots"] = len(seen_ids)
        return removed

    async def retention_loop() -> None:
        while True:
            try:
                removed = await asyncio.to_thread(run_retention)
                if any(removed.values()):
                    log.info("Retention removed %s", removed)
            except Exception:
                log.exception("Retention error")
            await asyncio.sleep(3600)

    async def keepalive_loop() -> None:
        """Free cloud hosts sleep when idle; ping our own public URL every 9 minutes."""
        while True:
            await asyncio.sleep(540)
            url = effective_public_url()
            if url:
                await asyncio.to_thread(ping_public_url, url)

    # ------------------------------------------------------------------ #
    # Lifespan
    # ------------------------------------------------------------------ #
    def print_banner() -> None:
        lan = get_lan_ip()
        port = settings.port
        lines = ["", "=" * 66, f"  Himaya Hub {config.VERSION}"]
        if hub.new_admin_key:
            lines += [
                "  ADMIN KEY (shown once - it is also saved in the data folder):",
                f"    {hub.new_admin_key}",
                f"    file: {hub.auth.key_file}",
            ]
        elif settings.admin_key:
            lines.append("  Admin key: taken from the HIMAYA_ADMIN_KEY environment variable.")
        else:
            lines.append(f"  Admin key: already created (see {hub.auth.key_file}).")
        if not settings.is_cloud:
            lines += [f"  Dashboard:  http://{lan}:{port}", f"  This PC:    http://localhost:{port}"]
        if settings.is_cloud and not database.get_database_url():
            lines += [
                "  WARNING: running in the cloud without DATABASE_URL. The local SQLite file",
                "  is erased when the host restarts, so devices would have to re-enroll.",
            ]
        lines += ["=" * 66, ""]
        print("\n".join(lines), flush=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        hub.loop = asyncio.get_running_loop()
        for folder in (settings.data_dir, settings.snapshots_dir, settings.blocklist_dir):
            folder.mkdir(parents=True, exist_ok=True)
        database.configure(settings.db_path)
        database.init_db()
        hub.new_admin_key = hub.auth.bootstrap()
        public = effective_public_url()
        if public:
            host = urllib.parse.urlparse(public).hostname
            if host:
                hub.engine.set_always_allow(list(settings.dns_always_allow) + [host])
        refresh_filter()
        print_banner()

        if settings.dns_enabled:
            hub.dns = DnsFilterServer(
                decide, host=settings.dns_host, port=settings.dns_port, upstream=settings.dns_upstream,
                on_block=on_dns_block, allow_public_clients=settings.dns_allow_public_clients,
            )
            await asyncio.to_thread(hub.dns.start)
        if settings.discovery_enabled:
            hub.discovery = DiscoveryServer(settings.port, settings.discovery_port, dns_port=settings.dns_port if settings.dns_enabled else None)
            await asyncio.to_thread(hub.discovery.start)

        hub.tasks = [asyncio.create_task(heartbeat_watchdog()), asyncio.create_task(retention_loop())]
        if settings.keepalive:
            hub.tasks.append(asyncio.create_task(keepalive_loop()))
        try:
            yield
        finally:
            for task in hub.tasks:
                task.cancel()
            await asyncio.gather(*hub.tasks, return_exceptions=True)
            if hub.dns:
                await asyncio.to_thread(hub.dns.stop)
            if hub.discovery:
                await asyncio.to_thread(hub.discovery.stop)

    app = FastAPI(
        title="Himaya Hub",
        version=config.VERSION,
        lifespan=lifespan,
        docs_url="/docs" if expose_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if expose_docs else None,
    )
    app.state.hub = hub
    hub.check_dark_devices = check_dark_devices  # type: ignore[attr-defined]
    hub.run_retention = run_retention  # type: ignore[attr-defined]
    hub.emit = emit  # type: ignore[attr-defined]

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PATCH", "DELETE"],
            allow_headers=["X-API-Key", "Content-Type"],
            allow_credentials=False,
        )

    default_csp = (
        "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; connect-src 'self' ws: wss:; font-src 'self' data:; "
        "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if "text/html" in headers.get("content-type", "") and "content-security-policy" not in headers:
            headers["Content-Security-Policy"] = default_csp
        if request.url.path.startswith(("/devices", "/events", "/api", "/admin", "/rules", "/enroll/info", "/snapshots")):
            headers.setdefault("Cache-Control", "no-store")
        return response

    # ------------------------------------------------------------------ #
    # Auth dependencies
    # ------------------------------------------------------------------ #
    def get_identity(request: Request, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> security.Identity:
        ip = security.client_ip(request, settings.trust_proxy)
        if hub.auth_failures.blocked(ip):
            raise HTTPException(429, "Too many failed attempts. Wait a minute and try again.")
        if not x_api_key:
            raise HTTPException(401, "Missing X-API-Key header.", headers={"WWW-Authenticate": "ApiKey"})
        identity = hub.auth.verify(x_api_key)
        if identity is None:
            hub.auth_failures.fail(ip)
            raise HTTPException(401, "That key is not valid.", headers={"WWW-Authenticate": "ApiKey"})
        return identity

    def require_parent(identity: security.Identity = Depends(get_identity)) -> security.Identity:
        if identity.role != "parent":
            raise HTTPException(403, "This action needs the parent (admin) key.")
        return identity

    def require_device_access(
        device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN),
        identity: security.Identity = Depends(get_identity),
    ) -> security.Identity:
        if identity.role == "parent" or (identity.role == "agent" and identity.device_id == device_id):
            return identity
        raise HTTPException(403, "This key cannot access that device.")

    def get_device_or_404(device_id: str) -> Dict[str, Any]:
        device = database.get_device(device_id)
        if device is None:
            raise HTTPException(404, "Device not found.")
        return device

    # ------------------------------------------------------------------ #
    # Public: health + dashboard
    # ------------------------------------------------------------------ #
    @app.get("/health")
    def health() -> Dict[str, Any]:
        return {"status": "ok", "service": "himaya-hub", "version": config.VERSION}

    @app.get("/probe")
    def probe() -> Dict[str, str]:
        return {"service": "himaya-hub", "status": "ok"}

    @app.get("/health/details")
    def health_details(_: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        devices = database.list_devices()
        return {
            "status": "ok",
            "version": config.VERSION,
            "uptime_s": int(time.time() - hub.started_at),
            "database": database.backend_name(),
            "devices": len(devices),
            "online": sum(1 for d in devices if d["status"] == "online"),
            "events": database.count_events(),
            "snapshots": database.count_snapshots(),
            "dns": hub.dns.status() if hub.dns else {"running": False},
            "discovery": {"running": bool(hub.discovery and hub.discovery.running)},
            "lan_ip": get_lan_ip(),
        }

    def index_response() -> Response:
        index = settings.static_dir / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-cache"})
        return HTMLResponse(
            "<!doctype html><meta charset=utf-8><title>Himaya Hub</title>"
            "<body style='font:16px system-ui;max-width:42rem;margin:12vh auto;padding:0 1rem'>"
            "<h1>Himaya Hub is running</h1><p>The dashboard has not been built yet. "
            "In the <code>dashboard</code> folder run <code>npm install</code> then <code>npm run build</code>, "
            "and restart the hub.</p></body>"
        )

    @app.get("/", include_in_schema=False)
    def root() -> Response:
        return index_response()

    @app.get("/dashboard", include_in_schema=False)
    def dashboard() -> Response:
        return index_response()

    # ------------------------------------------------------------------ #
    # Session helpers
    # ------------------------------------------------------------------ #
    @app.get("/api/me")
    def me(identity: security.Identity = Depends(get_identity)) -> Dict[str, Any]:
        return {"role": identity.role, "device_id": identity.device_id or None, "version": config.VERSION}

    @app.post("/api/admin-key/rotate")
    def rotate_admin_key(_: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        if settings.admin_key:
            raise HTTPException(409, "The admin key is set by the HIMAYA_ADMIN_KEY environment variable. Change it there.")
        return {"admin_key": hub.auth.reset_admin_key()}

    # ------------------------------------------------------------------ #
    # Devices
    # ------------------------------------------------------------------ #
    @app.get("/devices")
    def list_devices(_: security.Identity = Depends(require_parent)) -> List[Dict[str, Any]]:
        return [device_out(d) for d in database.list_devices()]

    @app.post("/devices", status_code=201)
    def create_device(body: DeviceCreate, request: Request, _: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        try:
            device = database.insert_device(body.device_id, body.name, body.platform, body.owner_type, body.ip)
        except database.DuplicateDevice:
            raise HTTPException(409, "A device with that ID already exists.")
        key = hub.auth.issue_agent_key(device["device_id"])
        refresh_filter()
        emit(device["device_id"], "device_paired", {"name": device["name"], "platform": device["platform"], "via": "dashboard"})
        push_device(device)
        return {**device_out(device), "agent_key": key}

    @app.get("/devices/{device_id}")
    def get_device(device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_device_access)) -> Dict[str, Any]:
        return device_out(get_device_or_404(device_id))

    @app.patch("/devices/{device_id}")
    def patch_device(
        body: DevicePatch,
        device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN),
        _: security.Identity = Depends(require_parent),
    ) -> Dict[str, Any]:
        get_device_or_404(device_id)
        changes = body.model_dump(exclude_none=True)
        updated = database.update_device(device_id, **changes)
        assert updated is not None
        push_device(updated)
        return device_out(updated)

    @app.delete("/devices/{device_id}")
    def delete_device(device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        get_device_or_404(device_id)
        hub.auth.revoke_device(device_id)
        database.delete_device(device_id)
        folder = safe_join(settings.snapshots_dir, device_id)
        if folder and folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)
        refresh_filter()
        broadcast({"type": "device_removed", "device_id": device_id})
        return {"status": "deleted", "device_id": device_id}

    # ------------------------------------------------------------------ #
    # Events + stats
    # ------------------------------------------------------------------ #
    @app.get("/events")
    def list_events(
        limit: int = Query(50, ge=1, le=500),
        before_id: Optional[int] = Query(None, ge=1),
        device_id: Optional[str] = Query(None, max_length=64),
        event_type: Optional[str] = Query(None, alias="type", max_length=200),
        _: security.Identity = Depends(require_parent),
    ) -> List[Dict[str, Any]]:
        types = [t.strip() for t in event_type.split(",") if t.strip()] if event_type else None
        events = database.list_events(limit, before_id, device_id, types, exclude_types=None if types else ["heartbeat"])
        return [decorate_event(e) for e in events]

    @app.get("/api/stats")
    def stats(_: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        since = now - timedelta(hours=24)
        events = database.events_since(since.isoformat(), exclude_types=["heartbeat"])
        by_type = Counter(e["type"] for e in events)
        start_hour = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=23)
        buckets = [
            {"t": (start_hour + timedelta(hours=i)).isoformat(), "dns_block": 0, "alerts": 0, "screenshots": 0, "other": 0}
            for i in range(24)
        ]
        blocked_hosts: Counter = Counter()
        for event in events:
            stamp = parse_ts(event["timestamp"])
            if stamp is None:
                continue
            index = int((stamp - start_hour).total_seconds() // 3600)
            if not 0 <= index < 24:
                continue
            kind = event["type"]
            if kind == "dns_block":
                buckets[index]["dns_block"] += 1
                host = (event.get("data") or {}).get("host")
                if host:
                    blocked_hosts[host] += 1
            elif kind in ALERT_TYPES:
                buckets[index]["alerts"] += 1
            elif kind == "screenshot":
                buckets[index]["screenshots"] += 1
            else:
                buckets[index]["other"] += 1
        devices = database.list_devices()
        return {
            "generated_at": now.isoformat(),
            "devices": {
                "total": len(devices),
                "online": sum(1 for d in devices if d["status"] == "online"),
                "locked": sum(1 for d in devices if d["locked"]),
                "paused": sum(1 for d in devices if d["paused"]),
            },
            "events_24h": {"total": len(events), "by_type": dict(by_type)},
            "alerts_24h": sum(count for kind, count in by_type.items() if kind in ALERT_TYPES),
            "histogram": buckets,
            "top_blocked": [{"host": host, "count": count} for host, count in blocked_hosts.most_common(6)],
            "snapshots_total": database.count_snapshots(),
        }

    @app.get("/api/categories")
    def categories(_: security.Identity = Depends(require_parent)) -> List[Dict[str, Any]]:
        return hub.engine.category_info()

    @app.get("/api/settings")
    def get_settings(_: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        local_tz = datetime.now().astimezone().tzname()
        return {
            "version": config.VERSION,
            "database": database.backend_name(),
            "is_cloud": settings.is_cloud,
            "public_url": effective_public_url(),
            "lan_ip": get_lan_ip(),
            "port": settings.port,
            "timezone": settings.timezone or local_tz,
            "dns": hub.dns.status() if hub.dns else {"running": False, "enabled": settings.dns_enabled},
            "discovery": {"running": bool(hub.discovery and hub.discovery.running), "port": settings.discovery_port},
            "retention": {
                "events_days": settings.event_retention_days,
                "snapshots_days": settings.snapshot_retention_days,
                "snapshots_per_device": settings.snapshot_max_per_device,
            },
            "admin_key_source": "environment" if settings.admin_key else "generated",
        }

    # ------------------------------------------------------------------ #
    # Rules
    # ------------------------------------------------------------------ #
    @app.get("/rules/{device_id}")
    def get_rules(device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_device_access)) -> Dict[str, Any]:
        device = get_device_or_404(device_id)
        return rules_out(device, database.get_device_rules(device_id))

    @app.post("/rules/{device_id}")
    def save_rules(body: RulesIn, device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        device = get_device_or_404(device_id)
        changes = body.model_dump(exclude_none=True)
        if not changes:
            return rules_out(device, database.get_device_rules(device_id))
        saved = database.save_device_rules(device_id, changes)
        database.queue_command(device_id, "policy_sync", {"changed": sorted(changes)})
        refresh_filter()
        emit(device_id, "policy_sync", {"action": "rules_updated", "changed": sorted(changes)})
        return rules_out(device, saved)

    # ------------------------------------------------------------------ #
    # Remote actions (parent -> device)
    # ------------------------------------------------------------------ #
    @app.post("/admin/{device_id}/action")
    def remote_action(body: ActionRequest, device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        device = get_device_or_404(device_id)
        action = body.action
        payload = dict(body.payload)
        command_payload: Dict[str, Any] = {}
        event_type = EventType.REMOTE_ACTION.value
        event_data: Dict[str, Any] = {"action": action.value}
        changes: Dict[str, Any] = {}

        if action == RemoteAction.WIPE:
            if device["platform"] != "android":
                raise HTTPException(400, "Remote wipe is only available for Android devices.")
            if payload.get("confirm") != device_id:
                raise HTTPException(400, "Wiping erases the device. Send payload {\"confirm\": \"<device_id>\"} to confirm.")
            command_payload = {"confirmed": True}
        elif action == RemoteAction.PUSH_NOTIFICATION:
            message = CONTROL_RE.sub("", str(payload.get("message", ""))).strip()[:500]
            if not message:
                raise HTTPException(400, "Write a message to send.")
            command_payload = {"message": message}
            event_data["message"] = message
        elif action == RemoteAction.FORCE_CLOSE_APP:
            app_name = str(payload.get("app", "")).strip()
            if not APP_NAME_RE.match(app_name):
                raise HTTPException(400, "Enter the app name to close (letters, numbers, dot, dash, space).")
            command_payload = {"app": app_name}
            event_data["app"] = app_name
        elif action == RemoteAction.LOCK:
            changes["locked"] = True
            event_type = EventType.DEVICE_LOCKED.value
        elif action == RemoteAction.UNLOCK:
            changes["locked"] = False
            event_type = EventType.DEVICE_UNLOCKED.value
        elif action in (RemoteAction.PAUSE, RemoteAction.BLOCK_INTERNET):
            changes["paused"] = True
        elif action in (RemoteAction.UNPAUSE, RemoteAction.UNBLOCK_INTERNET):
            changes["paused"] = False

        updated = database.update_device(device_id, **changes) if changes else device
        assert updated is not None
        database.queue_command(device_id, action.value, command_payload)
        if "paused" in changes:
            refresh_filter()
        emit(device_id, event_type, event_data)
        push_device(updated)
        return {"status": "dispatched", "action": action.value, "device": device_out(updated)}

    # ------------------------------------------------------------------ #
    # Agent endpoints (device key required)
    # ------------------------------------------------------------------ #
    @app.post("/agents/{device_id}/heartbeat")
    def heartbeat(
        request: Request,
        body: Optional[HeartbeatIn] = None,
        ip: str = Query("", max_length=64),  # legacy agents send the IP as a query parameter
        device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN),
        _: security.Identity = Depends(require_device_access),
    ) -> Dict[str, Any]:
        device = get_device_or_404(device_id)
        reported_ip = (body.ip if body and body.ip else None) or (ip or None)
        try:
            reported_ip = str(ipaddress.ip_address(reported_ip)) if reported_ip else None
        except ValueError:
            reported_ip = None
        reported_ip = reported_ip or security.client_ip(request, settings.trust_proxy)
        now = database.now_iso()
        fields: Dict[str, Any] = {"status": "online", "last_seen": now}
        if reported_ip and reported_ip != "unknown":
            fields["ip"] = reported_ip
        if body and body.caps is not None:
            fields["caps"] = body.caps
        if body and body.agent_version:
            fields["agent_version"] = body.agent_version
        was_offline = device["status"] != "online"
        ip_changed = bool(fields.get("ip")) and fields["ip"] != device.get("ip")
        updated = database.update_device(device_id, **fields)
        assert updated is not None
        if was_offline:
            emit(device_id, "device_online", {"name": device["name"]})
        if was_offline or ip_changed:
            refresh_filter()
        # Tell dashboards immediately on a state change, otherwise at most every 30 s.
        now_ts = time.time()
        if was_offline or ip_changed or now_ts - hub.last_push.get(device_id, 0) > 30:
            hub.last_push[device_id] = now_ts
            push_device(updated)
        broadcast({"type": "heartbeat", "device_id": device_id, "timestamp": now})
        rules = database.get_device_rules(device_id)
        return {
            "status": "ok",
            "timestamp": now,
            "state": agent_state(updated, rules),
            "snapshot_interval_s": rules["snapshot_interval_s"],
            "dns_port": settings.dns_port if hub.dns and hub.dns.running else None,
        }

    @app.get("/agents/{device_id}/commands")
    def poll_commands(device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_device_access)) -> Dict[str, Any]:
        device = get_device_or_404(device_id)
        return {"device_id": device_id, "commands": database.pop_pending_commands(device_id), "state": agent_state(device)}

    @app.post("/agents/{device_id}/dns-block")
    def agent_dns_block(
        body: Optional[DnsBlockIn] = None,
        host: str = Query("", max_length=253),
        device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN),
        _: security.Identity = Depends(require_device_access),
    ) -> Dict[str, str]:
        get_device_or_404(device_id)
        name = normalize_domain((body.host if body and body.host else host) or "") or "unknown"
        emit(device_id, "dns_block", {"host": name, "source": "agent"})
        return {"status": "ok"}

    @app.post("/agents/{device_id}/vpn-attempt")
    def agent_vpn_attempt(
        body: Optional[VpnAttemptIn] = None,
        interface: str = Query("", max_length=120),
        device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN),
        _: security.Identity = Depends(require_device_access),
    ) -> Dict[str, str]:
        get_device_or_404(device_id)
        name = CONTROL_RE.sub("", (body.interface if body and body.interface else interface) or "unknown").strip()[:120] or "unknown"
        emit(device_id, "vpn_attempt", {"interface": name})
        return {"status": "ok"}

    @app.post("/agents/{device_id}/policy-sync")
    def agent_policy_sync(device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_device_access)) -> Dict[str, str]:
        # Older agents confirmed their rules every minute. The hub is the source of
        # truth, so this is only an acknowledgement (storing each one would be noise).
        get_device_or_404(device_id)
        return {"status": "ok"}

    @app.post("/agents/{device_id}/event")
    def agent_event(body: AgentEventIn, device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN), _: security.Identity = Depends(require_device_access)) -> Dict[str, str]:
        device = get_device_or_404(device_id)
        emit(device_id, body.type, {**body.data, "name": device["name"]})
        if body.type == "agent_stopped":
            updated = database.update_device(device_id, status="offline")
            if updated:
                push_device(updated)
        return {"status": "ok"}

    @app.post("/agents/{device_id}/snapshot")
    async def upload_snapshot(
        file: UploadFile = File(...),
        device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN),
        _: security.Identity = Depends(require_device_access),
    ) -> Dict[str, Any]:
        limit = settings.snapshot_max_bytes
        content = await file.read(limit + 1)
        if len(content) > limit:
            raise HTTPException(413, f"Screenshot is larger than {limit // 1024} KB.")
        if not content.startswith(b"\xff\xd8\xff"):
            raise HTTPException(415, "Screenshots must be JPEG images.")

        def store() -> Dict[str, Any]:
            get_device_or_404(device_id)
            folder = safe_join(settings.snapshots_dir, device_id)
            if folder is None:
                raise HTTPException(400, "Bad device id.")
            folder.mkdir(parents=True, exist_ok=True)
            filename = f"shot_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}.jpg"
            (folder / filename).write_bytes(content)
            record = database.record_snapshot(device_id, filename, f"{device_id}/{filename}")
            emit(device_id, "screenshot", {"filename": filename, "snapshot_id": record["id"]})
            return {"status": "ok", "snapshot": {**record, "url": signed_snapshot_url(device_id, filename)}}

        return await asyncio.to_thread(store)

    # ------------------------------------------------------------------ #
    # Snapshots (parent)
    # ------------------------------------------------------------------ #
    @app.get("/snapshots")
    def list_snapshots(
        device_id: Optional[str] = Query(None, max_length=64),
        limit: int = Query(24, ge=1, le=100),
        before_id: Optional[int] = Query(None, ge=1),
        _: security.Identity = Depends(require_parent),
    ) -> List[Dict[str, Any]]:
        rows = database.list_snapshots(device_id, limit, before_id)
        return [{**row, "url": signed_snapshot_url(row["device_id"], row["filename"])} for row in rows]

    @app.delete("/snapshots/{snapshot_id}")
    def delete_snapshot(snapshot_id: int, _: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        row = database.get_snapshot(snapshot_id)
        if row is None:
            raise HTTPException(404, "Screenshot not found.")
        target = safe_join(settings.snapshots_dir, row["device_id"], row["filename"])
        if target and target.exists():
            target.unlink()
        database.delete_snapshot_rows([snapshot_id])
        return {"status": "deleted", "id": snapshot_id}

    @app.get("/snapshots/{device_id}/{filename}")
    def serve_snapshot(
        device_id: str = PathParam(..., pattern=DEVICE_ID_PATTERN),
        filename: str = PathParam(..., pattern=FILENAME_PATTERN),
        exp: Optional[int] = Query(None),
        sig: Optional[str] = Query(None, max_length=80),
        x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    ) -> Response:
        path = f"/snapshots/{device_id}/{filename}"
        allowed = bool(exp is not None and sig and hub.auth.check_signature(path, exp, sig))
        if not allowed and x_api_key:
            identity = hub.auth.verify(x_api_key)
            allowed = bool(identity and identity.role == "parent")
        if not allowed:
            raise HTTPException(403, "This screenshot link is missing or has expired. Reload the dashboard.")
        target = safe_join(settings.snapshots_dir, device_id, filename)
        if target is None or not target.is_file():
            raise HTTPException(404, "Screenshot not found.")
        return FileResponse(target, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})

    # ------------------------------------------------------------------ #
    # Enrollment
    # ------------------------------------------------------------------ #
    def request_base(request: Request) -> str:
        scheme = request.url.scheme
        host = request.headers.get("host", "")
        if settings.trust_proxy:
            scheme = request.headers.get("x-forwarded-proto", scheme).split(",")[0].strip()
            host = request.headers.get("x-forwarded-host", host).split(",")[0].strip()
        candidate = f"{scheme}://{host}"
        return candidate if templates.is_safe_base_url(candidate) else ""

    def is_loopback_url(url: str) -> bool:
        host = urllib.parse.urlparse(url).hostname or ""
        return host in ("localhost", "127.0.0.1", "::1")

    def hub_urls(request: Request) -> List[Dict[str, str]]:
        urls: List[Dict[str, str]] = []
        base = request_base(request)
        port = request.url.port or settings.port
        if not settings.is_cloud:
            urls.append({"kind": "lan", "label": "Same Wi-Fi", "url": f"http://{get_lan_ip()}:{port}"})
        public = effective_public_url()
        if public and templates.is_safe_base_url(public):
            urls.append({"kind": "internet", "label": "Internet", "url": public.rstrip("/")})
        elif settings.is_cloud and base and base.startswith("https://"):
            urls.append({"kind": "internet", "label": "Internet", "url": base})
        elif settings.lookup_public_ip and not settings.is_cloud:
            public_ip = get_public_ip()
            if public_ip:
                urls.append({"kind": "internet", "label": "Internet (needs port forwarding)", "url": f"http://{public_ip}:{port}"})
        return urls

    @app.get("/enroll/info")
    def enroll_info(request: Request, _: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        pin, ttl = hub.pin.current()
        entries = []
        for item in hub_urls(request):
            entries.append({
                **item,
                "windows_command": f"irm {item['url']}/enroll/win | iex",
                "mobile_url": f"{item['url']}/enroll/mobile",
                "qr_path": f"/enroll/qr?kind={item['kind']}",
            })
        return {
            "pin": pin,
            "pin_expires_in": ttl,
            "urls": entries,
            "is_cloud": settings.is_cloud,
            "lan_ip": get_lan_ip(),
            "dns_port": settings.dns_port if hub.dns and hub.dns.running else None,
        }

    @app.post("/enroll/pin/regenerate")
    def regenerate_pin(_: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        hub.pin.rotate()
        pin, ttl = hub.pin.current()
        return {"pin": pin, "pin_expires_in": ttl}

    @app.post("/enroll/public-url")
    def set_public_url(body: PublicUrlIn, _: security.Identity = Depends(require_parent)) -> Dict[str, Any]:
        url = body.url.strip().rstrip("/")
        if url and not templates.is_safe_base_url(url):
            raise HTTPException(400, "Enter an address like https://my-hub.example.com (no path or spaces).")
        if url:
            database.set_setting("public_url", url)
        else:
            database.delete_setting("public_url")
        host = urllib.parse.urlparse(url).hostname if url else None
        hub.engine.set_always_allow(list(settings.dns_always_allow) + ([host] if host else []))
        return {"public_url": effective_public_url()}

    @app.get("/enroll/win", response_class=PlainTextResponse)
    def windows_installer(request: Request) -> PlainTextResponse:
        candidates: List[str] = []
        base = request_base(request)
        if base and not is_loopback_url(base):
            candidates.append(base)
        candidates.extend(item["url"] for item in hub_urls(request))
        if not candidates:
            raise HTTPException(500, "The hub could not work out its own address. Set HIMAYA_PUBLIC_URL.")
        return PlainTextResponse(templates.build_windows_installer(candidates), media_type="text/plain; charset=utf-8")

    @app.get("/enroll/win/uninstall.ps1", response_class=PlainTextResponse)
    def windows_uninstaller() -> PlainTextResponse:
        return PlainTextResponse(templates.build_windows_uninstaller(), media_type="text/plain; charset=utf-8")

    @app.get("/enroll/win/agent.py")
    def windows_agent() -> Response:
        for candidate in (settings.agent_dir / "himaya_windows_agent.py", settings.agent_dir.parent / "agent-windows" / "himaya_windows_agent.py"):
            if candidate.is_file():
                return FileResponse(candidate, media_type="text/plain; charset=utf-8", filename="himaya_windows_agent.py")
        raise HTTPException(404, "Windows agent file is missing from this hub.")

    @app.get("/enroll/mobile", response_class=HTMLResponse)
    def mobile_enroll_page(request: Request) -> HTMLResponse:
        base = request_base(request)
        if not base or is_loopback_url(base):
            entries = hub_urls(request)
            base = entries[0]["url"] if entries else ""
        if not base:
            raise HTTPException(500, "The hub could not work out its own address. Set HIMAYA_PUBLIC_URL.")
        nonce = secrets.token_urlsafe(12)
        page = templates.build_mobile_enroll_page(base, nonce)
        csp = (
            f"default-src 'none'; style-src 'nonce-{nonce}'; script-src 'nonce-{nonce}'; "
            "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
        )
        return HTMLResponse(page, headers={"Content-Security-Policy": csp})

    @app.get("/enroll/qr")
    def enroll_qr(request: Request, kind: str = Query("lan", pattern="^(lan|internet)$")) -> Response:
        match = next((u for u in hub_urls(request) if u["kind"] == kind), None)
        if match is None:
            raise HTTPException(404, "That kind of address is not available on this hub.")
        try:
            import qrcode
        except ImportError:
            raise HTTPException(501, "QR codes need the 'qrcode' package: pip install qrcode[pil]")
        image = qrcode.make(f"{match['url']}/enroll/mobile", box_size=8, border=2)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return Response(buffer.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.post("/enroll/pair")
    def pair_device(body: PairRequest, request: Request) -> Dict[str, Any]:
        ip = security.client_ip(request, settings.trust_proxy)
        outcome = hub.pin.verify(body.pin, ip)
        if outcome == "rate_limited":
            raise HTTPException(429, "Too many wrong PINs. Wait a few minutes, then try again.", headers={"Retry-After": str(max(1, hub.pin.retry_after(ip)))})
        if outcome != "ok":
            raise HTTPException(403, "That PIN was not accepted. It changes after every use, so check the dashboard.")
        device = None
        for _ in range(5):
            try:
                device = database.insert_device(f"{body.platform}-{secrets.token_hex(4)}", body.name, body.platform, body.owner_type, body.ip or ip)
                break
            except database.DuplicateDevice:
                continue
        if device is None:  # pragma: no cover - 5 random collisions in a row
            raise HTTPException(500, "Could not allocate a device id. Try again.")
        if body.owner_type == "adult":
            # Adults are enrolled by agreement: no screenshots and no default blocking.
            database.save_device_rules(device["device_id"], {"snapshot_interval_s": 0, "blocked_categories": [], "blocked_domains": []})
        key = hub.auth.issue_agent_key(device["device_id"])
        refresh_filter()
        emit(device["device_id"], "device_paired", {"name": device["name"], "platform": device["platform"], "owner_type": device["owner_type"], "via": "pin"})
        push_device(device)
        return {
            "status": "paired",
            "device_id": device["device_id"],
            "agent_key": key,
            "device": device_out(device),
            "hub_name": "Himaya Safety Hub",
            "dns_port": settings.dns_port if hub.dns and hub.dns.running else None,
        }

    # ------------------------------------------------------------------ #
    # WebSocket feed (authenticated by a first message, never by URL)
    # ------------------------------------------------------------------ #
    @app.websocket("/ws")
    async def websocket_feed(ws: WebSocket) -> None:
        await ws.accept()
        ip = security.client_ip(ws, settings.trust_proxy)
        if hub.auth_failures.blocked(ip):
            await ws.close(code=4429)
            return
        try:
            raw = await asyncio.wait_for(ws.receive_text(), timeout=10)
            message = json.loads(raw)
        except (asyncio.TimeoutError, WebSocketDisconnect, ValueError):
            await ws.close(code=4401)
            return
        key = message.get("key") if isinstance(message, dict) and message.get("type") == "auth" else None
        if not hub.auth.verify_admin(key):
            hub.auth_failures.fail(ip)
            await ws.send_json({"type": "auth_failed"})
            await ws.close(code=4401)
            return
        hub.ws_clients.add(ws)
        try:
            devices = await asyncio.to_thread(database.list_devices)
            events = await asyncio.to_thread(database.list_events, 50, None, None, None, ["heartbeat"])
            await ws.send_json({
                "type": "snapshot",
                "devices": [device_out(d) for d in devices],
                "events": [decorate_event(e) for e in events],
            })
            while True:
                incoming = await ws.receive_text()
                try:
                    if json.loads(incoming).get("type") == "ping":
                        await ws.send_json({"type": "pong"})
                except (ValueError, AttributeError):
                    pass
        except WebSocketDisconnect:
            pass
        except Exception:
            log.debug("WebSocket closed with error", exc_info=True)
        finally:
            hub.ws_clients.discard(ws)

    # ------------------------------------------------------------------ #
    # Static dashboard
    # ------------------------------------------------------------------ #
    assets_dir = settings.static_dir / "assets"
    if assets_dir.is_dir():
        class ImmutableAssets(StaticFiles):
            async def get_response(self, path, scope):
                response = await super().get_response(path, scope)
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response

        app.mount("/assets", ImmutableAssets(directory=str(assets_dir)), name="assets")
    if settings.static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    @app.get("/{name}", include_in_schema=False)
    def root_file(name: str) -> Response:
        """Top-level static files such as favicon.svg and manifest.webmanifest."""
        if re.match(r"^[A-Za-z0-9_.-]{1,80}$", name) and name != "index.html":
            target = safe_join(settings.static_dir, name)
            if target and target.is_file():
                media_type = "application/manifest+json" if name.endswith(".webmanifest") else None
                return FileResponse(target, media_type=media_type)
        raise HTTPException(404, "Not found.")

    return app


app = create_app()


def _cli() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Himaya Hub")
    parser.add_argument("--host", default=None, help="bind address (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help="HTTP port (default 8000 or $PORT)")
    parser.add_argument("--reset-admin-key", action="store_true", help="create a new admin key, print it and exit")
    args = parser.parse_args()

    config.load_dotenv()
    current = config.load_settings()
    if args.reset_admin_key:
        database.configure(current.db_path)
        database.init_db()
        auth = security.AuthService(current.data_dir, None)
        auth.bootstrap()
        if current.admin_key:
            print("HIMAYA_ADMIN_KEY is set in the environment, so it always wins. Change it there instead.")
            return
        print("New admin key (all older keys stop working):\n  " + auth.reset_admin_key())
        return

    import dataclasses

    import uvicorn

    overrides = {}
    if args.host:
        overrides["host"] = args.host
    if args.port:
        overrides["port"] = args.port
    effective = dataclasses.replace(current, **overrides) if overrides else current
    # Rebuild the app so the banner, discovery beacon and enrollment URLs use the real port.
    uvicorn.run(create_app(effective), host=effective.host, port=effective.port, log_level="info")


if __name__ == "__main__":
    _cli()
