"""Website-filtering policy for Himaya.

This module is deliberately pure: no sockets, no database. The DNS sinkhole, the
REST API (which hands the effective blocklist to the Windows agent) and the unit
tests all share the exact same decision logic.

Concepts
--------
* **Categories** are named domain sets (``adult``, ``gambling``, ``social``...).
  Built-in starter lists ship with the hub; drop ``<name>.txt`` files into
  ``data/blocklists/`` to add or extend categories (one domain per line, hosts
  files and ``||domain^`` adblock lines are understood).
* **Per-device rules** pick categories, add custom blocked domains, add allowed
  exceptions and optionally a bedtime window.
* A device can also be **paused** by the parent. A paused device (or one inside
  its bedtime window) gets every lookup sinkholed except the hub itself.
"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Set

try:  # Python 3.9+; on Windows it needs the ``tzdata`` package
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore

# Starter lists. They are intentionally short and conservative; extend them with
# files in data/blocklists/ (see module docstring).
BUILTIN_CATEGORIES: Dict[str, Set[str]] = {
    "adult": {
        "pornhub.com", "xvideos.com", "xnxx.com", "xhamster.com", "redtube.com", "youporn.com",
        "spankbang.com", "chaturbate.com", "stripchat.com", "onlyfans.com", "eporner.com",
        "brazzers.com", "bongacams.com", "livejasmin.com", "cam4.com", "omegle.com", "ome.tv",
    },
    "gambling": {
        "bet365.com", "gambling.com", "1xbet.com", "betway.com", "pokerstars.com", "draftkings.com",
        "fanduel.com", "stake.com", "williamhill.com", "unibet.com", "888casino.com", "bovada.lv",
        "betfair.com", "ladbrokes.com", "paddypower.com", "22bet.com", "melbet.com", "mostbet.com",
        "parimatch.com",
    },
    "social": {
        "tiktok.com", "tiktokcdn.com", "byteoversea.com", "musical.ly", "instagram.com", "facebook.com",
        "fb.com", "snapchat.com", "x.com", "twitter.com", "reddit.com", "kick.com", "discord.com",
        "discord.gg", "twitch.tv", "tumblr.com",
    },
    "gaming": {
        "roblox.com", "rbxcdn.com", "steampowered.com", "steamcommunity.com", "epicgames.com",
        "fortnite.com", "minecraft.net", "riotgames.com", "leagueoflegends.com", "battle.net",
        "blizzard.com", "ea.com", "xbox.com", "playstation.com", "ubisoft.com", "supercell.com",
        "garena.com",
    },
    "video": {
        "youtube.com", "youtu.be", "ytimg.com", "googlevideo.com", "netflix.com", "primevideo.com",
        "disneyplus.com", "vimeo.com", "dailymotion.com", "hotstar.com",
    },
}

CATEGORY_LABELS: Dict[str, str] = {
    "adult": "Adult content",
    "gambling": "Gambling",
    "social": "Social media",
    "gaming": "Games",
    "video": "Video streaming",
}

# What an unknown client (not an enrolled device) gets from the hub DNS.
DEFAULT_CLIENT_CATEGORIES = ("adult", "gambling")

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9_](?:[a-z0-9_-]{0,61}[a-z0-9_])?\.)+[a-z0-9-]{2,63}$")
_CATEGORY_NAME_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def normalize_domain(value: str) -> str:
    """Return a bare lowercase domain, or ``""`` if the input is not a valid domain."""
    v = (value or "").strip().lower()
    if not v:
        return ""
    if "://" in v:
        v = v.split("://", 1)[1]
    v = re.split(r"[/?#]", v, maxsplit=1)[0]
    v = v.rsplit("@", 1)[-1]
    v = v.split(":", 1)[0]
    v = v.rstrip(".")
    if v.startswith("*."):
        v = v[2:]
    if v.startswith("www."):
        v = v[4:]
    return v if _DOMAIN_RE.match(v) else ""


def parse_blocklist_text(text: str) -> Set[str]:
    """Parse plain lists, hosts-format lines and ``||domain^`` adblock rules."""
    found: Set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("!"):
            continue
        if line.startswith("||"):
            line = line[2:].split("^", 1)[0]
        else:
            parts = line.split()
            if len(parts) >= 2 and parts[0] in ("0.0.0.0", "127.0.0.1", "::1", "::"):
                line = parts[1]
            else:
                line = parts[0]
        domain = normalize_domain(line)
        if domain:
            found.add(domain)
    return found


def domain_matches(domain: str, domains: Iterable[str]) -> bool:
    """True if ``domain`` or any parent domain (with at least two labels) is in ``domains``."""
    pool = domains if isinstance(domains, (set, frozenset)) else set(domains)
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        if ".".join(parts[i:]) in pool:
            return True
    return False


def hhmm_to_minutes(value: str) -> Optional[int]:
    match = _HHMM_RE.match(value or "")
    if not match:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def in_window(now_minutes: int, start: str, end: str) -> bool:
    """Is ``now`` inside [start, end)? Windows may cross midnight (e.g. 21:00 -> 07:00)."""
    a, b = hhmm_to_minutes(start), hhmm_to_minutes(end)
    if a is None or b is None or a == b:
        return False
    if a < b:
        return a <= now_minutes < b
    return now_minutes >= a or now_minutes < b


@dataclass(frozen=True)
class DevicePolicy:
    device_id: str = ""
    paused: bool = False
    categories: FrozenSet[str] = frozenset(DEFAULT_CLIENT_CATEGORIES)
    blocked: FrozenSet[str] = frozenset()
    allowed: FrozenSet[str] = frozenset()
    bedtime_enabled: bool = False
    bedtime_start: str = "21:00"
    bedtime_end: str = "07:00"


@dataclass(frozen=True)
class Decision:
    blocked: bool
    reason: str = ""
    device_id: Optional[str] = None


class FilterEngine:
    """Thread-safe policy lookup shared by the DNS server and the REST layer."""

    def __init__(self, blocklist_dir: Optional[Path] = None, timezone: Optional[str] = None, always_allow: Iterable[str] = ()):
        self.categories: Dict[str, Set[str]] = {name: set(domains) for name, domains in BUILTIN_CATEGORIES.items()}
        self._lock = threading.RLock()
        self._by_device: Dict[str, DevicePolicy] = {}
        self._by_ip: Dict[str, str] = {}
        self._default = DevicePolicy()
        self._tz = None
        if timezone and ZoneInfo is not None:
            try:
                self._tz = ZoneInfo(timezone)
            except Exception:
                self._tz = None
        self._always_allow: Set[str] = set()
        self.set_always_allow(always_allow)
        if blocklist_dir:
            self.load_custom_lists(blocklist_dir)

    # -- configuration ------------------------------------------------------ #
    def load_custom_lists(self, directory: Path) -> int:
        """Load ``*.txt`` category files. Returns the number of lists loaded."""
        loaded = 0
        try:
            files = sorted(Path(directory).glob("*.txt"))
        except OSError:
            return 0
        for file in files:
            name = file.stem.lower()
            if not _CATEGORY_NAME_RE.match(name):
                continue
            try:
                domains = parse_blocklist_text(file.read_text(encoding="utf-8", errors="ignore"))
            except OSError:
                continue
            with self._lock:
                self.categories.setdefault(name, set()).update(domains)
            loaded += 1
        return loaded

    def set_always_allow(self, domains: Iterable[str]) -> None:
        cleaned = {normalize_domain(d) for d in domains}
        with self._lock:
            self._always_allow = {d for d in cleaned if d}

    def category_info(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [
                {"name": name, "label": CATEGORY_LABELS.get(name, name.replace("_", " ").replace("-", " ").capitalize()), "count": len(domains)}
                for name, domains in sorted(self.categories.items())
            ]

    # -- time --------------------------------------------------------------- #
    def now(self) -> datetime:
        return datetime.now(self._tz) if self._tz else datetime.now()

    def _minutes(self, now: Optional[datetime] = None) -> int:
        now = now or self.now()
        return now.hour * 60 + now.minute

    def bedtime_active(self, rules: Dict[str, Any], now: Optional[datetime] = None) -> bool:
        if not rules.get("bedtime_enabled"):
            return False
        return in_window(self._minutes(now), rules.get("bedtime_start", "21:00"), rules.get("bedtime_end", "07:00"))

    # -- policy table ------------------------------------------------------- #
    @staticmethod
    def policy_from_rules(device_id: str, rules: Dict[str, Any], paused: bool = False) -> DevicePolicy:
        return DevicePolicy(
            device_id=device_id,
            paused=bool(paused),
            categories=frozenset(str(c).lower() for c in rules.get("blocked_categories", [])),
            blocked=frozenset(d for d in (normalize_domain(x) for x in rules.get("blocked_domains", [])) if d),
            allowed=frozenset(d for d in (normalize_domain(x) for x in rules.get("allowed_domains", [])) if d),
            bedtime_enabled=bool(rules.get("bedtime_enabled")),
            bedtime_start=rules.get("bedtime_start", "21:00"),
            bedtime_end=rules.get("bedtime_end", "07:00"),
        )

    def refresh(self, devices: Iterable[Dict[str, Any]], rules_by_device: Dict[str, Dict[str, Any]], default_rules: Optional[Dict[str, Any]] = None) -> None:
        """Rebuild the lookup tables from the database snapshot."""
        by_device: Dict[str, DevicePolicy] = {}
        by_ip: Dict[str, str] = {}
        for device in devices:
            device_id = device["device_id"]
            rules = rules_by_device.get(device_id) or default_rules or {}
            policy = self.policy_from_rules(device_id, rules, paused=bool(device.get("paused")))
            by_device[device_id] = policy
            if device.get("ip"):
                by_ip[device["ip"]] = device_id
        with self._lock:
            self._by_device = by_device
            self._by_ip = by_ip

    def policy_for_ip(self, ip: str) -> DevicePolicy:
        with self._lock:
            device_id = self._by_ip.get(ip)
            return self._by_device.get(device_id, self._default) if device_id else self._default

    # -- decisions ---------------------------------------------------------- #
    def decide(self, client_ip: str, domain: str, now: Optional[datetime] = None) -> Decision:
        domain = normalize_domain(domain)
        if not domain:
            return Decision(False)
        policy = self.policy_for_ip(client_ip)
        device_id = policy.device_id or None
        with self._lock:
            always = self._always_allow
            if always and domain_matches(domain, always):
                return Decision(False, "hub", device_id)
            if policy.paused:
                return Decision(True, "paused", device_id)
            if policy.bedtime_enabled and in_window(self._minutes(now), policy.bedtime_start, policy.bedtime_end):
                return Decision(True, "bedtime", device_id)
            if policy.allowed and domain_matches(domain, policy.allowed):
                return Decision(False, "allowed", device_id)
            if policy.blocked and domain_matches(domain, policy.blocked):
                return Decision(True, "custom", device_id)
            for category in sorted(policy.categories):
                domains = self.categories.get(category)
                if domains and domain_matches(domain, domains):
                    return Decision(True, f"category:{category}", device_id)
        return Decision(False, "", device_id)

    def effective_blocked_domains(self, rules: Dict[str, Any], limit: int = 3000) -> List[str]:
        """Flatten categories + custom domains - allowed, for agents that block via the hosts file."""
        policy = self.policy_from_rules("", rules)
        out: Set[str] = set(policy.blocked)
        with self._lock:
            for category in policy.categories:
                out.update(self.categories.get(category, ()))
        out = {d for d in out if not (policy.allowed and domain_matches(d, policy.allowed))}
        return sorted(out)[:limit]
