-- ====================================================================
-- Himaya Family Safety Hub — Supabase PostgreSQL Database Schema
-- Paste and run this script in your Supabase SQL Editor
-- ====================================================================

-- 1. Devices Table
CREATE TABLE IF NOT EXISTS devices (
    id SERIAL PRIMARY KEY,
    device_id TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    platform TEXT NOT NULL,
    ip TEXT,
    owner_type TEXT DEFAULT 'child',
    status TEXT DEFAULT 'offline',
    last_seen TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 2. Security & Activity Events Table
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    type TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Queued Remote Commands Table
CREATE TABLE IF NOT EXISTS commands (
    id SERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    action TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 4. Content Filtering & Curfew Rules Table
CREATE TABLE IF NOT EXISTS rules (
    device_id TEXT PRIMARY KEY,
    blocked_categories JSONB DEFAULT '["adult", "gambling"]'::jsonb,
    blocked_domains JSONB DEFAULT '[]'::jsonb,
    bedtime_enabled BOOLEAN DEFAULT FALSE,
    bedtime_start TEXT DEFAULT '21:00',
    bedtime_end TEXT DEFAULT '07:00',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 5. Screen Snapshots Metadata Table
CREATE TABLE IF NOT EXISTS snapshots (
    id SERIAL PRIMARY KEY,
    device_id TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 6. System & Network Settings Table
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Performance Indexes
CREATE INDEX IF NOT EXISTS idx_events_device_id ON events(device_id);
CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_commands_device_status ON commands(device_id, status);
CREATE INDEX IF NOT EXISTS idx_snapshots_device_timestamp ON snapshots(device_id, timestamp DESC);
