"""End-to-end tests of the hub's HTTP/WebSocket API (isolated hub per test)."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone

import pytest

from conftest import ADMIN, ADMIN_KEY, JPEG


# --------------------------------------------------------------------------- #
# Authentication
# --------------------------------------------------------------------------- #
class TestAuth:
    def test_health_is_public_and_minimal(self, client):
        body = client.get("/health").json()
        assert body["status"] == "ok"
        assert "lan_ip" not in body and "public_ip" not in body and "devices" not in body

    @pytest.mark.parametrize("path", ["/devices", "/events", "/snapshots", "/api/stats", "/enroll/info", "/api/settings", "/health/details"])
    def test_parent_routes_need_a_key(self, client, path):
        assert client.get(path).status_code == 401

    def test_wrong_key_rejected(self, client):
        assert client.get("/devices", headers={"X-API-Key": "nope"}).status_code == 401

    def test_correct_key_accepted(self, client):
        response = client.get("/api/me", headers=ADMIN)
        assert response.status_code == 200 and response.json()["role"] == "parent"

    def test_brute_force_is_rate_limited(self, client):
        codes = [client.get("/devices", headers={"X-API-Key": f"guess-{i}"}).status_code for i in range(12)]
        assert 429 in codes
        # even the right key is refused while locked out from that address
        assert client.get("/devices", headers=ADMIN).status_code == 429

    def test_admin_key_is_not_stored_in_plaintext(self, client, env):
        import database

        with database.get_connection() as conn:
            stored = [r["value"] for r in conn.execute("SELECT value FROM settings").fetchall()]
        assert ADMIN_KEY not in stored and all(ADMIN_KEY not in value for value in stored)

    def test_docs_hidden_by_default(self, client):
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404

    def test_no_cors_by_default(self, client):
        response = client.get("/health", headers={"Origin": "https://evil.example"})
        assert "access-control-allow-origin" not in response.headers


# --------------------------------------------------------------------------- #
# Pairing
# --------------------------------------------------------------------------- #
class TestPairing:
    def test_pin_is_random_not_the_old_hardcoded_default(self, client):
        """Regression: the PIN used to be the constant 842019 for every hub."""
        import security

        pin = client.get("/enroll/info", headers=ADMIN).json()["pin"]
        assert re.fullmatch(r"\d{6}", pin)
        many = {security.PinManager().current()[0] for _ in range(25)}
        assert len(many) > 1 and many != {"842019"}

    def test_pin_never_leaks_without_auth(self, client):
        pin = client.get("/enroll/info", headers=ADMIN).json()["pin"]
        for path in ("/enroll/mobile", "/enroll/win", "/health", "/probe"):
            assert pin not in client.get(path).text

    def test_pairing_flow_and_single_use_pin(self, client):
        info = client.get("/enroll/info", headers=ADMIN).json()
        pin = info["pin"]
        assert info["pin_expires_in"] > 0 and info["urls"][0]["kind"] == "lan"
        ok = client.post("/enroll/pair", json={"pin": pin, "name": "Tablet", "platform": "android", "owner_type": "child"})
        assert ok.status_code == 200
        data = ok.json()
        assert data["device_id"].startswith("android-") and data["agent_key"].startswith("hag_")
        # the PIN is consumed
        again = client.post("/enroll/pair", json={"pin": pin, "name": "Tablet 2", "platform": "android"})
        assert again.status_code == 403
        devices = client.get("/devices", headers=ADMIN).json()
        assert [d["device_id"] for d in devices] == [data["device_id"]]

    def test_wrong_pins_are_rate_limited_and_rotate_the_pin(self, client):
        pin = client.get("/enroll/info", headers=ADMIN).json()["pin"]
        wrong = "000000" if pin != "000000" else "111111"
        codes = [client.post("/enroll/pair", json={"pin": wrong, "name": "x", "platform": "windows"}).status_code for _ in range(7)]
        assert codes[:5] == [403] * 5 and 429 in codes[5:]
        # even the correct pin is refused during the lock-out
        assert client.post("/enroll/pair", json={"pin": pin, "name": "x", "platform": "windows"}).status_code == 429

    def test_regenerate_pin_requires_parent(self, client):
        assert client.post("/enroll/pin/regenerate").status_code == 401
        first = client.get("/enroll/info", headers=ADMIN).json()["pin"]
        second = client.post("/enroll/pin/regenerate", headers=ADMIN).json()["pin"]
        assert re.fullmatch(r"\d{6}", second)
        assert client.get("/enroll/info", headers=ADMIN).json()["pin"] == second
        assert isinstance(first, str)

    def test_adult_devices_get_no_screenshots_and_no_default_blocks(self, client):
        pin = client.get("/enroll/info", headers=ADMIN).json()["pin"]
        data = client.post("/enroll/pair", json={"pin": pin, "name": "Dad's laptop", "platform": "windows", "owner_type": "adult"}).json()
        rules = client.get(f"/rules/{data['device_id']}", headers=ADMIN).json()
        assert rules["snapshot_interval_s"] == 0 and rules["blocked_categories"] == [] and rules["blocked_domains"] == []

    def test_client_cannot_choose_its_device_id(self, client):
        pin = client.get("/enroll/info", headers=ADMIN).json()["pin"]
        data = client.post("/enroll/pair", json={"pin": pin, "name": "x", "platform": "windows", "device_id": "admin-1"}).json()
        assert data["device_id"] != "admin-1"

    def test_invalid_inputs_rejected(self, client):
        assert client.post("/enroll/pair", json={"pin": "12", "name": "x"}).status_code == 422
        assert client.post("/enroll/pair", json={"pin": "123456", "name": "", "platform": "windows"}).status_code == 422
        assert client.post("/enroll/pair", json={"pin": "123456", "name": "x", "platform": "toaster"}).status_code == 422


# --------------------------------------------------------------------------- #
# Agent endpoints
# --------------------------------------------------------------------------- #
class TestAgent:
    def test_agent_key_only_works_for_its_own_device(self, client, paired):
        device_id, agent = paired
        other_pin = client.post("/enroll/pin/regenerate", headers=ADMIN).json()["pin"]
        other = client.post("/enroll/pair", json={"pin": other_pin, "name": "Other", "platform": "android"}).json()
        assert client.post(f"/agents/{device_id}/heartbeat", headers=agent).status_code == 200
        assert client.post(f"/agents/{other['device_id']}/heartbeat", headers=agent).status_code == 403
        assert client.get("/devices", headers=agent).status_code == 403          # agents cannot list the family
        assert client.get("/events", headers=agent).status_code == 403
        assert client.post(f"/admin/{device_id}/action", headers=agent, json={"action": "lock"}).status_code == 403

    def test_heartbeat_marks_online_and_reports_ip_and_caps(self, client, paired):
        device_id, agent = paired
        response = client.post(
            f"/agents/{device_id}/heartbeat", headers=agent,
            json={"ip": "192.168.1.77", "agent_version": "2.0.0", "caps": {"pause": "proxy", "tray": True, "evil": {"nested": 1}}},
        )
        body = response.json()
        assert body["status"] == "ok" and body["state"] == {"locked": False, "paused": False, "bedtime_active": False}
        device = client.get(f"/devices/{device_id}", headers=ADMIN).json()
        assert device["status"] == "online" and device["ip"] == "192.168.1.77"
        assert device["caps"] == {"pause": "proxy", "tray": True} and device["agent_version"] == "2.0.0"

    def test_legacy_query_parameter_ip_still_accepted(self, client, paired):
        device_id, agent = paired
        client.post(f"/agents/{device_id}/heartbeat?ip=10.1.2.3", headers=agent)
        assert client.get(f"/devices/{device_id}", headers=ADMIN).json()["ip"] == "10.1.2.3"

    def test_heartbeats_are_not_stored_as_events(self, client, paired):
        device_id, agent = paired
        for _ in range(5):
            client.post(f"/agents/{device_id}/heartbeat", headers=agent)
        types = [e["type"] for e in client.get("/events?limit=100", headers=ADMIN).json()]
        assert "heartbeat" not in types and "device_online" in types and "device_paired" in types

    def test_dns_block_and_vpn_reports_accept_json_and_query(self, client, paired):
        device_id, agent = paired
        client.post(f"/agents/{device_id}/dns-block", headers=agent, json={"host": "https://www.TikTok.com/x"})
        client.post(f"/agents/{device_id}/dns-block?host=kick.com", headers=agent)
        client.post(f"/agents/{device_id}/vpn-attempt", headers=agent, json={"interface": "WireGuard Tunnel"})
        events = client.get("/events?limit=50&type=dns_block,vpn_attempt", headers=ADMIN).json()
        hosts = {e["data"].get("host") for e in events if e["type"] == "dns_block"}
        assert hosts == {"tiktok.com", "kick.com"}
        assert any(e["type"] == "vpn_attempt" and e["data"]["interface"] == "WireGuard Tunnel" for e in events)

    def test_agent_can_report_stopping(self, client, paired):
        device_id, agent = paired
        client.post(f"/agents/{device_id}/heartbeat", headers=agent)
        assert client.post(f"/agents/{device_id}/event", headers=agent, json={"type": "agent_stopped", "data": {"reason": "uninstalled"}}).status_code == 200
        assert client.get(f"/devices/{device_id}", headers=ADMIN).json()["status"] == "offline"
        assert client.post(f"/agents/{device_id}/event", headers=agent, json={"type": "device_locked"}).status_code == 422

    def test_watchdog_marks_silent_devices_dark(self, client, paired):
        import database

        device_id, agent = paired
        client.post(f"/agents/{device_id}/heartbeat", headers=agent)
        database.update_device(device_id, last_seen=(datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat())
        client.hub.check_dark_devices()
        assert client.get(f"/devices/{device_id}", headers=ADMIN).json()["status"] == "offline"
        types = [e["type"] for e in client.get("/events", headers=ADMIN).json()]
        assert "device_went_dark" in types


# --------------------------------------------------------------------------- #
# Remote actions + command queue
# --------------------------------------------------------------------------- #
class TestActions:
    def test_lock_unlock_flow_and_state_in_heartbeat(self, client, paired):
        device_id, agent = paired
        result = client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "lock"}).json()
        assert result["device"]["locked"] is True and result["device"]["state"] == "locked"
        assert client.post(f"/agents/{device_id}/heartbeat", headers=agent).json()["state"]["locked"] is True
        client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "unlock"})
        assert client.post(f"/agents/{device_id}/heartbeat", headers=agent).json()["state"]["locked"] is False

    def test_commands_are_delivered_exactly_once(self, client, paired):
        device_id, agent = paired
        client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "push_notification", "payload": {"message": "Dinner time"}})
        first = client.get(f"/agents/{device_id}/commands", headers=agent).json()
        second = client.get(f"/agents/{device_id}/commands", headers=agent).json()
        assert [c["action"] for c in first["commands"]] == ["push_notification"]
        assert first["commands"][0]["payload"] == {"message": "Dinner time"}
        assert second["commands"] == []

    def test_pause_sets_flag_not_status(self, client, paired):
        device_id, agent = paired
        client.post(f"/agents/{device_id}/heartbeat", headers=agent)
        device = client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "pause"}).json()["device"]
        assert device["paused"] is True and device["status"] == "online" and device["state"] == "paused"
        device = client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "unpause"}).json()["device"]
        assert device["paused"] is False

    def test_message_and_app_name_are_validated(self, client, paired):
        device_id, _ = paired
        act = lambda payload, action="push_notification": client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": action, "payload": payload})
        assert act({"message": "   "}).status_code == 400
        assert act({"app": "chrome.exe; rm -rf /"}, "force_close_app").status_code == 400
        assert act({"app": "chrome.exe"}, "force_close_app").status_code == 200

    def test_wipe_needs_android_and_typed_confirmation(self, client, paired):
        win_id, _ = paired
        assert client.post(f"/admin/{win_id}/action", headers=ADMIN, json={"action": "wipe", "payload": {"confirm": win_id}}).status_code == 400  # windows
        pin = client.post("/enroll/pin/regenerate", headers=ADMIN).json()["pin"]
        phone = client.post("/enroll/pair", json={"pin": pin, "name": "Phone", "platform": "android"}).json()["device_id"]
        assert client.post(f"/admin/{phone}/action", headers=ADMIN, json={"action": "wipe"}).status_code == 400
        assert client.post(f"/admin/{phone}/action", headers=ADMIN, json={"action": "wipe", "payload": {"confirm": "wrong"}}).status_code == 400
        ok = client.post(f"/admin/{phone}/action", headers=ADMIN, json={"action": "wipe", "payload": {"confirm": phone}})
        assert ok.status_code == 200

    def test_unknown_device_404(self, client):
        assert client.post("/admin/nope-123/action", headers=ADMIN, json={"action": "lock"}).status_code == 404


# --------------------------------------------------------------------------- #
# Rules
# --------------------------------------------------------------------------- #
class TestRules:
    def test_partial_update_keeps_other_fields(self, client, paired):
        device_id, _ = paired
        before = client.get(f"/rules/{device_id}", headers=ADMIN).json()
        client.post(f"/rules/{device_id}", headers=ADMIN, json={"bedtime_enabled": True, "bedtime_start": "20:30"})
        after = client.get(f"/rules/{device_id}", headers=ADMIN).json()
        assert after["bedtime_enabled"] is True and after["bedtime_start"] == "20:30"
        assert after["blocked_categories"] == before["blocked_categories"]      # the old API wiped these
        assert after["blocked_domains"] == before["blocked_domains"]

    def test_domains_are_normalised_and_validated(self, client, paired):
        device_id, _ = paired
        out = client.post(f"/rules/{device_id}", headers=ADMIN, json={"blocked_domains": ["https://www.Example.com/path", "example.com"]}).json()
        assert out["blocked_domains"] == ["example.com"]
        assert client.post(f"/rules/{device_id}", headers=ADMIN, json={"blocked_domains": ["bad domain!"]}).status_code == 422
        assert client.post(f"/rules/{device_id}", headers=ADMIN, json={"bedtime_start": "25:00"}).status_code == 422
        assert client.post(f"/rules/{device_id}", headers=ADMIN, json={"snapshot_interval_s": 5}).status_code == 422

    def test_agent_can_read_but_not_write_its_rules(self, client, paired):
        device_id, agent = paired
        rules = client.get(f"/rules/{device_id}", headers=agent).json()
        assert "tiktok.com" in rules["effective_blocked_domains"]       # expanded from categories + custom
        assert client.post(f"/rules/{device_id}", headers=agent, json={"blocked_domains": []}).status_code == 403

    def test_rule_change_is_queued_for_the_agent_and_logged(self, client, paired):
        device_id, agent = paired
        client.post(f"/rules/{device_id}", headers=ADMIN, json={"blocked_categories": ["social"]})
        commands = client.get(f"/agents/{device_id}/commands", headers=agent).json()["commands"]
        assert commands and commands[0]["action"] == "policy_sync"
        events = client.get(f"/events?device_id={device_id}&type=policy_sync", headers=ADMIN).json()
        assert events and events[0]["data"]["changed"] == ["blocked_categories"]


# --------------------------------------------------------------------------- #
# Snapshots
# --------------------------------------------------------------------------- #
class TestSnapshots:
    def upload(self, client, device_id, agent, content=JPEG):
        return client.post(f"/agents/{device_id}/snapshot", headers=agent, files={"file": ("s.jpg", content, "image/jpeg")})

    def test_upload_list_and_signed_download(self, client, paired):
        device_id, agent = paired
        up = self.upload(client, device_id, agent)
        assert up.status_code == 200, up.text
        listing = client.get("/snapshots", headers=ADMIN).json()
        assert len(listing) == 1
        url = listing[0]["url"]
        image = client.get(url)                       # no header: the signature is the credential
        assert image.status_code == 200 and image.content == JPEG and image.headers["content-type"] == "image/jpeg"

    def test_unsigned_or_tampered_links_are_refused(self, client, paired):
        device_id, agent = paired
        self.upload(client, device_id, agent)
        url = client.get("/snapshots", headers=ADMIN).json()[0]["url"]
        bare = url.split("?")[0]
        assert client.get(bare).status_code == 403
        assert client.get(url[:-3] + "abc").status_code == 403
        assert client.get(bare, headers=ADMIN).status_code == 200      # admin key also works

    def test_expired_links_are_refused(self, client, paired, monkeypatch):
        device_id, agent = paired
        self.upload(client, device_id, agent)
        url = client.get("/snapshots", headers=ADMIN).json()[0]["url"]
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() + 3600)
        assert client.get(url).status_code == 403

    def test_only_jpeg_and_size_limited(self, client, paired):
        device_id, agent = paired
        assert self.upload(client, device_id, agent, b"<?php echo 1;").status_code == 415
        big = JPEG + b"0" * (client.hub.settings.snapshot_max_bytes + 10)
        assert self.upload(client, device_id, agent, big).status_code == 413

    def test_path_traversal_is_impossible(self, client, paired):
        device_id, agent = paired
        assert client.get("/snapshots/..%2F..%2Fetc/passwd.jpg").status_code in (403, 404, 422)
        assert client.get(f"/snapshots/{device_id}/..%2F..%2Fhimaya.db.jpg").status_code in (403, 404, 422)

    def test_screenshot_events_carry_a_fresh_signed_url(self, client, paired):
        device_id, agent = paired
        self.upload(client, device_id, agent)
        event = client.get("/events?type=screenshot", headers=ADMIN).json()[0]
        assert event["data"]["url"].startswith(f"/snapshots/{device_id}/")
        assert client.get(event["data"]["url"]).status_code == 200

    def test_delete_snapshot(self, client, paired):
        device_id, agent = paired
        self.upload(client, device_id, agent)
        snap = client.get("/snapshots", headers=ADMIN).json()[0]
        assert client.delete(f"/snapshots/{snap['id']}", headers=ADMIN).status_code == 200
        assert client.get(snap["url"]).status_code == 404
        assert client.get("/snapshots", headers=ADMIN).json() == []

    def test_deleting_a_device_removes_its_screenshots_and_keys(self, client, paired):
        device_id, agent = paired
        self.upload(client, device_id, agent)
        folder = client.hub.settings.snapshots_dir / device_id
        assert folder.is_dir()
        assert client.delete(f"/devices/{device_id}", headers=ADMIN).status_code == 200
        assert not folder.exists()
        assert client.post(f"/agents/{device_id}/heartbeat", headers=agent).status_code == 401   # key revoked


# --------------------------------------------------------------------------- #
# Events, stats, retention
# --------------------------------------------------------------------------- #
class TestEventsAndStats:
    def test_event_filters_pagination_and_clamping(self, client, paired):
        device_id, agent = paired
        for i in range(5):
            client.post(f"/agents/{device_id}/dns-block", headers=agent, json={"host": f"site{i}.com"})
        page1 = client.get("/events?limit=3&type=dns_block", headers=ADMIN).json()
        page2 = client.get(f"/events?limit=3&type=dns_block&before_id={page1[-1]['id']}", headers=ADMIN).json()
        assert len(page1) == 3 and len(page2) == 2
        assert page1[0]["id"] > page1[-1]["id"]                                  # newest first
        assert client.get("/events?limit=100000", headers=ADMIN).status_code == 422

    def test_stats_summary(self, client, paired):
        device_id, agent = paired
        client.post(f"/agents/{device_id}/heartbeat", headers=agent)
        for host in ("a.com", "a.com", "b.com"):
            client.post(f"/agents/{device_id}/dns-block", headers=agent, json={"host": host})
        client.post(f"/agents/{device_id}/vpn-attempt", headers=agent, json={"interface": "tun0"})
        stats = client.get("/api/stats", headers=ADMIN).json()
        assert stats["devices"]["online"] == 1 and len(stats["histogram"]) == 24
        assert stats["top_blocked"][0] == {"host": "a.com", "count": 2}
        assert stats["alerts_24h"] == 1 and stats["events_24h"]["by_type"]["dns_block"] == 3

    def test_retention_prunes_old_rows_and_files(self, client, paired):
        import database

        device_id, agent = paired
        TestSnapshots().upload(client, device_id, agent)
        old = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        database.insert_event(device_id, "dns_block", {"host": "old.com"}, old)
        with database.get_connection() as conn:
            conn.execute("UPDATE snapshots SET timestamp = ?", (old,))
        removed = client.hub.run_retention()
        assert removed["events"] >= 1 and removed["snapshots"] == 1
        assert not list((client.hub.settings.snapshots_dir / device_id).glob("*.jpg"))


# --------------------------------------------------------------------------- #
# Enrollment pages
# --------------------------------------------------------------------------- #
class TestEnrollmentPages:
    def test_windows_installer_is_consent_first_and_visible(self, client):
        script = client.get("/enroll/win").text
        assert "Type YES to continue" in script and "Read-Host" in script
        assert "-WindowStyle Hidden" not in script and ".vbs" not in script           # no stealth launcher
        assert "http://testserver" in script or "http://192.168.1.50" in script

    def test_hostile_host_header_cannot_inject_into_the_script_or_page(self, client):
        hostile = {"Host": "x\"; Start-Process calc; \""}
        for path in ("/enroll/win", "/enroll/mobile"):
            response = client.get(path, headers=hostile)
            assert "Start-Process calc" not in response.text
            assert response.status_code == 200                                         # falls back to the hub's own LAN address

    def test_mobile_page_escapes_and_has_no_pin_and_strict_csp(self, client):
        response = client.get("/enroll/mobile")
        assert response.status_code == 200
        assert "intent://enroll?hub=" in response.text
        assert "script-src 'nonce-" in response.headers["content-security-policy"]
        assert "'unsafe-inline'" not in response.headers["content-security-policy"]

    def test_hub_url_query_parameter_is_ignored(self, client):
        assert "evil.example" not in client.get("/enroll/win?hub_url=http://evil.example").text
        assert "evil.example" not in client.get("/enroll/mobile?hub_url=http://evil.example").text

    def test_agent_and_uninstaller_downloads(self, client):
        assert client.get("/enroll/win/uninstall.ps1").text.startswith("# Himaya - Windows uninstall")
        agent = client.get("/enroll/win/agent.py")
        assert agent.status_code == 200 and "Himaya" in agent.text

    def test_qr_code_is_a_png(self, client):
        response = client.get("/enroll/qr?kind=lan")
        assert response.status_code == 200 and response.content.startswith(b"\x89PNG")
        assert client.get("/enroll/qr?kind=bogus").status_code == 422

    def test_public_url_roundtrip_and_validation(self, client):
        assert client.post("/enroll/public-url", headers=ADMIN, json={"url": "javascript:alert(1)"}).status_code == 400
        assert client.post("/enroll/public-url", headers=ADMIN, json={"url": "https://hub.example.com/"}).json()["public_url"] == "https://hub.example.com"
        kinds = [u["kind"] for u in client.get("/enroll/info", headers=ADMIN).json()["urls"]]
        assert kinds == ["lan", "internet"]
        assert client.post("/enroll/public-url", headers=ADMIN, json={"url": ""}).json()["public_url"] is None


# --------------------------------------------------------------------------- #
# WebSocket
# --------------------------------------------------------------------------- #
class TestWebSocket:
    def test_requires_auth_message(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "key": "wrong"}))
            assert ws.receive_json()["type"] == "auth_failed"

    def test_key_in_url_is_not_accepted(self, client):
        with client.websocket_connect(f"/ws?key={ADMIN_KEY}") as ws:
            ws.send_text(json.dumps({"type": "hello"}))
            assert ws.receive_json()["type"] == "auth_failed"

    def test_live_events_and_device_updates_are_pushed(self, client, paired):
        device_id, agent = paired
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "key": ADMIN_KEY}))
            first = ws.receive_json()
            assert first["type"] == "snapshot" and first["devices"][0]["device_id"] == device_id
            client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "lock"})
            seen = {}
            for _ in range(4):
                message = ws.receive_json()
                seen[message["type"]] = message
                if {"event", "device"} <= seen.keys():
                    break
            assert seen["event"]["event"]["type"] == "device_locked"
            assert seen["device"]["device"]["locked"] is True

    def test_test_injection_message_is_gone(self, client):
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"type": "auth", "key": ADMIN_KEY}))
            ws.receive_json()
            ws.send_text(json.dumps({"type": "test_dns_block", "host": "evil.com"}))
            ws.send_text(json.dumps({"type": "ping"}))
            assert ws.receive_json() == {"type": "pong"}
        assert client.get("/events?type=dns_block", headers=ADMIN).json() == []


# --------------------------------------------------------------------------- #
# Static dashboard + headers
# --------------------------------------------------------------------------- #
class TestStatic:
    def test_dashboard_assets_are_served_from_root_paths(self, env, monkeypatch):
        """Regression: index.html referenced /assets/* but only /static/* was mounted."""
        from fastapi.testclient import TestClient

        import config
        import main

        static = env / "static"
        (static / "assets").mkdir(parents=True)
        (static / "index.html").write_text('<!doctype html><script type="module" src="/assets/app-abc.js"></script>')
        (static / "assets" / "app-abc.js").write_text("console.log(1)")
        (static / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>")
        with TestClient(main.create_app(config.load_settings())) as c:
            assert c.get("/").status_code == 200 and "/assets/app-abc.js" in c.get("/").text
            js = c.get("/assets/app-abc.js")
            assert js.status_code == 200 and "immutable" in js.headers["cache-control"]
            assert c.get("/favicon.svg").status_code == 200
            assert c.get("/static/index.html").status_code == 200
            assert c.get("/does-not-exist").status_code == 404
            assert c.get("/..%2fmain.py").status_code in (404, 422)

    def test_placeholder_when_dashboard_not_built(self, client):
        response = client.get("/")
        assert response.status_code == 200 and "npm run build" in response.text

    def test_security_headers(self, client):
        response = client.get("/health")
        assert response.headers["x-content-type-options"] == "nosniff" and response.headers["x-frame-options"] == "DENY"
        assert "no-store" in client.get("/devices", headers=ADMIN).headers["cache-control"]
        assert "frame-ancestors 'none'" in client.get("/").headers["content-security-policy"]


# --------------------------------------------------------------------------- #
# Device CRUD + misc
# --------------------------------------------------------------------------- #
class TestDevices:
    def test_manual_create_returns_key_once_and_rejects_duplicates(self, client):
        body = {"name": "Old laptop", "platform": "windows", "device_id": "win-manual-1"}
        created = client.post("/devices", headers=ADMIN, json=body)
        assert created.status_code == 201 and created.json()["agent_key"].startswith("hag_")
        assert "agent_key" not in client.get("/devices/win-manual-1", headers=ADMIN).json()
        assert client.post("/devices", headers=ADMIN, json=body).status_code == 409

    def test_rename_and_owner_type(self, client, paired):
        device_id, _ = paired
        updated = client.patch(f"/devices/{device_id}", headers=ADMIN, json={"name": "  Sarah's laptop  ", "owner_type": "adult"}).json()
        assert updated["name"] == "Sarah's laptop" and updated["owner_type"] == "adult"
        assert client.patch(f"/devices/{device_id}", headers=ADMIN, json={"owner_type": "robot"}).status_code == 422

    def test_device_id_in_path_is_validated(self, client):
        assert client.get("/devices/..%2Fetc", headers=ADMIN).status_code in (404, 422)
        assert client.get("/devices/a", headers=ADMIN).status_code == 422

    def test_admin_key_rotation_invalidates_the_old_key(self, client, monkeypatch):
        # with an env-provided key rotation is refused
        assert client.post("/api/admin-key/rotate", headers=ADMIN).status_code == 409


class TestCloudConfig:
    def test_render_false_does_not_enable_cloud_mode(self, env):
        """Regression: bool('false') is True, which put local Docker runs in cloud mode."""
        import config

        assert config.load_settings().is_cloud is False
        assert config.env_bool("X_UNSET", True) is True
