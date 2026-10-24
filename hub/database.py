"""Himaya hub storage.

SQLite is the default (zero setup, local-first). PostgreSQL / Supabase is
optional: set ``DATABASE_URL`` and the same code runs against it.

What changed compared to the first version
------------------------------------------
* The SQLite file now lives in the data directory (``hub/data/himaya.db``) so a
  Docker volume really persists it. Before, it sat next to the code and was lost
  whenever the container was recreated.
* SQLite runs in WAL mode with a busy timeout (the DNS thread, the watchdog and
  request threads all write concurrently).
* Rows are normalised: PostgreSQL ``TIMESTAMPTZ`` values become ISO strings and
  flags become real booleans, so the rest of the code never sees driver quirks.
* ``save_device_rules`` merges instead of replacing, so a partial update no
  longer wipes the blocklist.
* ``pop_pending_commands`` is a single atomic ``UPDATE ... RETURNING`` so two
  concurrent polls can never receive the same command.
* New tables: ``api_keys`` (hashed keys, never plaintext). New columns:
  ``devices.locked/paused/caps/agent_version`` and ``rules.allowed_domains /
  snapshot_interval_s``. Connectivity (``status``) is now separate from the
  parent-controlled state (``locked`` / ``paused``).
"""
from __future__ import annotations

import json
import logging
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

import config

log = logging.getLogger("himaya.db")

_db_path: Path = config.BASE_DIR / "data" / "himaya.db"
_pg_pool = None
_pg_lock = threading.Lock()
_pg_retry_at = 0.0
_pg_failed_logged = False
_bool_kinds: Dict[tuple, str] = {}

DEFAULT_RULES: Dict[str, Any] = {
    "blocked_categories": ["adult", "gambling"],
    "blocked_domains": ["tiktok.com", "kick.com"],
    "allowed_domains": [],
    "bedtime_enabled": False,
    "bedtime_start": "21:00",
    "bedtime_end": "07:00",
    "snapshot_interval_s": 300,
}


class DuplicateDevice(Exception):
    """Raised when a device_id already exists."""


# --------------------------------------------------------------------------- #
# Configuration / connection handling
# --------------------------------------------------------------------------- #
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def configure(db_path: Path) -> None:
    """Point the storage layer at ``db_path`` (also resets cached PostgreSQL state)."""
    global _db_path, _pg_pool, _pg_retry_at, _pg_failed_logged
    _db_path = Path(db_path)
    _db_path.parent.mkdir(parents=True, exist_ok=True)
    _bool_kinds.clear()
    _pg_retry_at = 0.0
    _pg_failed_logged = False
    with _pg_lock:
        if _pg_pool is not None:
            try:
                _pg_pool.closeall()
            except Exception:  # pragma: no cover - best effort
                pass
            _pg_pool = None

    # One-time migration of the pre-2.0 database that lived next to the code.
    legacy = config.BASE_DIR / "himaya.db"
    default_location = (config.BASE_DIR / "data" / "himaya.db").resolve()
    if _db_path.resolve() == default_location and not _db_path.exists() and legacy.exists():
        try:
            shutil.copy2(legacy, _db_path)
            log.info("Migrated legacy database %s -> %s", legacy, _db_path)
        except OSError as exc:  # pragma: no cover
            log.warning("Could not migrate legacy database: %s", exc)


def get_database_url() -> Optional[str]:
    import os

    url = os.environ.get("DATABASE_URL") or os.environ.get("SUPABASE_DB_URL") or ""
    url = url.strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url or None


def _get_pg_pool():
    """Create (once) a small connection pool, or return None if unavailable."""
    global _pg_pool, _pg_retry_at, _pg_failed_logged
    url = get_database_url()
    if not url:
        return None
    if _pg_pool is not None:
        return _pg_pool
    if time.time() < _pg_retry_at:
        return None
    with _pg_lock:
        if _pg_pool is not None:
            return _pg_pool
        try:
            from psycopg2.extras import RealDictCursor
            from psycopg2.pool import ThreadedConnectionPool

            _pg_pool = ThreadedConnectionPool(1, 8, dsn=url, connect_timeout=5, cursor_factory=RealDictCursor)
            _pg_failed_logged = False
            log.info("Connected to PostgreSQL.")
        except Exception as exc:  # network down, bad password, driver missing...
            _pg_retry_at = time.time() + 60
            if not _pg_failed_logged:
                log.warning("PostgreSQL unavailable (%s). Using local SQLite and retrying in 60s.", exc)
                _pg_failed_logged = True
            return None
    return _pg_pool


