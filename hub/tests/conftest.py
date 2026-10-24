"""Shared fixtures: every test gets a brand-new hub with its own temp data directory."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

HUB_DIR = Path(__file__).resolve().parent.parent
if str(HUB_DIR) not in sys.path:
    sys.path.insert(0, str(HUB_DIR))

ADMIN_KEY = "test-admin-key-0123456789"
ADMIN = {"X-API-Key": ADMIN_KEY}

# Minimal valid JPEG (SOI + APP0 + EOI) - enough for the hub's magic-byte check.
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    values = {
        "HIMAYA_SKIP_DOTENV": "1",
        "HIMAYA_DATA_DIR": str(tmp_path / "data"),
        "HIMAYA_STATIC_DIR": str(tmp_path / "static"),
        "HIMAYA_ADMIN_KEY": ADMIN_KEY,
        "HIMAYA_DNS_ENABLED": "0",
        "HIMAYA_DISCOVERY": "0",
        # Set HIMAYA_TEST_DATABASE_URL to run the whole suite against PostgreSQL (the Supabase code path).
        "DATABASE_URL": os.environ.get("HIMAYA_TEST_DATABASE_URL", ""),
        "SUPABASE_DB_URL": "",
        "HIMAYA_LAN_IP": "192.168.1.50",
        "RENDER": "false",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    for key in ("RENDER_EXTERNAL_URL", "HIMAYA_PUBLIC_URL", "HIMAYA_CORS_ORIGINS", "HIMAYA_CLOUD"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path


@pytest.fixture()
def client(env):
    from fastapi.testclient import TestClient

    import config
    import main

    settings = config.load_settings()
    if os.environ.get("HIMAYA_TEST_DATABASE_URL"):
        import database

        database.configure(settings.db_path)
        database.init_db()
        database.reset_all()               # tests share one PostgreSQL database, so start each one clean
    app = main.create_app(settings)
    with TestClient(app) as test_client:
        test_client.hub = app.state.hub  # type: ignore[attr-defined]
        yield test_client


@pytest.fixture()
def paired(client):
    """Pair one Windows child device through the real PIN flow. Returns (device_id, agent_headers)."""
    pin = client.get("/enroll/info", headers=ADMIN).json()["pin"]
    response = client.post("/enroll/pair", json={"pin": pin, "name": "Sarah's PC", "platform": "windows", "owner_type": "child"})
    assert response.status_code == 200, response.text
    data = response.json()
    return data["device_id"], {"X-API-Key": data["agent_key"]}
