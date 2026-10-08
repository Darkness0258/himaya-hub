"""Himaya Hub SQLite Database Storage.

Provides persistent storage for:
- Devices registry
- Security & activity event logs
- Queued remote commands
- Content filtering rules & schedules
- Snapshot metadata
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DB_PATH = Path(__file__).parent / "himaya.db"
DATABASE_URL = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL")


_pg_available: Optional[bool] = None


def is_postgres() -> bool:
    global _pg_available
    if not DATABASE_URL:
        return False
    if _pg_available is False:
        return False
    return True


def _safe_json_load(val: Any, default: Any = None) -> Any:
    if val is None:
        return default if default is not None else {}
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default if default is not None else {}


class CursorWrapper:
    """Wraps database cursor to provide unified parameter placeholders and lastrowid across SQLite and PostgreSQL."""
    def __init__(self, raw_cursor, is_pg: bool):
        self._cur = raw_cursor
        self._is_pg = is_pg
        self.lastrowid = getattr(raw_cursor, "lastrowid", None)

    def execute(self, sql: str, params: Any = ()):
        if self._is_pg:
            # PostgreSQL requires %s instead of SQLite's ? placeholder
            sql = sql.replace("?", "%s")
            if isinstance(params, list):
                params = tuple(params)
            sql_clean = sql.strip().rstrip(";").strip()
            # If INSERT into a table with serial ID, capture generated ID
            if sql_clean.upper().startswith("INSERT") and "RETURNING" not in sql_clean.upper() and "ON CONFLICT" not in sql_clean.upper():
                try:
                    self._cur.execute(sql_clean + " RETURNING id;", params)
                    row = self._cur.fetchone()
                    if row:
                        if isinstance(row, dict) and "id" in row:
                            self.lastrowid = row["id"]
                        elif isinstance(row, (tuple, list)) and len(row) > 0:
                            self.lastrowid = row[0]
                    return self
                except Exception:
                    pass
        self._cur.execute(sql, params)
        if not self._is_pg:
            self.lastrowid = getattr(self._cur, "lastrowid", None)
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class DBConnection:
    """Unified context manager supporting both SQLite and PostgreSQL (Supabase)."""
    def __init__(self):
        global _pg_available
        self.is_pg = is_postgres()
        if self.is_pg:
            try:
                import psycopg2
                from psycopg2.extras import RealDictCursor
                url = DATABASE_URL
                if url.startswith("postgres://"):
                    url = url.replace("postgres://", "postgresql://", 1)
                self.conn = psycopg2.connect(url, cursor_factory=RealDictCursor, connect_timeout=5)
                _pg_available = True
            except Exception as e:
                print(f"[Database Warning] Could not connect to PostgreSQL: {e}")
                print("[Database Warning] Gracefully falling back to local SQLite database.")
                _pg_available = False
                self.is_pg = False
                self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
                self.conn.row_factory = sqlite3.Row
        else:
            self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            self.conn.row_factory = sqlite3.Row

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.conn.close()

    def cursor(self):
        return CursorWrapper(self.conn.cursor(), self.is_pg)

    def execute(self, sql: str, params: tuple = ()):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def executescript(self, script: str):
        if self.is_pg:
            cur = self.conn.cursor()
            cur.execute(script)
        else:
            self.conn.executescript(script)

    def commit(self):
        self.conn.commit()


def get_connection():
    return DBConnection()



def init_db() -> None:
    """Initialize database tables and indexes."""
    try:
        with get_connection() as conn:
            if conn.is_pg:
                conn.executescript("""
                CREATE TABLE IF NOT EXISTS devices (
                    id SERIAL PRIMARY KEY,
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
                    id SERIAL PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS commands (
                    id SERIAL PRIMARY KEY,
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
                    id SERIAL PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    timestamp TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_dev ON events(device_id);
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_cmds_dev ON commands(device_id, status);
            """)
            else:
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

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_dev ON events(device_id);
                CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_cmds_dev ON commands(device_id, status);
            """)
            conn.commit()
    except Exception as e:
        print(f"[Database Error] Table initialization encountered error: {e}")


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


def delete_device(device_id: str) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
        cursor.execute("DELETE FROM commands WHERE device_id = ?", (device_id,))
        cursor.execute("DELETE FROM rules WHERE device_id = ?", (device_id,))
        cursor.execute("DELETE FROM events WHERE device_id = ?", (device_id,))
        conn.commit()
        return True


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
            parsed_data = _safe_json_load(r["data"], {})
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
        cursor.execute(f"UPDATE commands SET status = 'consumed' WHERE id IN ({','.join(['?']*len(ids))})", tuple(ids))
        conn.commit()

        results = []
        for r in rows:
            p = _safe_json_load(r["payload"], {})
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
            "blocked_categories": _safe_json_load(row["blocked_categories"], ["adult", "gambling"]),
            "blocked_domains": _safe_json_load(row["blocked_domains"], []),
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
# --- System & Network Settings Operations ---
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row["value"]
        return default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()

