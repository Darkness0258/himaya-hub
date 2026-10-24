"""Himaya hub configuration.

Everything is driven by environment variables (optionally loaded from a ``.env``
file) so the same code runs on a laptop, in Docker, or on Render without edits.

Design notes
------------
* Booleans are parsed properly. The old code used ``bool(os.environ.get("RENDER"))``
  which is ``True`` for the string ``"false"`` and silently put local Docker runs
  into "cloud mode".
* Nothing here has side effects at import time except :func:`load_dotenv`, which
  callers invoke explicitly.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
VERSION = "2.0.0"

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f", ""}


def env_bool(name: str, default: bool = False) -> bool:
    """Parse a boolean environment variable (``"false"`` really is False)."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return default


def env_int(name: str, default: int, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    """Parse an integer environment variable, clamped to ``[lo, hi]``."""
    raw = os.environ.get(name)
    try:
        value = int(raw) if raw is not None and raw.strip() != "" else default
    except ValueError:
        value = default
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def env_list(name: str) -> List[str]:
    raw = os.environ.get(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def load_dotenv(path: Optional[Path] = None) -> None:
    """Load ``KEY=VALUE`` pairs from a ``.env`` file without overriding real env vars."""
    if env_bool("HIMAYA_SKIP_DOTENV", False):
        return
    candidates = [path] if path else [BASE_DIR / ".env", BASE_DIR.parent / ".env"]
    for candidate in candidates:
        if candidate and candidate.is_file():
            try:
                for line in candidate.read_text(encoding="utf-8-sig").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and key not in os.environ:
                        os.environ[key] = value
            except OSError:
                pass
            return


def _parse_host_port(value: str, default_port: int = 53) -> Tuple[str, int]:
    value = value.strip()
    if ":" in value and not value.startswith("["):
        host, _, port = value.rpartition(":")
        try:
            return host, int(port)
        except ValueError:
            return value, default_port
    return value, default_port


@dataclass(frozen=True)
class Settings:
    # Storage
    data_dir: Path
    db_path: Path
    snapshots_dir: Path
    blocklist_dir: Path
    static_dir: Path
    agent_dir: Path
    # HTTP
    host: str
    port: int
    cors_origins: List[str] = field(default_factory=list)
    trust_proxy: bool = False
    public_url: Optional[str] = None
    is_cloud: bool = False
    keepalive: bool = False
    # Auth
    admin_key: Optional[str] = None
    # DNS sinkhole
    dns_enabled: bool = True
    dns_host: str = "0.0.0.0"
    dns_port: int = 5300
    dns_upstream: Tuple[str, int] = ("1.1.1.3", 53)
    dns_allow_public_clients: bool = False
    dns_always_allow: List[str] = field(default_factory=list)
    # Discovery beacon
    discovery_enabled: bool = True
    discovery_port: int = 5354
    # Misc
    timezone: Optional[str] = None
    lookup_public_ip: bool = False
    # Retention
    event_retention_days: int = 30
    snapshot_retention_days: int = 7
    snapshot_max_per_device: int = 500
    snapshot_max_bytes: int = 6 * 1024 * 1024
    heartbeat_timeout_s: int = 75
    watchdog_interval_s: int = 10


def load_settings() -> Settings:
    """Build :class:`Settings` from the current environment."""
    data_dir = Path(os.environ.get("HIMAYA_DATA_DIR") or (BASE_DIR / "data")).expanduser().resolve()
    db_path = Path(os.environ.get("HIMAYA_DB_PATH") or (data_dir / "himaya.db")).expanduser().resolve()
    is_cloud = env_bool("RENDER", False) or bool(os.environ.get("RENDER_EXTERNAL_URL")) or env_bool("HIMAYA_CLOUD", False)

    public_url = (os.environ.get("HIMAYA_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/") or None

    upstream = os.environ.get("HIMAYA_DNS_UPSTREAM", "1.1.1.3")
    port = env_int("PORT", env_int("HIMAYA_PORT", 8000, 1, 65535), 1, 65535)

    return Settings(
        data_dir=data_dir,
        db_path=db_path,
        snapshots_dir=data_dir / "snapshots",
        blocklist_dir=data_dir / "blocklists",
        static_dir=Path(os.environ.get("HIMAYA_STATIC_DIR") or (BASE_DIR / "static")).resolve(),
        agent_dir=BASE_DIR,
        host=os.environ.get("HIMAYA_HOST", "0.0.0.0"),
        port=port,
        cors_origins=env_list("HIMAYA_CORS_ORIGINS"),
        trust_proxy=env_bool("HIMAYA_TRUST_PROXY", is_cloud),
        public_url=public_url,
        is_cloud=is_cloud,
        keepalive=env_bool("HIMAYA_KEEPALIVE", is_cloud),
        admin_key=(os.environ.get("HIMAYA_ADMIN_KEY") or os.environ.get("HIMAYA_PARENT_API_KEY") or "").strip() or None,
        # Render exposes only HTTP, so a UDP DNS server is pointless there.
        dns_enabled=env_bool("HIMAYA_DNS_ENABLED", not is_cloud),
        dns_host=os.environ.get("HIMAYA_DNS_HOST", "0.0.0.0"),
        dns_port=env_int("HIMAYA_DNS_PORT", 5300, 1, 65535),
        dns_upstream=_parse_host_port(upstream, 53),
        dns_allow_public_clients=env_bool("HIMAYA_DNS_ALLOW_PUBLIC", False),
        dns_always_allow=env_list("HIMAYA_DNS_ALWAYS_ALLOW"),
        discovery_enabled=env_bool("HIMAYA_DISCOVERY", not is_cloud),
        discovery_port=env_int("HIMAYA_DISCOVERY_PORT", 5354, 1, 65535),
        timezone=(os.environ.get("HIMAYA_TIMEZONE") or "").strip() or None,
        lookup_public_ip=env_bool("HIMAYA_LOOKUP_PUBLIC_IP", False),
        event_retention_days=env_int("HIMAYA_EVENT_RETENTION_DAYS", 30, 1, 3650),
        snapshot_retention_days=env_int("HIMAYA_SNAPSHOT_RETENTION_DAYS", 7, 1, 3650),
        snapshot_max_per_device=env_int("HIMAYA_SNAPSHOT_MAX_PER_DEVICE", 500, 10, 100000),
        snapshot_max_bytes=env_int("HIMAYA_SNAPSHOT_MAX_BYTES", 6 * 1024 * 1024, 64 * 1024, 64 * 1024 * 1024),
        heartbeat_timeout_s=env_int("HIMAYA_HEARTBEAT_TIMEOUT", 75, 15, 3600),
        watchdog_interval_s=env_int("HIMAYA_WATCHDOG_INTERVAL", 10, 2, 300),
    )
