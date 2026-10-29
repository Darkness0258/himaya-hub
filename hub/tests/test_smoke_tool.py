"""tools/smoke_test.py against a REAL hub on a real socket (home mode and cloud mode)."""
from __future__ import annotations

import importlib.util
import json
import socket
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "smoke_test.py"
spec = importlib.util.spec_from_file_location("smoke_test", TOOL)
smoke = importlib.util.module_from_spec(spec)
sys.modules["smoke_test"] = smoke   # dataclasses look their own module up here
spec.loader.exec_module(smoke)  # type: ignore[union-attr]

KEY = "smoke-test-admin-key-0123456789"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_hub(tmp_path, monkeypatch, cloud: bool):
    uvicorn = pytest.importorskip("uvicorn")
    port = free_port()
    values = {
        "HIMAYA_SKIP_DOTENV": "1", "HIMAYA_DATA_DIR": str(tmp_path / "hubdata"), "HIMAYA_STATIC_DIR": str(tmp_path / "static"),
        "HIMAYA_ADMIN_KEY": KEY, "HIMAYA_DNS_ENABLED": "0", "HIMAYA_DISCOVERY": "0", "DATABASE_URL": "", "SUPABASE_DB_URL": "",
        "HIMAYA_LAN_IP": "127.0.0.1", "RENDER": "true" if cloud else "false", "PORT": str(port), "HIMAYA_KEEPALIVE": "0",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
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
    return f"http://127.0.0.1:{port}", server, thread


@pytest.fixture()
def home_hub(tmp_path, monkeypatch):
    url, server, thread = start_hub(tmp_path, monkeypatch, cloud=False)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture()
def cloud_hub(tmp_path, monkeypatch):
    url, server, thread = start_hub(tmp_path, monkeypatch, cloud=True)
    yield url
    server.should_exit = True
    thread.join(timeout=5)


def run(url, key=KEY, patience=2):
    lines = []
    code = smoke.run(url, key, patience_s=patience, out=lines.append)
    return code, "\n".join(lines)


def device_names(url):
    request = urllib.request.Request(url + "/devices", headers={"X-API-Key": KEY})
    with urllib.request.urlopen(request) as response:
        return [d["name"] for d in json.load(response)]


class TestHealthyHub:
    def test_everything_passes_and_nothing_is_left_behind(self, home_hub):
        code, out = run(home_hub)
        assert code == 0, out
        for check in ("hub answers", "admin key", "enroll info", "pairing", "heartbeat", "screenshot", "live view", "cleanup"):
            assert f"[ ok ] {check}" in out, out
        assert "0 failed" in out
        assert device_names(home_hub) == []            # the throwaway device was deleted

    def test_it_never_prints_the_admin_key_or_the_pin(self, home_hub):
        request = urllib.request.Request(home_hub + "/enroll/info", headers={"X-API-Key": KEY})
        with urllib.request.urlopen(request) as response:
            pin = json.load(response)["pin"]
        _, out = run(home_hub)
        assert KEY not in out and str(pin) not in out

    def test_the_websocket_check_runs_when_the_library_is_there(self, home_hub):
        pytest.importorskip("websockets")
        _, out = run(home_hub)
        assert "[ ok ] websocket" in out

    def test_a_home_hub_without_dns_is_flagged(self, home_hub):
        _, out = run(home_hub)
        assert "DNS filter is not running" in out


class TestCloudHub:
    def test_cloud_with_sqlite_gets_the_persistence_warning(self, cloud_hub):
        code, out = run(cloud_hub)
        assert code == 0, out
        assert "cloud hub using SQLite" in out and "DATABASE_URL" in out
        assert "Cloud hub: the website filter (DNS) is off by design" in out


class TestProblems:
    def test_wrong_key_is_explained_and_stops_early(self, home_hub):
        code, out = run(home_hub, key="not-the-key")
        assert code == 1
        assert "[FAIL] admin key" in out and "HIMAYA_ADMIN_KEY" in out and "pairing" not in out

    def test_nothing_listening_is_explained(self):
        code, out = run(f"http://127.0.0.1:{free_port()}", patience=1)
        assert code == 1
        assert "[FAIL] hub answers" in out and "connection refused" in out

    def test_a_web_server_that_is_not_a_hub_is_recognised(self, tmp_path):
        import http.server

        class Other(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(404)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = http.server.HTTPServer(("127.0.0.1", 0), Other)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            code, out = run(f"http://127.0.0.1:{server.server_port}", patience=5)
        finally:
            server.shutdown()
        assert code == 1 and "not a Himaya hub" in out

    def test_a_crashing_check_still_cleans_up(self, home_hub, monkeypatch):
        def boom(*args, **kwargs):
            raise RuntimeError("simulated crash")

        monkeypatch.setattr(smoke, "check_screenshot", boom)
        code, out = run(home_hub)
        assert code == 1 and "[FAIL] screenshot" in out and "simulated crash" in out
        assert "[ ok ] live view" in out                 # later checks still ran
        assert device_names(home_hub) == []              # and the throwaway device is gone

    def test_a_device_key_is_refused_up_front(self, capsys):
        assert smoke.main(["http://127.0.0.1:1", "--key", "hag_abc"]) == 2
        assert "device key" in capsys.readouterr().err


class TestAddresses:
    @pytest.mark.parametrize("raw,expected", [
        ("192.168.1.20:8000", "http://192.168.1.20:8000"),
        ("localhost:8000", "http://localhost:8000"),
        ("hub.local", "http://hub.local"),
        ("himaya-hub.onrender.com", "https://himaya-hub.onrender.com"),
        ("https://himaya-hub.onrender.com/", "https://himaya-hub.onrender.com"),
        ("http://10.8.0.1:8000", "http://10.8.0.1:8000"),
    ])
    def test_normalize(self, raw, expected):
        assert smoke.normalize(raw) == expected