def backend_name() -> str:
    return "postgres" if _get_pg_pool() is not None else "sqlite"


class _Cursor:
    """Thin wrapper: ``?`` placeholders everywhere, converted for PostgreSQL."""

    def __init__(self, raw, is_pg: bool):
        self._cur = raw
        self._is_pg = is_pg

    def execute(self, sql: str, params: Sequence[Any] = ()):
        if self._is_pg:
            sql = sql.replace("?", "%s")
        self._cur.execute(sql, tuple(params))
        return self

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return getattr(self._cur, "lastrowid", None)


class DBConnection:
    """Context manager: commits on success, rolls back on error, always releases."""

    def __init__(self):
        self.is_pg = False
        self._pool = _get_pg_pool()
        if self._pool is not None:
            try:
                self.conn = self._pool.getconn()
                self.is_pg = True
            except Exception as exc:
                log.warning("Could not get a PostgreSQL connection (%s); falling back to SQLite.", exc)
                self._pool = None
        if not self.is_pg:
            self.conn = sqlite3.connect(str(_db_path), timeout=10, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
            self.conn.execute("PRAGMA busy_timeout=10000")

    def __enter__(self) -> "DBConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            if self.is_pg and self._pool is not None:
                try:
                    self._pool.putconn(self.conn)
                except Exception:  # pragma: no cover
                    pass
            else:
                self.conn.close()

    def cursor(self) -> _Cursor:
        return _Cursor(self.conn.cursor(), self.is_pg)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> _Cursor:
        return self.cursor().execute(sql, params)


def get_connection() -> DBConnection:
    return DBConnection()


# --------------------------------------------------------------------------- #
# Row helpers
# --------------------------------------------------------------------------- #
def _safe_json_load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _row(row: Any) -> Dict[str, Any]:
    """Convert a driver row to a plain dict with ISO timestamps."""
    data = dict(row)
    for key, value in list(data.items()):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            data[key] = value.astimezone(timezone.utc).isoformat()
    return data


def _bool_kind(conn: DBConnection, table: str, column: str) -> str:
    """Return 'bool' if the column is a real boolean (Supabase SQL file), else 'int'."""
    key = (table, column)
    if key in _bool_kinds:
        return _bool_kinds[key]
    kind = "int"
    if conn.is_pg:
        row = conn.execute(
            "SELECT data_type FROM information_schema.columns WHERE table_name = ? AND column_name = ?",
            (table, column),
        ).fetchone()
        if row is not None:
            data_type = row["data_type"] if isinstance(row, dict) else row[0]
            if data_type == "boolean":
                kind = "bool"
    _bool_kinds[key] = kind
    return kind


def _bool_param(conn: DBConnection, table: str, column: str, value: Any):
    flag = bool(value)
    return flag if _bool_kind(conn, table, column) == "bool" else int(flag)


def _insert_returning_id(conn: DBConnection, sql: str, params: Sequence[Any]) -> int:
    if conn.is_pg:
        cur = conn.execute(sql.rstrip().rstrip(";") + " RETURNING id", params)
        row = cur.fetchone()
        return int(row["id"] if isinstance(row, dict) else row[0])
    cur = conn.execute(sql, params)
    return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
# Schema
# --------------------------------------------------------------------------- #
def _schema(is_pg: bool) -> List[str]:
    pk = "SERIAL PRIMARY KEY" if is_pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    return [
        f"""CREATE TABLE IF NOT EXISTS devices (
            id {pk},
            device_id TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            platform TEXT NOT NULL,
            ip TEXT,
            owner_type TEXT DEFAULT 'child',
            status TEXT DEFAULT 'offline',
            last_seen TEXT,
            created_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS events (
            id {pk},
            device_id TEXT NOT NULL,
            type TEXT NOT NULL,
            data TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS commands (
            id {pk},
            device_id TEXT NOT NULL,
            action TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS rules (
            device_id TEXT PRIMARY KEY,
            blocked_categories TEXT DEFAULT '["adult", "gambling"]',
            blocked_domains TEXT DEFAULT '[]',
            bedtime_enabled INTEGER DEFAULT 0,
            bedtime_start TEXT DEFAULT '21:00',
            bedtime_end TEXT DEFAULT '07:00',
            updated_at TEXT NOT NULL
        )""",
        f"""CREATE TABLE IF NOT EXISTS snapshots (
            id {pk},
            device_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            timestamp TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS api_keys (
            key_hash TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            device_id TEXT,
            created_at TEXT NOT NULL,
            last_used TEXT
        )""",
        "CREATE INDEX IF NOT EXISTS idx_events_dev ON events(device_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp)",
        "CREATE INDEX IF NOT EXISTS idx_cmds_dev ON commands(device_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_snaps_dev ON snapshots(device_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_keys_dev ON api_keys(device_id)",
    ]


_COLUMN_ADDS = {
    "devices": [
        ("locked", "INTEGER DEFAULT 0"),
        ("paused", "INTEGER DEFAULT 0"),
        ("caps", "TEXT"),
        ("agent_version", "TEXT"),
    ],
    "rules": [
        ("allowed_domains", "TEXT DEFAULT '[]'"),
        ("snapshot_interval_s", "INTEGER DEFAULT 300"),
    ],
}


def _existing_columns(conn: DBConnection, table: str) -> set:
    if conn.is_pg:
        rows = conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name = ?", (table,)).fetchall()
        return {(r["column_name"] if isinstance(r, dict) else r[0]) for r in rows}
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def init_db() -> None:
    """Create tables, add missing columns, and migrate old status values."""
    with get_connection() as conn:
        for statement in _schema(conn.is_pg):
            conn.execute(statement)
        for table, columns in _COLUMN_ADDS.items():
            have = _existing_columns(conn, table)
            for name, ddl in columns:
                if name not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")
        if conn.is_pg:
            # Supabase exposes every public table through its REST API. With RLS on and no
            # policies, the anon/authenticated roles see nothing; the hub's own (owner)
            # connection is unaffected.
            for table in ("devices", "events", "commands", "rules", "snapshots", "settings", "api_keys"):
                try:
                    conn.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
                except Exception as exc:  # restricted role: warn, don't stop the hub
                    log.warning("Could not enable row level security on %s: %s", table, exc)
        # Pre-2.0 stored lock/pause inside `status`. Split them into real flags.
        conn.execute("UPDATE devices SET locked = 1, status = 'offline' WHERE status = 'locked'")
        conn.execute("UPDATE devices SET paused = 1, status = 'offline' WHERE status IN ('paused', 'blocked')")
    if not backend_name() == "postgres":
        try:
            import os

            if _db_path.exists():
                os.chmod(_db_path, 0o600)
        except OSError:  # Windows or read-only FS
            pass


def reset_all() -> None:
    """Delete every row from every table (tests only)."""
    with get_connection() as conn:
        for table in ("devices", "events", "commands", "rules", "snapshots", "settings", "api_keys"):
            conn.execute(f"DELETE FROM {table}")


# --------------------------------------------------------------------------- #
# Devices
# --------------------------------------------------------------------------- #
_DEVICE_COLS = "id, device_id, name, platform, ip, owner_type, status, last_seen, created_at, locked, paused, caps, agent_version"
_DEVICE_UPDATABLE = {"name", "owner_type", "ip", "status", "last_seen", "locked", "paused", "caps", "agent_version"}


def _device(row: Any) -> Dict[str, Any]:
    data = _row(row)
    data["locked"] = bool(data.get("locked"))
    data["paused"] = bool(data.get("paused"))
    data["caps"] = _safe_json_load(data.get("caps"), {})
    return data


def get_device(device_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(f"SELECT {_DEVICE_COLS} FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        return _device(row) if row else None


def list_devices() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(f"SELECT {_DEVICE_COLS} FROM devices ORDER BY id ASC").fetchall()
        return [_device(r) for r in rows]


def insert_device(device_id: str, name: str, platform: str, owner_type: str = "child", ip: Optional[str] = None) -> Dict[str, Any]:
    now = now_iso()
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO devices (device_id, name, platform, ip, owner_type, status, last_seen, created_at, locked, paused) "
                "VALUES (?, ?, ?, ?, ?, 'offline', NULL, ?, 0, 0)",
                (device_id, name, platform, ip, owner_type, now),
            )
    except Exception as exc:
        if exc.__class__.__name__ in ("IntegrityError", "UniqueViolation"):
            raise DuplicateDevice(device_id) from exc
        raise
    created = get_device(device_id)
    assert created is not None
    return created


def update_device(device_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Update whitelisted device fields. Returns the fresh device (or None if missing)."""
    sets: List[str] = []
    params: List[Any] = []
    for key, value in fields.items():
        if key not in _DEVICE_UPDATABLE:
            raise ValueError(f"field not updatable: {key}")
        if key in ("locked", "paused"):
            value = int(bool(value))
        elif key == "caps":
            value = json.dumps(value or {})
        sets.append(f"{key} = ?")
        params.append(value)
    if not sets:
        return get_device(device_id)
    params.append(device_id)
    with get_connection() as conn:
        conn.execute(f"UPDATE devices SET {', '.join(sets)} WHERE device_id = ?", params)
    return get_device(device_id)


def delete_device(device_id: str) -> bool:
    with get_connection() as conn:
        exists = conn.execute("SELECT 1 FROM devices WHERE device_id = ?", (device_id,)).fetchone()
        for table in ("devices", "commands", "rules", "events", "snapshots", "api_keys"):
            conn.execute(f"DELETE FROM {table} WHERE device_id = ?", (device_id,))
        return exists is not None


def count_devices() -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM devices").fetchone()
        return int(row["n"])


# --------------------------------------------------------------------------- #
# Events
# --------------------------------------------------------------------------- #
def insert_event(device_id: str, event_type: str, data: Dict[str, Any], timestamp: str) -> int:
    with get_connection() as conn:
        return _insert_returning_id(
            conn,
            "INSERT INTO events (device_id, type, data, timestamp) VALUES (?, ?, ?, ?)",
            (device_id, event_type, json.dumps(data, default=str), timestamp),
        )


def _event(row: Any) -> Dict[str, Any]:
    data = _row(row)
    data["data"] = _safe_json_load(data.get("data"), {})
    return data


def list_events(
    limit: int = 50,
    before_id: Optional[int] = None,
    device_id: Optional[str] = None,
    types: Optional[Iterable[str]] = None,
    exclude_types: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    """Newest first."""
    where: List[str] = []
    params: List[Any] = []
    if before_id is not None:
        where.append("id < ?")
        params.append(int(before_id))
    if device_id:
        where.append("device_id = ?")
        params.append(device_id)
    types = list(types or [])
    if types:
        where.append(f"type IN ({','.join('?' * len(types))})")
        params.extend(types)
    exclude = list(exclude_types or [])
    if exclude:
        where.append(f"type NOT IN ({','.join('?' * len(exclude))})")
        params.extend(exclude)
    sql = "SELECT id, device_id, type, data, timestamp FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with get_connection() as conn:
        return [_event(r) for r in conn.execute(sql, params).fetchall()]


def events_since(since_iso: str, exclude_types: Optional[Iterable[str]] = None, limit: int = 5000) -> List[Dict[str, Any]]:
    params: List[Any] = [since_iso]
    sql = "SELECT id, device_id, type, data, timestamp FROM events WHERE timestamp >= ?"
    exclude = list(exclude_types or [])
    if exclude:
        sql += f" AND type NOT IN ({','.join('?' * len(exclude))})"
        params.extend(exclude)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with get_connection() as conn:
        return [_event(r) for r in conn.execute(sql, params).fetchall()]


def count_events() -> int:
    with get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM events").fetchone()["n"])


# --------------------------------------------------------------------------- #
# Command queue
# --------------------------------------------------------------------------- #
def queue_command(device_id: str, action: str, payload: Dict[str, Any]) -> int:
    with get_connection() as conn:
        return _insert_returning_id(
            conn,
            "INSERT INTO commands (device_id, action, payload, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (device_id, action, json.dumps(payload, default=str), now_iso()),
        )


def pop_pending_commands(device_id: str) -> List[Dict[str, Any]]:
    """Atomically claim every pending command for a device."""
    with get_connection() as conn:
        if conn.is_pg or sqlite3.sqlite_version_info >= (3, 35, 0):
            rows = conn.execute(
                "UPDATE commands SET status = 'delivered' WHERE device_id = ? AND status = 'pending' "
                "RETURNING id, action, payload, created_at",
                (device_id,),
            ).fetchall()
        else:  # very old SQLite: emulate atomicity with a write lock
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id, action, payload, created_at FROM commands WHERE device_id = ? AND status = 'pending'",
                (device_id,),
            ).fetchall()
            if rows:
                ids = [r["id"] for r in rows]
                conn.execute(f"UPDATE commands SET status = 'delivered' WHERE id IN ({','.join('?' * len(ids))})", ids)
        normalised = [_row(r) for r in rows]
    normalised.sort(key=lambda r: r["id"])
    return [
        {
            "id": r["id"],
            "action": r["action"],
            "payload": _safe_json_load(r["payload"], {}),
            "timestamp": r["created_at"],
        }
        for r in normalised
    ]


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
def _rules_from_row(row: Any) -> Dict[str, Any]:
    data = _row(row)
    return {
        "device_id": data["device_id"],
        "blocked_categories": _safe_json_load(data.get("blocked_categories"), list(DEFAULT_RULES["blocked_categories"])),
        "blocked_domains": _safe_json_load(data.get("blocked_domains"), []),
        "allowed_domains": _safe_json_load(data.get("allowed_domains"), []),
        "bedtime_enabled": bool(data.get("bedtime_enabled")),
        "bedtime_start": data.get("bedtime_start") or DEFAULT_RULES["bedtime_start"],
        "bedtime_end": data.get("bedtime_end") or DEFAULT_RULES["bedtime_end"],
        "snapshot_interval_s": int(data["snapshot_interval_s"]) if data.get("snapshot_interval_s") is not None else DEFAULT_RULES["snapshot_interval_s"],
        "updated_at": data.get("updated_at"),
    }


def get_device_rules(device_id: str) -> Dict[str, Any]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM rules WHERE device_id = ?", (device_id,)).fetchone()
        if row:
            return _rules_from_row(row)
    defaults = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_RULES.items()}
    defaults.update({"device_id": device_id, "updated_at": None})
    return defaults


def list_all_rules() -> Dict[str, Dict[str, Any]]:
    with get_connection() as conn:
        return {r["device_id"]: _rules_from_row(r) for r in conn.execute("SELECT * FROM rules").fetchall()}


def save_device_rules(device_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    """Merge ``changes`` into the stored rules and return the result."""
    merged = get_device_rules(device_id)
    for key in DEFAULT_RULES:
        if key in changes and changes[key] is not None:
            merged[key] = changes[key]
    now = now_iso()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO rules (device_id, blocked_categories, blocked_domains, allowed_domains,
                                  bedtime_enabled, bedtime_start, bedtime_end, snapshot_interval_s, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(device_id) DO UPDATE SET
                   blocked_categories = excluded.blocked_categories,
                   blocked_domains = excluded.blocked_domains,
                   allowed_domains = excluded.allowed_domains,
                   bedtime_enabled = excluded.bedtime_enabled,
                   bedtime_start = excluded.bedtime_start,
                   bedtime_end = excluded.bedtime_end,
                   snapshot_interval_s = excluded.snapshot_interval_s,
                   updated_at = excluded.updated_at""",
            (
                device_id,
                json.dumps(merged["blocked_categories"]),
                json.dumps(merged["blocked_domains"]),
                json.dumps(merged["allowed_domains"]),
                _bool_param(conn, "rules", "bedtime_enabled", merged["bedtime_enabled"]),
                merged["bedtime_start"],
                merged["bedtime_end"],
                int(merged["snapshot_interval_s"]),
                now,
            ),
        )
    merged["updated_at"] = now
    merged["device_id"] = device_id
    return merged


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #
def record_snapshot(device_id: str, filename: str, file_path: str) -> Dict[str, Any]:
    now = now_iso()
    with get_connection() as conn:
        new_id = _insert_returning_id(
            conn,
            "INSERT INTO snapshots (device_id, filename, file_path, timestamp) VALUES (?, ?, ?, ?)",
            (device_id, filename, file_path, now),
        )
    return {"id": new_id, "device_id": device_id, "filename": filename, "timestamp": now}


def list_snapshots(device_id: Optional[str] = None, limit: int = 24, before_id: Optional[int] = None) -> List[Dict[str, Any]]:
    where: List[str] = []
    params: List[Any] = []
    if device_id:
        where.append("device_id = ?")
        params.append(device_id)
    if before_id is not None:
        where.append("id < ?")
        params.append(int(before_id))
    sql = "SELECT id, device_id, filename, timestamp FROM snapshots"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    with get_connection() as conn:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]


def get_snapshot(snapshot_id: int) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT id, device_id, filename, timestamp FROM snapshots WHERE id = ?", (int(snapshot_id),)).fetchone()
        return _row(row) if row else None


def delete_snapshot_rows(ids: Sequence[int]) -> None:
    if not ids:
        return
    with get_connection() as conn:
        conn.execute(f"DELETE FROM snapshots WHERE id IN ({','.join('?' * len(ids))})", [int(i) for i in ids])


def snapshots_older_than(cutoff_iso: str) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute("SELECT id, device_id, filename, timestamp FROM snapshots WHERE timestamp < ?", (cutoff_iso,)).fetchall()
        return [_row(r) for r in rows]


def snapshots_beyond_limit(device_id: str, keep: int) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, device_id, filename, timestamp FROM snapshots WHERE device_id = ? ORDER BY id DESC LIMIT 1000000 OFFSET ?",
            (device_id, int(keep)),
        ).fetchall()
        return [_row(r) for r in rows]


