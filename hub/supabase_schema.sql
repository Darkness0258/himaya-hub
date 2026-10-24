-- ====================================================================
-- Himaya Family Safety Hub - PostgreSQL / Supabase schema
-- Optional: the hub creates and upgrades all of this by itself when it connects.
-- Run it in the Supabase SQL Editor only if you want to create the tables up front.
-- ====================================================================

CREATE TABLE IF NOT EXISTS devices (
    id SERIAL PRIMARY KEY,
    device_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    ip TEXT,
    owner_type TEXT DEFAULT 'child',
    status TEXT DEFAULT 'offline',          -- connectivity only: online / offline
    last_seen TEXT,
    created_at TEXT NOT NULL,
    locked INTEGER DEFAULT 0,               -- parent-controlled state
    paused INTEGER DEFAULT 0,
    caps TEXT,                              -- what the agent can enforce (JSON)
    agent_version TEXT
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
    allowed_domains TEXT DEFAULT '[]',
    bedtime_enabled INTEGER DEFAULT 0,
    bedtime_start TEXT DEFAULT '21:00',
    bedtime_end TEXT DEFAULT '07:00',
    snapshot_interval_s INTEGER DEFAULT 300,
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

-- Only SHA-256 hashes of keys are stored, never the keys themselves.
CREATE TABLE IF NOT EXISTS api_keys (
    key_hash TEXT PRIMARY KEY,
    role TEXT NOT NULL,
    device_id TEXT,
    created_at TEXT NOT NULL,
    last_used TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_dev ON events(device_id);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(timestamp);
CREATE INDEX IF NOT EXISTS idx_cmds_dev ON commands(device_id, status);
CREATE INDEX IF NOT EXISTS idx_snaps_dev ON snapshots(device_id, id);
CREATE INDEX IF NOT EXISTS idx_keys_dev ON api_keys(device_id);

-- IMPORTANT on Supabase: every table in the "public" schema is reachable through the project's
-- auto-generated REST API. Row Level Security with NO policies means the anon/authenticated roles
-- can see nothing, while the hub (which connects as the table owner) keeps full access.
ALTER TABLE devices   ENABLE ROW LEVEL SECURITY;
ALTER TABLE events    ENABLE ROW LEVEL SECURITY;
ALTER TABLE commands  ENABLE ROW LEVEL SECURITY;
ALTER TABLE rules     ENABLE ROW LEVEL SECURITY;
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings  ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys  ENABLE ROW LEVEL SECURITY;
