"""Himaya request/response schemas.

Everything that crosses the network is validated here: identifier formats,
string lengths, domain syntax and payload sizes. The first version accepted any
string anywhere, which made values like device names and domains an injection
surface for the HTML/PowerShell pages the hub generates.
"""
from __future__ import annotations

import ipaddress
import json
import re
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from filtering import normalize_domain

DEVICE_ID_PATTERN = r"^[A-Za-z0-9_-]{3,64}$"
_CATEGORY_RE = re.compile(r"^[a-z0-9_-]{1,32}$")
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

Platform = Literal["android", "windows", "ios", "macos", "linux"]
OwnerType = Literal["child", "adult"]


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    # Kept so older clients that still know these names do not break. The hub now
    # reports lock/pause as separate booleans on the device.
    BLOCKED = "blocked"
    PAUSED = "paused"
    LOCKED = "locked"


class EventType(str, Enum):
    HEARTBEAT = "heartbeat"
    VPN_ATTEMPT = "vpn_attempt"
    POLICY_SYNC = "policy_sync"
    SCREENSHOT = "screenshot"
    DNS_BLOCK = "dns_block"
    DEVICE_LOCKED = "device_locked"
    DEVICE_UNLOCKED = "device_unlocked"
    DEVICE_WENT_DARK = "device_went_dark"
    DEVICE_ONLINE = "device_online"
    DEVICE_PAIRED = "device_paired"
    REMOTE_ACTION = "remote_action"
    AGENT_STOPPED = "agent_stopped"
    ENFORCEMENT_NOTICE = "enforcement_notice"


class RemoteAction(str, Enum):
    LOCK = "lock"
    UNLOCK = "unlock"
    BLOCK_INTERNET = "block_internet"
    UNBLOCK_INTERNET = "unblock_internet"
    PAUSE = "pause"
    UNPAUSE = "unpause"
    FORCE_CLOSE_APP = "force_close_app"
    PUSH_NOTIFICATION = "push_notification"
    SNAPSHOT = "snapshot"
    WIPE = "wipe"


def _clean_text(value: str, max_len: int) -> str:
    value = _CONTROL_RE.sub("", value or "").strip()
    if len(value) > max_len:
        value = value[:max_len]
    return value


def _check_ip(value: Optional[str]) -> Optional[str]:
    if value in (None, ""):
        return None
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError as exc:
        raise ValueError("ip must be a valid IPv4/IPv6 address") from exc


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    platform: Platform
    device_id: str = Field(pattern=DEVICE_ID_PATTERN)
    ip: Optional[str] = None
    owner_type: OwnerType = "child"

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = _clean_text(v, 80)
        if not v:
            raise ValueError("name cannot be empty")
        return v

    _ip = field_validator("ip")(lambda cls, v: _check_ip(v))


class DevicePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    owner_type: Optional[OwnerType] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = _clean_text(v, 80)
        if not v:
            raise ValueError("name cannot be empty")
        return v


class PairRequest(BaseModel):
    pin: str = Field(pattern=r"^\d{6}$")
    name: str = Field(min_length=1, max_length=80)
    platform: Platform = "android"
    owner_type: OwnerType = "child"
    ip: Optional[str] = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        v = _clean_text(v, 80)
        if not v:
            raise ValueError("name cannot be empty")
        return v

    _ip = field_validator("ip")(lambda cls, v: _check_ip(v))


def _lenient_ip(value: Any) -> Optional[str]:
    """For heartbeats: an unusable IP is ignored (the hub uses the socket address instead)."""
    if not isinstance(value, str):
        return None
    try:
        return _check_ip(value)
    except ValueError:
        return None


def _clean_caps(value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Capabilities are small flat dicts of scalars (what this agent can enforce)."""
    if value is None:
        return None
    if len(value) > 24:
        raise ValueError("too many capability entries")
    cleaned: Dict[str, Any] = {}
    for key, item in value.items():
        key = str(key)[:40]
        if isinstance(item, (bool, int, float)) or item is None:
            cleaned[key] = item
        elif isinstance(item, str):
            cleaned[key] = _clean_text(item, 64)
        # nested values are ignored on purpose
    return cleaned


class HeartbeatIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ip: Optional[str] = None
    agent_version: Optional[str] = Field(default=None, max_length=32)
    caps: Optional[Dict[str, Any]] = None

    _ip = field_validator("ip", mode="before")(lambda cls, v: _lenient_ip(v))
    _caps = field_validator("caps")(lambda cls, v: _clean_caps(v))


class DnsBlockIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    host: str = Field(default="", max_length=253)


class VpnAttemptIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    interface: str = Field(default="", max_length=120)


class AgentEventIn(BaseModel):
    type: Literal["agent_stopped", "enforcement_notice"]
    data: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _small(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if len(json.dumps(v, default=str)) > 2048:
            raise ValueError("event data too large")
        return v


class RulesIn(BaseModel):
    """Partial update: only the fields that are present are changed."""

    model_config = ConfigDict(extra="ignore")
    blocked_categories: Optional[List[str]] = None
    blocked_domains: Optional[List[str]] = None
    allowed_domains: Optional[List[str]] = None
    bedtime_enabled: Optional[bool] = None
    bedtime_start: Optional[str] = None
    bedtime_end: Optional[str] = None
    snapshot_interval_s: Optional[int] = None

    @field_validator("blocked_categories")
    @classmethod
    def _categories(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if len(v) > 40:
            raise ValueError("too many categories")
        out: List[str] = []
        for item in v:
            name = str(item).strip().lower()
            if not _CATEGORY_RE.match(name):
                raise ValueError(f"invalid category name: {item!r}")
            if name not in out:
                out.append(name)
        return out

    @field_validator("blocked_domains", "allowed_domains")
    @classmethod
    def _domains(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if len(v) > 500:
            raise ValueError("too many domains (max 500)")
        out: List[str] = []
        for item in v:
            domain = normalize_domain(str(item))
            if not domain:
                raise ValueError(f"not a valid domain: {str(item)[:60]!r}")
            if domain not in out:
                out.append(domain)
        return out

    @field_validator("bedtime_start", "bedtime_end")
    @classmethod
    def _hhmm(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not _HHMM_RE.match(v):
            raise ValueError("time must look like HH:MM (24-hour)")
        return v

    @field_validator("snapshot_interval_s")
    @classmethod
    def _interval(cls, v: Optional[int]) -> Optional[int]:
        if v is None:
            return v
        if v != 0 and not (60 <= v <= 3600):
            raise ValueError("snapshot_interval_s must be 0 (off) or between 60 and 3600 seconds")
        return v


class ActionRequest(BaseModel):
    action: RemoteAction
    payload: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("payload")
    @classmethod
    def _small(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        if len(json.dumps(v, default=str)) > 2048:
            raise ValueError("payload too large")
        return v


class PublicUrlIn(BaseModel):
    url: str = Field(default="", max_length=300)
