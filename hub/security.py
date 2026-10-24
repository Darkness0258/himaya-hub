"""Authentication, pairing PINs, rate limiting and signed URLs for the Himaya hub.

Threat model (short version)
----------------------------
The hub holds a family's device telemetry and screenshots, so:

* **Parent actions** (list devices, lock, read screenshots, change rules) need the
  *admin key*. It is generated on first start, only its SHA-256 hash is stored,
  and it can be supplied through ``HIMAYA_ADMIN_KEY`` for cloud deployments.
* **Agents** (Windows / Android) get a *per-device key* when they pair. A device
  key can only talk to its own ``/agents/<device_id>/...`` endpoints.
* **Pairing** needs a 6-digit PIN that is random, expires, is single use, and is
  only ever shown to an authenticated parent. Wrong guesses are rate limited per
  client and globally, and trigger an automatic PIN change.
* **Screenshots** are served through short-lived HMAC-signed URLs so an ``<img>``
  tag works without putting the admin key in a URL.

Keys have high entropy (256 bits), so a fast hash is appropriate here (this is
not a human-chosen password).
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple

import database

ADMIN_PREFIX = "hma_"
AGENT_PREFIX = "hag_"


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_key(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


@dataclass(frozen=True)
class Identity:
    role: str  # "parent" or "agent"
    device_id: str = ""


# --------------------------------------------------------------------------- #
# Network helpers
# --------------------------------------------------------------------------- #
_LAN_NETWORKS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16",
        "100.64.0.0/10",  # CGNAT: Tailscale, many VPNs, carrier NAT
        "::1/128", "fc00::/7", "fe80::/10",
    )
)


def is_lan_client(ip: str) -> bool:
    """True for loopback, private (RFC1918 / ULA), link-local and CGNAT addresses only."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return any(addr.version == net.version and addr in net for net in _LAN_NETWORKS)


def client_ip(request, trust_proxy: bool) -> str:
    """Best-effort client address. Only trusts X-Forwarded-For when told to."""
    if trust_proxy:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip() or "unknown"
    return request.client.host if getattr(request, "client", None) else "unknown"


# --------------------------------------------------------------------------- #
# Rate limiting
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Counts *failures* per key inside a sliding window."""

    def __init__(self, max_failures: int, window_s: float):
        self.max_failures = max_failures
        self.window_s = window_s
        self._hits: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    def _live(self, key: str, now: float) -> Optional[Deque[float]]:
        """Return the key's deque after dropping expired hits (None if empty)."""
        hits = self._hits.get(key)
        if hits is None:
            return None
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def fail(self, key: str) -> None:
        now = time.time()
        with self._lock:
            hits = self._live(key, now)
            if hits is None:
                hits = self._hits.setdefault(key, deque())
            hits.append(now)
            if len(self._hits) > 5000:  # keep memory bounded under scanning
                for other in list(self._hits):
                    self._live(other, now)

    def blocked(self, key: str) -> bool:
        with self._lock:
            hits = self._live(key, time.time())
            return hits is not None and len(hits) >= self.max_failures

    def retry_after(self, key: str) -> int:
        now = time.time()
        with self._lock:
            hits = self._live(key, now)
            if hits is None or len(hits) < self.max_failures:
                return 0
            return max(1, int(self.window_s - (now - hits[0])) + 1)

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


# --------------------------------------------------------------------------- #
# Pairing PIN
# --------------------------------------------------------------------------- #
class PinManager:
    """6-digit enrollment PIN: random, expiring, single use, brute-force resistant."""

    def __init__(self, ttl_s: int = 900, per_ip_failures: int = 5, per_ip_window_s: int = 300, global_failures: int = 12):
        self.ttl_s = ttl_s
        self._lock = threading.Lock()
        self._pin = ""
        self._expires = 0.0
        self._ip = RateLimiter(per_ip_failures, per_ip_window_s)
        self._global = RateLimiter(global_failures, per_ip_window_s)
        self._rotate_locked()

    def _rotate_locked(self) -> str:
        self._pin = f"{secrets.randbelow(1_000_000):06d}"
        self._expires = time.time() + self.ttl_s
        return self._pin

    def rotate(self) -> str:
        with self._lock:
            return self._rotate_locked()

    def current(self) -> Tuple[str, int]:
        """Return ``(pin, seconds_remaining)``; rotates first if it has expired."""
        with self._lock:
            if time.time() >= self._expires:
                self._rotate_locked()
            return self._pin, max(0, int(self._expires - time.time()))

    def verify(self, candidate: str, ip: str) -> str:
        """Return ``"ok"``, ``"bad"`` or ``"rate_limited"``. A good PIN is consumed."""
        if self._ip.blocked(ip) or self._global.blocked("*"):
            return "rate_limited"
        with self._lock:
            if time.time() >= self._expires:
                self._rotate_locked()
            matches = hmac.compare_digest((candidate or "").encode("utf-8"), self._pin.encode("utf-8"))
            if matches:
                self._rotate_locked()  # single use
                self._ip.reset(ip)
                return "ok"
        self._ip.fail(ip)
        self._global.fail("*")
        if self._global.blocked("*"):
            # Someone is guessing: invalidate the PIN so guesses never accumulate.
            self.rotate()
            self._global.reset("*")
            self._ip.fail(ip)
        return "bad"

    def retry_after(self, ip: str) -> int:
        return max(self._ip.retry_after(ip), self._global.retry_after("*"))


