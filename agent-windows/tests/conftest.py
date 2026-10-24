"""Fixtures for the agent tests: a REAL hub on a real socket (in a thread) + a fake Windows layer."""
from __future__ import annotations

import io
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

AGENT_DIR = Path(__file__).resolve().parent.parent
HUB_DIR = AGENT_DIR.parent / "hub"
# HUB_DIR first, AGENT_DIR on top: `himaya_windows_agent` must resolve to agent-windows/ (the source of truth).
for path in (str(HUB_DIR), str(AGENT_DIR)):
    if path in sys.path:
        sys.path.remove(path)
    sys.path.insert(0, path)

ADMIN_KEY = "agent-test-admin-key-0123456789"
ADMIN = {"X-API-Key": ADMIN_KEY}


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture()
def live_hub(tmp_path, monkeypatch):
    uvicorn = pytest.importorskip("uvicorn")
    port = free_port()
    values = {
        "HIMAYA_SKIP_DOTENV": "1", "HIMAYA_DATA_DIR": str(tmp_path / "hubdata"), "HIMAYA_STATIC_DIR": str(tmp_path / "static"),
        "HIMAYA_ADMIN_KEY": ADMIN_KEY, "HIMAYA_DNS_ENABLED": "0", "HIMAYA_DISCOVERY": "0",
        "DATABASE_URL": "", "SUPABASE_DB_URL": "", "HIMAYA_LAN_IP": "127.0.0.1", "RENDER": "false", "PORT": str(port),
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    import config
    import main

    app = main.create_app(config.load_settings())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "hub did not start"
    yield f"http://127.0.0.1:{port}", app.state.hub
    server.should_exit = True
    thread.join(timeout=5)


class FakePlatform:
    """Records every side effect the real Windows layer would have."""

    def __init__(self):
        self.admin = False
        self.locks = 0
        self.messages = []
        self.proxy = {"enable": 0, "server": None, "override": None}
        self.proxy_writes = []
        self.vpns = []
        self.killed = []
        self.shots = 0
        self.flushes = 0

    def is_admin(self): return self.admin
    def local_ip(self): return "192.168.1.55"
    def lock_workstation(self): self.locks += 1
    def message_box(self, title, text): self.messages.append((title, text))
    def read_proxy(self): return dict(self.proxy)

    def write_proxy(self, enable, server, override):
        self.proxy = {"enable": enable, "server": server, "override": override}
        self.proxy_writes.append(dict(self.proxy))

    def list_vpn_adapters(self): return list(self.vpns)

    def grab_screenshot_jpeg(self):
        from PIL import Image
        self.shots += 1
        buffer = io.BytesIO()
        Image.new("RGB", (64, 36), (20, 40, 90)).save(buffer, "JPEG")
        return buffer.getvalue()

    def kill_process(self, name):
        self.killed.append(name)
        return True

    def flush_dns(self): self.flushes += 1


class FakeUI:
    def __init__(self):
        self.notifications = []
        self.levels = []

    def notify(self, title, message): self.notifications.append((title, message))
    def set_level(self, level, tooltip): self.levels.append((level, tooltip))


@pytest.fixture()
def platform():
    return FakePlatform()


@pytest.fixture()
def enrolled(live_hub, platform, tmp_path):
    """Pair a child PC through the real PIN flow and build an AgentCore wired to the live hub."""
    import requests

    import himaya_windows_agent as agent

    base, hub = live_hub
    pin = requests.get(base + "/enroll/info", headers=ADMIN, timeout=5).json()["pin"]
    paired = requests.post(base + "/enroll/pair", json={"pin": pin, "name": "KID-PC (sarah)", "platform": "windows", "owner_type": "child"}, timeout=5).json()
    config = {"hub_url": base, "candidate_urls": [], "device_id": paired["device_id"], "agent_key": paired["agent_key"], "owner_type": "child"}
    client = agent.HubClient([base], paired["device_id"], paired["agent_key"])
    ui = FakeUI()
    hosts_path = tmp_path / "hosts"
    core = agent.AgentCore(config, client, platform, ui=ui, config_path=tmp_path / "agent_config.json", hosts_path=hosts_path)

    class Ctx:
        pass

    ctx = Ctx()
    ctx.base, ctx.hub, ctx.core, ctx.ui, ctx.platform = base, hub, core, ui, platform
    ctx.device_id, ctx.agent_key, ctx.hosts_path, ctx.agent = paired["device_id"], paired["agent_key"], hosts_path, agent

    def parent(method, path, **kwargs):
        return getattr(requests, method)(base + path, headers=ADMIN, timeout=5, **kwargs)

    ctx.parent = parent
    return ctx
