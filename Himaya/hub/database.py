"""Himaya Hub SQLite Database Storage.

Provides persistent storage for:
- Devices registry
- Security & activity event logs
- Queued remote commands
- Content filtering rules & schedules
- Snapshot metadata
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "himaya.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Initialize database tables and indexes."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                ip TEXT,
                owner_type TEXT DEFAULT 'child',
                status TEXT DEFAULT 'offline',
                last_seen TEXT,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                type TEXT NOT NULL,
                data TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                action TEXT NOT NULL,
                payload TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS rules (
                device_id TEXT PRIMARY KEY,
                blocked_categories TEXT DEFAULT '["adult", "gambling"]',
                blocked_domains TEXT DEFAULT '[]',
                bedtime_enabled INTEGER DEFAULT 0,
                bedtime_start TEXT DEFAULT '21:00',
                bedtime_end TEXT DEFAULT '07:00',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                timestamp TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_events_dev ON events(device_id);
            CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_cmds_dev ON commands(device_id, status);
        """)
        conn.commit()


def clear_all_data() -> None:
    """Clear all records from database tables (useful for test isolation)."""
    with get_connection() as conn:
        conn.executescript("""
            DELETE FROM devices;
            DELETE FROM events;
            DELETE FROM commands;
            DELETE FROM rules;
            DELETE FROM snapshots;
        """)
        conn.commit()


# --- Device Operations ---
def get_device(device_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM devices WHERE device_id = ?", (device_id,))
        row = cursor.fetchone()
        if not row:
            return None
        return dict(row)


def list_devices() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM devices ORDER BY id ASC")
        return [dict(r) for r in cursor.fetchall()]


def insert_device(device_id: str, name: str, platform: str, owner_type: str = "child", ip: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO devices (device_id, name, platform, ip, owner_type, status, last_seen, created_at)
            VALUES (?, ?, ?, ?, ?, 'offline', NULL, ?)
        """, (device_id, name, platform, ip, owner_type, now))
        conn.commit()
        dev_id = cursor.lastrowid
        return {
            "id": dev_id,
            "device_id": device_id,
            "name": name,
            "platform": platform,
            "ip": ip,
            "owner_type": owner_type,
            "status": "offline",
            "last_seen": None,
            "created_at": now
        }


def update_device_status(device_id: str, status: str, ip: Optional[str] = None, last_seen: Optional[str] = None) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        fields = ["status = ?"]
        params = [status]
        if ip:
            fields.append("ip = ?")
            params.append(ip)
        if last_seen:
            fields.append("last_seen = ?")
            params.append(last_seen)
        params.append(device_id)

        sql = f"UPDATE devices SET {', '.join(fields)} WHERE device_id = ?"
        cursor.execute(sql, params)
        conn.commit()


# --- Event Operations ---
def insert_event(device_id: str, event_type: str, data: dict, timestamp: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO events (device_id, type, data, timestamp)
            VALUES (?, ?, ?, ?)
        """, (device_id, event_type, json.dumps(data), timestamp))
        conn.commit()
        return cursor.lastrowid


def list_events(limit: int = 50) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, device_id, type, data, timestamp
            FROM events
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        result = []
        for r in reversed(rows):
            try:
                parsed_data = json.loads(r["data"])
            except Exception:
                parsed_data = {}
            result.append({
                "id": r["id"],
                "device_id": r["device_id"],
                "type": r["type"],
                "data": parsed_data,
                "timestamp": r["timestamp"]
            })
        return result


# --- Command Queue Operations ---
def queue_command(device_id: str, action: str, payload: dict) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO commands (device_id, action, payload, status, created_at)
            VALUES (?, ?, ?, 'pending', ?)
        """, (device_id, action, json.dumps(payload), now))
        conn.commit()
        return cursor.lastrowid


def pop_pending_commands(device_id: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, action, payload, created_at
            FROM commands
            WHERE device_id = ? AND status = 'pending'
            ORDER BY id ASC
        """, (device_id,))
        rows = cursor.fetchall()
        if not rows:
            return []

        ids = [r["id"] for r in rows]
        cursor.execute(f"UPDATE commands SET status = 'consumed' WHERE id IN ({','.join(['?']*len(ids))})", ids)
        conn.commit()

        results = []
        for r in rows:
            try:
                p = json.loads(r["payload"])
            except Exception:
                p = {}
            results.append({
                "id": r["id"],
                "action": r["action"],
                "payload": p,
                "timestamp": r["created_at"]
            })
        return results


# --- Rules & Filtering ---
def get_device_rules(device_id: str) -> Dict[str, Any]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM rules WHERE device_id = ?", (device_id,))
        row = cursor.fetchone()
        if not row:
            # Return default rules
            return {
                "device_id": device_id,
                "blocked_categories": ["adult", "gambling"],
                "blocked_domains": ["tiktok.com", "kick.com"],
                "bedtime_enabled": True,
                "bedtime_start": "21:00",
                "bedtime_end": "07:00"
            }
        return {
            "device_id": row["device_id"],
            "blocked_categories": json.loads(row["blocked_categories"]),
            "blocked_domains": json.loads(row["blocked_domains"]),
            "bedtime_enabled": bool(row["bedtime_enabled"]),
            "bedtime_start": row["bedtime_start"],
            "bedtime_end": row["bedtime_end"]
        }


def save_device_rules(device_id: str, rules: Dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO rules (device_id, blocked_categories, blocked_domains, bedtime_enabled, bedtime_start, bedtime_end, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                blocked_categories = excluded.blocked_categories,
                blocked_domains = excluded.blocked_domains,
                bedtime_enabled = excluded.bedtime_enabled,
                bedtime_start = excluded.bedtime_start,
                bedtime_end = excluded.bedtime_end,
                updated_at = excluded.updated_at
        """, (
            device_id,
            json.dumps(rules.get("blocked_categories", [])),
            json.dumps(rules.get("blocked_domains", [])),
            1 if rules.get("bedtime_enabled") else 0,
            rules.get("bedtime_start", "21:00"),
            rules.get("bedtime_end", "07:00"),
            now
        ))
        conn.commit()


# --- Snapshot Operations ---
def record_snapshot(device_id: str, filename: str, file_path: str) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO snapshots (device_id, filename, file_path, timestamp)
            VALUES (?, ?, ?, ?)
        """, (device_id, filename, file_path, now))
        conn.commit()
        return {
            "id": cursor.lastrowid,
            "device_id": device_id,
            "filename": filename,
            "timestamp": now
        }


def list_snapshots(device_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        if device_id:
            cursor.execute("""
                SELECT id, device_id, filename, file_path, timestamp
                FROM snapshots
                WHERE device_id = ?
                ORDER BY id DESC
                LIMIT ?
            """, (device_id, limit))
        else:
            cursor.execute("""
                SELECT id, device_id, filename, file_path, timestamp
                FROM snapshots
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
        return [dict(r) for r in cursor.fetchall()]