def snapshot_device_ids() -> List[str]:
    with get_connection() as conn:
        return [r["device_id"] for r in conn.execute("SELECT DISTINCT device_id FROM snapshots").fetchall()]


def count_snapshots() -> int:
    with get_connection() as conn:
        return int(conn.execute("SELECT COUNT(*) AS n FROM snapshots").fetchone()["n"])


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def delete_setting(key: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))


# --------------------------------------------------------------------------- #
# API keys (only SHA-256 hashes are stored)
# --------------------------------------------------------------------------- #
def store_api_key(key_hash: str, role: str, device_id: Optional[str]) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO api_keys (key_hash, role, device_id, created_at) VALUES (?, ?, ?, ?) ON CONFLICT(key_hash) DO NOTHING",
            (key_hash, role, device_id or "", now_iso()),
        )


def find_api_key(key_hash: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute("SELECT key_hash, role, device_id FROM api_keys WHERE key_hash = ?", (key_hash,)).fetchone()
        return _row(row) if row else None


def touch_api_key(key_hash: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE api_keys SET last_used = ? WHERE key_hash = ?", (now_iso(), key_hash))


def delete_api_keys_for_device(device_id: str) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM api_keys WHERE device_id = ?", (device_id,))


# --------------------------------------------------------------------------- #
# Maintenance
# --------------------------------------------------------------------------- #
def prune(event_cutoff_iso: str, command_cutoff_iso: str, max_events: int = 50000) -> Dict[str, int]:
    """Delete old events/commands. Returns how many rows were removed."""
    removed = {"events": 0, "commands": 0}
    with get_connection() as conn:
        removed["events"] += conn.execute("DELETE FROM events WHERE timestamp < ?", (event_cutoff_iso,)).rowcount or 0
        removed["commands"] += conn.execute(
            "DELETE FROM commands WHERE status <> 'pending' AND created_at < ?", (command_cutoff_iso,)
        ).rowcount or 0
        # Hard cap on table size, independent of age.
        row = conn.execute("SELECT id FROM events ORDER BY id DESC LIMIT 1 OFFSET ?", (int(max_events),)).fetchone()
        if row:
            cutoff_id = row["id"]
            removed["events"] += conn.execute("DELETE FROM events WHERE id <= ?", (cutoff_id,)).rowcount or 0
    return removed


def ping() -> bool:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False
