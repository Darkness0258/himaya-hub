"""Himaya data models — Pydantic schemas for device registry and events."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BLOCKED = "blocked"
    PAUSED = "paused"
    LOCKED = "locked"


class DeviceCreate(BaseModel):
    name: str
    platform: str  # "android" | "windows"
    device_id: str  # unique per device
    ip: Optional[str] = None
    owner_type: str = "child"  # "child" | "adult"


class Device(DeviceCreate):
    id: int
    status: DeviceStatus = DeviceStatus.OFFLINE
    last_seen: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class EventType(str, Enum):
    HEARTBEAT = "heartbeat"
    VPN_ATTEMPT = "vpn_attempt"
    POLICY_SYNC = "policy_sync"
    SCREENSHOT = "screenshot"
    DNS_BLOCK = "dns_block"
    DEVICE_LOCKED = "device_locked"
    DEVICE_UNLOCKED = "device_unlocked"
    DEVICE_WENT_DARK = "device_went_dark"


class Event(BaseModel):
    id: Optional[int] = None
    device_id: str
    type: EventType
    data: dict
    timestamp: datetime

    class Config:
        from_attributes = True


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