# --------------------------------------------------------------------------- #
# Signed URLs (screenshots)
# --------------------------------------------------------------------------- #
def sign_path(secret: bytes, path: str, exp: int) -> str:
    return hmac.new(secret, f"{path}|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()[:40]


def verify_signature(secret: bytes, path: str, exp: int, sig: str) -> bool:
    if exp < int(time.time()):
        return False
    return hmac.compare_digest(sign_path(secret, path, exp), sig or "")


# --------------------------------------------------------------------------- #
# Key store
# --------------------------------------------------------------------------- #
class AuthService:
    """Admin key bootstrap plus per-device agent keys (all stored hashed)."""

    ADMIN_SETTING = "admin_key_hash"
    SECRET_SETTING = "signing_secret"

    def __init__(self, data_dir: Path, env_admin_key: Optional[str] = None):
        self.data_dir = Path(data_dir)
        self.env_admin_key = env_admin_key
        self._admin_hash: Optional[str] = None
        self._cache: Dict[str, Identity] = {}
        self._lock = threading.Lock()
        self.signing_secret: bytes = b""

    # -- bootstrap ---------------------------------------------------------- #
    @property
    def key_file(self) -> Path:
        return self.data_dir / "admin_key.txt"

    def bootstrap(self) -> Optional[str]:
        """Make sure an admin key and signing secret exist.

        Returns the plaintext admin key **only** when one was generated just now
        (so the caller can show it once). Otherwise returns ``None``.
        """
        secret_hex = database.get_setting(self.SECRET_SETTING)
        if not secret_hex:
            secret_hex = secrets.token_hex(32)
            database.set_setting(self.SECRET_SETTING, secret_hex)
        self.signing_secret = bytes.fromhex(secret_hex)

        if self.env_admin_key:
            self._admin_hash = hash_key(self.env_admin_key)
            database.set_setting(self.ADMIN_SETTING, self._admin_hash)
            return None

        stored = database.get_setting(self.ADMIN_SETTING)
        if stored:
            self._admin_hash = stored
            return None
        return self.reset_admin_key()

    def reset_admin_key(self) -> str:
        raw = new_key(ADMIN_PREFIX)
        self._admin_hash = hash_key(raw)
        database.set_setting(self.ADMIN_SETTING, self._admin_hash)
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.key_file.write_text(raw + "\n", encoding="utf-8")
            try:
                os.chmod(self.key_file, 0o600)
            except OSError:
                pass
        except OSError:
            pass
        return raw

    # -- verification ------------------------------------------------------- #
    def verify_admin(self, raw: Optional[str]) -> bool:
        if not raw or not self._admin_hash or len(raw) > 256:
            return False
        return hmac.compare_digest(hash_key(raw), self._admin_hash)

    def verify(self, raw: Optional[str]) -> Optional[Identity]:
        if not raw or len(raw) > 256:
            return None
        digest = hash_key(raw)
        if self._admin_hash and hmac.compare_digest(digest, self._admin_hash):
            return Identity("parent")
        with self._lock:
            cached = self._cache.get(digest)
        if cached:
            return cached
        record = database.find_api_key(digest)
        if record and record.get("role") == "agent" and record.get("device_id"):
            identity = Identity("agent", record["device_id"])
            with self._lock:
                self._cache[digest] = identity
            return identity
        return None

    # -- agent keys --------------------------------------------------------- #
    def issue_agent_key(self, device_id: str) -> str:
        raw = new_key(AGENT_PREFIX)
        digest = hash_key(raw)
        database.store_api_key(digest, "agent", device_id)
        with self._lock:
            self._cache[digest] = Identity("agent", device_id)
        return raw

    def revoke_device(self, device_id: str) -> None:
        database.delete_api_keys_for_device(device_id)
        with self._lock:
            for digest in [h for h, ident in self._cache.items() if ident.device_id == device_id]:
                self._cache.pop(digest, None)

    # -- signed URLs -------------------------------------------------------- #
    def sign(self, path: str, ttl_s: int = 600) -> Tuple[int, str]:
        exp = int(time.time()) + ttl_s
        return exp, sign_path(self.signing_secret, path, exp)

    def check_signature(self, path: str, exp: int, sig: str) -> bool:
        return verify_signature(self.signing_secret, path, exp, sig)
