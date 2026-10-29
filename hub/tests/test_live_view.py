"""Live view: short, parent-started, visible to the child, memory-only.

Rules these tests lock in:
  * it only starts when the agent says it can (caps.live_view), is online and unlocked;
  * it follows the screenshot consent rule: screenshots off -> live view off;
  * the agent can only send frames while a session the PARENT started is open;
  * frames live in memory only (never in the snapshots folder or the database);
  * a session ends on stop, on time-out, and when the device is removed.
"""
from __future__ import annotations

import time

from conftest import ADMIN, JPEG


def go_online(client, device_id, agent, live=True):
    caps = {"os": "windows", "live_view": live, "screenshots": True}
    response = client.post(f"/agents/{device_id}/heartbeat", headers=agent, json={"caps": caps})
    assert response.status_code == 200, response.text


def start(client, device_id, **payload):
    return client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "live_view", "payload": payload})


def frame(client, device_id, agent, data=JPEG):
    return client.post(f"/agents/{device_id}/live-frame", headers=agent, files={"file": ("f.jpg", data, "image/jpeg")})


class TestStarting:
    def test_refused_when_the_agent_cannot_do_it(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent, live=False)
        response = start(client, device_id)
        assert response.status_code == 400 and "can't do live view" in response.json()["detail"]

    def test_refused_while_offline(self, client, paired):
        device_id, agent = paired   # paired but no heartbeat yet -> offline
        client.post(f"/agents/{device_id}/heartbeat", headers=agent, json={"caps": {"live_view": True}})
        import database
        database.update_device(device_id, status="offline")
        assert start(client, device_id).status_code == 409

    def test_follows_the_screenshot_consent_rule(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        client.post(f"/rules/{device_id}", headers=ADMIN, json={"snapshot_interval_s": 0})
        response = start(client, device_id)
        assert response.status_code == 409 and "Screenshots are turned off" in response.json()["detail"]

    def test_refused_while_locked(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "lock"})
        assert start(client, device_id).status_code == 409

    def test_happy_path_queues_the_command_and_records_the_event(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        response = start(client, device_id, duration_s=45)
        assert response.status_code == 200, response.text
        live = response.json()["live"]
        assert live["duration_s"] == 45 and live["url"].startswith(f"/live/{device_id}?exp=")
        commands = client.get(f"/agents/{device_id}/commands", headers=agent).json()["commands"]
        assert [c["action"] for c in commands if c["action"] == "live_view"] == ["live_view"]
        assert [c["payload"] for c in commands if c["action"] == "live_view"][0]["duration_s"] == 45
        events = client.get("/events?type=live_started", headers=ADMIN).json()
        assert events and events[0]["data"]["duration_s"] == 45

    def test_duration_is_clamped(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        assert start(client, device_id, duration_s=99999).json()["live"]["duration_s"] == 120
        assert start(client, device_id, duration_s=1).json()["live"]["duration_s"] == 10
        assert start(client, device_id, duration_s="soon").json()["live"]["duration_s"] == 60


class TestFrames:
    def test_agent_cannot_send_frames_without_a_session(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        assert frame(client, device_id, agent).status_code == 409

    def test_frames_reach_the_parent_through_a_signed_link_only(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        url = start(client, device_id).json()["live"]["url"]
        assert client.get(url).status_code == 404                      # no frame yet
        assert frame(client, device_id, agent).status_code == 200
        shown = client.get(url)
        assert shown.status_code == 200 and shown.content == JPEG
        assert shown.headers["cache-control"] == "no-store"
        assert client.get(f"/live/{device_id}").status_code == 403      # unsigned
        assert client.get(f"/live/{device_id}?exp=1&sig=bad").status_code == 403
        assert client.get(f"/live/{device_id}", headers=ADMIN).status_code == 200   # the parent's own key works

    def test_bad_frames_and_fast_frames_are_refused(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        start(client, device_id)
        assert frame(client, device_id, agent, b"not a jpeg").status_code == 415
        assert frame(client, device_id, agent).status_code == 200
        assert frame(client, device_id, agent).status_code == 429       # inside the minimum gap

    def test_another_device_cannot_use_this_session(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        start(client, device_id)
        pin = client.get("/enroll/info", headers=ADMIN).json()["pin"]
        other = client.post("/enroll/pair", json={"pin": pin, "name": "Other", "platform": "windows", "owner_type": "child"}).json()
        response = client.post(f"/agents/{device_id}/live-frame", headers={"X-API-Key": other["agent_key"]}, files={"file": ("f.jpg", JPEG, "image/jpeg")})
        assert response.status_code in (401, 403)

    def test_frames_are_never_written_to_disk_or_the_database(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        start(client, device_id)
        assert frame(client, device_id, agent).status_code == 200
        folder = client.hub.settings.snapshots_dir / device_id
        assert not folder.exists() or not any(folder.iterdir())
        assert client.get("/snapshots", headers=ADMIN).json() == []


class TestEnding:
    def test_parent_can_stop_it(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        url = start(client, device_id).json()["live"]["url"]
        frame(client, device_id, agent)
        client.get(f"/agents/{device_id}/commands", headers=agent)     # drain the start command
        assert client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "stop_live_view"}).status_code == 200
        assert frame(client, device_id, agent).status_code == 409
        assert client.get(url).status_code == 404                       # the last frame is gone
        commands = client.get(f"/agents/{device_id}/commands", headers=agent).json()["commands"]
        assert any(c["action"] == "stop_live_view" for c in commands)
        ended = client.get("/events?type=live_ended", headers=ADMIN).json()
        assert ended and ended[0]["data"]["reason"] == "stopped by the parent"

    def test_stopping_when_nothing_is_running_is_harmless(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        assert client.post(f"/admin/{device_id}/action", headers=ADMIN, json={"action": "stop_live_view"}).status_code == 200
        assert client.get("/events?type=live_ended", headers=ADMIN).json() == []

    def test_it_ends_by_itself(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        start(client, device_id)
        client.hub.live[device_id]["expires"] = time.time() - 1
        assert frame(client, device_id, agent).status_code == 409
        assert client.get("/events?type=live_ended", headers=ADMIN).json()[0]["data"]["reason"] == "time ran out"
        assert device_id not in client.hub.live

    def test_removing_the_device_ends_it(self, client, paired):
        device_id, agent = paired
        go_online(client, device_id, agent)
        start(client, device_id)
        assert client.delete(f"/devices/{device_id}", headers=ADMIN).status_code == 200
        assert device_id not in client.hub.live
