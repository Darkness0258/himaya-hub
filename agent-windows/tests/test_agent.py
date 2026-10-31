"""Agent <-> hub integration tests. The hub is real (uvicorn in a thread); only Windows itself is faked."""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pytest

import himaya_windows_agent as agent


def wait_for(predicate, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.02)
    return False


# --------------------------------------------------------------------------- #
# Hub contract
# --------------------------------------------------------------------------- #
class TestHubContract:
    def test_heartbeat_marks_online_with_ip_caps_and_version(self, enrolled):
        enrolled.core.heartbeat_once()
        device = enrolled.parent("get", f"/devices/{enrolled.device_id}").json()
        assert device["status"] == "online" and device["ip"] == "192.168.1.55"      # old agent sent the IP in a body the hub ignored
        assert device["agent_version"] == agent.AGENT_VERSION
        assert device["caps"]["pause"] == "proxy" and device["caps"]["wipe"] is False and device["caps"]["tray"] is True
        assert enrolled.core.connected and enrolled.core.state == {"locked": False, "paused": False, "bedtime_active": False}

    def test_rules_schema_is_understood(self, enrolled):
        """Regression: RuleSet(**data) raised on the hub's field names, so rules were never applied."""
        enrolled.core.heartbeat_once()
        rules = enrolled.core.client.rules()
        assert "tiktok.com" in rules["effective_blocked_domains"] and "bedtime_start" in rules

    def test_unknown_key_is_rejected_cleanly(self, enrolled):
        client = agent.HubClient([enrolled.base], enrolled.device_id, "hag_not_a_real_key")
        with pytest.raises(agent.AuthRejected):
            client.heartbeat("1.2.3.4", {})

    def test_failover_to_second_url(self, enrolled):
        client = agent.HubClient(["http://127.0.0.1:9", enrolled.base], enrolled.device_id, enrolled.agent_key)
        assert client.heartbeat("1.2.3.4", {})["status"] == "ok" and client.active == enrolled.base

    def test_all_urls_down_is_a_state_not_a_crash(self, enrolled):
        core = enrolled.core
        core.client = agent.HubClient(["http://127.0.0.1:9"], enrolled.device_id, enrolled.agent_key)
        core.heartbeat_once()
        assert core.connected is False and "Can't reach" in core.status_text()

    def test_own_traffic_ignores_the_system_proxy(self, enrolled):
        assert enrolled.core.client.session.trust_env is False


# --------------------------------------------------------------------------- #
# Lock / pause / bedtime (desired state, enforced locally)
# --------------------------------------------------------------------------- #
class TestEnforcement:
    def test_lock_and_unlock(self, enrolled):
        core = enrolled.core
        core.heartbeat_once()
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "lock"})
        core.heartbeat_once()
        core.enforce_once()
        core.enforce_once()
        assert core.state["locked"] and enrolled.platform.locks == 2          # re-locks every tick: a child cannot just sign back in
        assert any("locked" in message.lower() for _, message in enrolled.ui.notifications)
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "unlock"})
        core.heartbeat_once()
        locks_before = enrolled.platform.locks
        core.enforce_once()
        assert not core.state["locked"] and enrolled.platform.locks == locks_before
        assert any("unlocked" in message.lower() for _, message in enrolled.ui.notifications)

    def test_missed_lock_command_cannot_desync(self, enrolled):
        """Lock is hub *state*, so even if the command poll never ran the next heartbeat still locks."""
        core = enrolled.core
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "lock"})
        core.heartbeat_once()                          # never called poll_commands_once
        core.enforce_once()
        assert enrolled.platform.locks == 1

    def test_pause_engages_and_restores_the_users_own_proxy(self, enrolled):
        core, fake = enrolled.core, enrolled.platform
        fake.proxy = {"enable": 1, "server": "proxy.corp:8080", "override": "intranet"}
        core.heartbeat_once()
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "pause"})
        core.heartbeat_once()
        core.enforce_once()
        assert fake.proxy["server"] == agent.BLACKHOLE_PROXY and fake.proxy["enable"] == 1
        assert any("paused the internet" in m for _, m in enrolled.ui.notifications)
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "unpause"})
        core.heartbeat_once()
        core.enforce_once()
        assert fake.proxy == {"enable": 1, "server": "proxy.corp:8080", "override": "intranet"}
        assert any("back on" in m for _, m in enrolled.ui.notifications)

    def test_agent_still_reaches_the_hub_while_paused(self, enrolled):
        """The pause is a dead proxy; the agent must ignore it or the parent could never un-pause."""
        core = enrolled.core
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "pause"})
        core.heartbeat_once()
        core.enforce_once()
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "unpause"})
        core.heartbeat_once()
        assert core.connected and not core.state["paused"]

    def test_child_switching_the_proxy_off_is_undone_without_corrupting_the_backup(self, enrolled):
        core, fake = enrolled.core, enrolled.platform
        fake.proxy = {"enable": 0, "server": None, "override": None}
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "pause"})
        core.heartbeat_once()
        core.enforce_once()
        fake.proxy = {"enable": 0, "server": agent.BLACKHOLE_PROXY, "override": "<local>"}      # child unticks the proxy
        core.enforce_once()
        assert fake.proxy["enable"] == 1                                                         # re-engaged
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "unpause"})
        core.heartbeat_once()
        core.enforce_once()
        assert fake.proxy["server"] is None and fake.proxy["enable"] == 0                         # not stuck on the dead proxy

    def test_crash_recovery_restores_internet_on_next_start(self, enrolled, tmp_path):
        """If the agent died while paused, the saved backup lets the next run put things back."""
        core, fake = enrolled.core, enrolled.platform
        fake.proxy = {"enable": 1, "server": "corp:3128", "override": None}
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "pause"})
        core.heartbeat_once()
        core.enforce_once()
        saved = json.loads((tmp_path / "agent_config.json").read_text())
        assert saved["proxy_backup"]["server"] == "corp:3128"
        # "new process": fresh core reading the saved config; the hub says nothing is paused any more
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "unpause"})
        client = agent.HubClient([enrolled.base], enrolled.device_id, enrolled.agent_key)
        core2 = agent.AgentCore(saved, client, fake, ui=enrolled.ui, config_path=tmp_path / "agent_config.json", hosts_path=enrolled.hosts_path)
        core2.heartbeat_once()
        core2.enforce_once()
        assert fake.proxy["server"] == "corp:3128" and fake.proxy["enable"] == 1

    def test_bedtime_window_pauses_and_says_when_it_ends(self, enrolled):
        core, fake = enrolled.core, enrolled.platform
        now = datetime.now()
        start, end = (now - timedelta(hours=1)).strftime("%H:%M"), (now + timedelta(hours=1)).strftime("%H:%M")
        enrolled.parent("post", f"/rules/{enrolled.device_id}", json={"bedtime_enabled": True, "bedtime_start": start, "bedtime_end": end})
        core.heartbeat_once()
        core.refresh_rules()
        core.enforce_once()
        assert core.state["bedtime_active"] and fake.proxy["server"] == agent.BLACKHOLE_PROXY
        assert any("Bedtime" in m and end in m for _, m in enrolled.ui.notifications)
        assert "Bedtime" in core.status_text()

    def test_released_when_the_hub_forgets_this_pc(self, enrolled):
        core, fake = enrolled.core, enrolled.platform
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "pause"})
        core.heartbeat_once()
        core.enforce_once()
        assert fake.proxy["server"] == agent.BLACKHOLE_PROXY
        enrolled.parent("delete", f"/devices/{enrolled.device_id}")
        core.heartbeat_once()
        assert core.auth_ok is False and fake.proxy["server"] is None            # never leave a PC permanently offline
        assert not core.state["locked"] and "removed" in core.status_text()


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
class TestCommands:
    def test_push_message_is_shown(self, enrolled):
        enrolled.core.heartbeat_once()
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "push_notification", "payload": {"message": "Dinner time"}})
        enrolled.core.poll_commands_once()
        assert wait_for(lambda: enrolled.platform.messages == [("Message from your parent", "Dinner time")])

    def test_close_app(self, enrolled):
        core = enrolled.core
        assert core.close_app("chrome") and enrolled.platform.killed == ["chrome.exe"]
        assert not core.close_app("explorer") and not core.close_app("python.exe") and not core.close_app("a; calc")
        assert enrolled.platform.killed == ["chrome.exe"]

    def test_screenshot_now_reaches_the_hub(self, enrolled):
        core = enrolled.core
        core.heartbeat_once()
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "snapshot"})
        core.poll_commands_once()
        shots = enrolled.parent("get", "/snapshots").json()
        assert len(shots) == 1 and shots[0]["device_id"] == enrolled.device_id
        import requests

        assert requests.get(enrolled.base + shots[0]["url"], timeout=5).content[:3] == b"\xff\xd8\xff"

    def test_no_screenshot_while_locked_or_offline(self, enrolled):
        core = enrolled.core
        assert core.snapshot_once() is False                                       # not connected yet
        core.heartbeat_once()
        core.state["locked"] = True
        assert core.snapshot_once() is False and enrolled.platform.shots == 0

    def test_wipe_is_refused_on_windows(self, enrolled):
        enrolled.core.execute("wipe", {"confirmed": True})
        events = enrolled.parent("get", "/events?type=enforcement_notice").json()
        assert events and "not supported" in events[0]["data"]["message"]


# --------------------------------------------------------------------------- #
# Screenshot schedule (respects the hub's interval; adults default to off)
# --------------------------------------------------------------------------- #
class TestSnapshotSchedule:
    def test_due_logic_follows_the_hub_interval(self, enrolled):
        core = enrolled.core
        core.snapshot_interval = 120
        now = time.time()
        core.last_snapshot = now - 60
        assert not core.snapshot_due(now)
        core.last_snapshot = now - 121
        assert core.snapshot_due(now)
        core.snapshot_interval = 0
        assert not core.snapshot_due(now + 10_000)

    def test_first_screenshot_is_one_interval_after_start(self, enrolled):
        core = enrolled.core
        core.snapshot_interval = 300
        assert not core.snapshot_due(time.time())

    def test_adult_devices_get_no_schedule_from_the_hub(self, live_hub, platform, tmp_path):
        import requests

        from conftest import ADMIN

        base, _ = live_hub
        pin = requests.get(base + "/enroll/info", headers=ADMIN, timeout=5).json()["pin"]
        paired = requests.post(base + "/enroll/pair", json={"pin": pin, "name": "Dad", "platform": "windows", "owner_type": "adult"}, timeout=5).json()
        client = agent.HubClient([base], paired["device_id"], paired["agent_key"])
        core = agent.AgentCore({"owner_type": "adult"}, client, platform, ui=None, hosts_path=tmp_path / "hosts")
        core.heartbeat_once()
        assert core.snapshot_interval == 0 and core.extra_text() == "Screenshots: off"
        assert not core.snapshot_due(time.time() + 10_000)


# --------------------------------------------------------------------------- #
# VPN guard
# --------------------------------------------------------------------------- #
class TestVpnGuard:
    def test_reported_once_per_appearance(self, enrolled):
        core, fake = enrolled.core, enrolled.platform
        fake.vpns = ["WireGuard Tunnel - WireGuard Tunnel"]
        core.vpn_check_once()
        core.vpn_check_once()                                                      # still up: no spam
        events = enrolled.parent("get", "/events?type=vpn_attempt").json()
        assert len(events) == 1 and "WireGuard" in events[0]["data"]["interface"]
        fake.vpns = []
        core.vpn_check_once()
        fake.vpns = ["WireGuard Tunnel - WireGuard Tunnel"]
        core.vpn_check_once()
        assert len(enrolled.parent("get", "/events?type=vpn_attempt").json()) == 2

    def test_keyword_list_does_not_match_normal_adapters(self):
        benign = ["Ethernet|Realtek PCIe GbE Family Controller", "Wi-Fi|Intel(R) Wi-Fi 6 AX201 160MHz", "vEthernet (Default Switch)|Hyper-V Virtual Ethernet Adapter",
                  "Bluetooth Network Connection|Bluetooth Device (Personal Area Network)"]
        assert not [line for line in benign if any(word in line.lower() for word in agent.VPN_KEYWORDS)]
        assert any(word in "OpenVPN TAP-Windows Adapter V9".lower() for word in agent.VPN_KEYWORDS)


# --------------------------------------------------------------------------- #
# Hosts file (needs Administrator in real life)
# --------------------------------------------------------------------------- #
class TestHostsFile:
    ORIGINAL = "# Copyright\r\n127.0.0.1 localhost\r\n::1 localhost\r\n10.0.0.5 nas.local\r\n"

    def test_block_is_added_and_everything_else_survives(self, tmp_path):
        path = tmp_path / "hosts"
        path.write_bytes(self.ORIGINAL.encode())
        hosts = agent.HostsBlocklist(path)
        assert hosts.apply(["tiktok.com", "kick.com"]) is True
        text = path.read_bytes().decode()
        assert text.startswith(self.ORIGINAL.rstrip("\r\n")) and "0.0.0.0 tiktok.com" in text and "0.0.0.0 www.kick.com" in text
        assert "\r\n" in text and "\n" not in text.replace("\r\n", "")              # CRLF preserved
        assert hosts.apply(["tiktok.com", "kick.com"]) is False                    # idempotent: no pointless rewrite

    def test_entries_added_after_our_block_by_other_software_survive(self, tmp_path):
        """Regression: the old agent cut the file at the start marker and destroyed what followed."""
        path = tmp_path / "hosts"
        path.write_bytes(self.ORIGINAL.encode())
        hosts = agent.HostsBlocklist(path)
        hosts.apply(["tiktok.com"])
        path.write_bytes(path.read_bytes() + b"192.168.9.9 printer.local\r\n")
        hosts.apply(["kick.com"])
        text = path.read_bytes().decode()
        assert "printer.local" in text and "nas.local" in text
        assert "tiktok.com" not in text and "0.0.0.0 kick.com" in text
        assert text.count(agent.HOSTS_START) == 1

    def test_remove_restores_the_original_and_is_a_noop_when_clean(self, tmp_path):
        path = tmp_path / "hosts"
        path.write_bytes(self.ORIGINAL.encode())
        hosts = agent.HostsBlocklist(path)
        assert hosts.remove() is False and path.read_bytes().decode() == self.ORIGINAL
        hosts.apply(["tiktok.com"])
        assert hosts.remove() is True and path.read_bytes().decode() == self.ORIGINAL

    def test_missing_file_is_not_created_by_remove(self, tmp_path):
        hosts = agent.HostsBlocklist(tmp_path / "nope")
        assert hosts.remove() is False and not (tmp_path / "nope").exists()

    def test_hub_rules_flow_into_the_hosts_file_when_admin(self, enrolled):
        core = enrolled.core
        enrolled.platform.admin = True
        core.is_admin = core.hosts_enabled = True
        enrolled.hosts_path.write_bytes(self.ORIGINAL.encode())
        core.heartbeat_once()                                                      # first heartbeat also fetches the rules
        text = enrolled.hosts_path.read_text()
        assert "0.0.0.0 tiktok.com" in text and "nas.local" in text and enrolled.platform.flushes == 1
        enrolled.parent("post", f"/rules/{enrolled.device_id}", json={"blocked_categories": [], "blocked_domains": ["only-this.test"]})
        core.poll_commands_once()                                                  # policy_sync command -> immediate refresh
        text = enrolled.hosts_path.read_text()
        assert "only-this.test" in text and "tiktok.com" not in text

    def test_without_admin_the_hosts_file_is_left_alone(self, enrolled):
        enrolled.hosts_path.write_bytes(self.ORIGINAL.encode())
        enrolled.core.heartbeat_once()
        assert enrolled.hosts_path.read_bytes() == self.ORIGINAL.encode()
        assert enrolled.core.caps()["hosts_blocking"] is False

    def test_permission_error_disables_blocking_and_tells_the_parent(self, enrolled, monkeypatch):
        core = enrolled.core
        core.hosts_enabled = True

        def deny(_domains):
            raise PermissionError("denied")

        monkeypatch.setattr(core.hosts, "apply", deny)
        core.rules = {"effective_blocked_domains": ["tiktok.com"]}
        core.apply_hosts()
        assert core.hosts_enabled is False
        assert enrolled.parent("get", "/events?type=enforcement_notice").json()


# --------------------------------------------------------------------------- #
# Lifecycle, visibility, config
# --------------------------------------------------------------------------- #
class TestLifecycle:
    def test_shutdown_tells_the_hub_and_releases_the_internet(self, enrolled):
        core, fake = enrolled.core, enrolled.platform
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "pause"})
        core.heartbeat_once()
        core.enforce_once()
        core.shutdown("test")
        assert fake.proxy["server"] is None
        assert enrolled.parent("get", f"/devices/{enrolled.device_id}").json()["status"] == "offline"
        assert enrolled.parent("get", "/events?type=agent_stopped").json()

    def test_background_threads_really_run(self, enrolled, monkeypatch):
        monkeypatch.setattr(agent, "HEARTBEAT_S", 0.05)
        core = enrolled.core
        threads = core.start_threads()
        assert wait_for(lambda: enrolled.parent("get", f"/devices/{enrolled.device_id}").json()["status"] == "online")
        core.shutdown("test")
        for thread in threads:
            thread.join(timeout=3)
        assert not any(t.is_alive() for t in threads)

    def test_status_text_and_levels(self, enrolled):
        core = enrolled.core
        assert "Can't reach" in core.status_text()
        core.heartbeat_once()
        assert core.status_text() == "Connected to the hub" and enrolled.ui.levels[-1][0] == "ok"
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "lock"})
        core.heartbeat_once()
        assert enrolled.ui.levels[-1][0] == "warn" and "Locked" in enrolled.ui.levels[-1][1]

    def test_the_tray_has_no_quit_entry_and_always_explains_itself(self):
        source = open(agent.__file__, encoding="utf-8").read()
        menu_block = source[source.index("menu = pystray.Menu("):source.index("self.icon = pystray.Icon")]
        assert "Quit" not in menu_block and "Exit" not in menu_block
        assert "What does Himaya do?" in menu_block and "Himaya is active" in menu_block
        assert "never" in agent.ABOUT_TEXT and "screenshot" in agent.ABOUT_TEXT

    def test_icon_renders_in_every_state(self):
        for level in ("ok", "warn", "off"):
            image = agent.draw_icon(level)
            assert image.size == (64, 64) and image.getpixel((32, 32))[3] == 255

    def test_config_loading(self, tmp_path):
        good = tmp_path / "c.json"
        good.write_bytes(b"\xef\xbb\xbf" + json.dumps({"hub_url": "http://h", "device_id": "d", "agent_key": "k"}).encode())   # PowerShell 5 BOM
        assert agent.load_config(good)["device_id"] == "d"
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"hub_url": "http://h"}))
        with pytest.raises(ValueError):
            agent.load_config(bad)

    def test_once_flag_reports_connection(self, enrolled, monkeypatch, capsys, tmp_path):
        cfg = tmp_path / "agent_config.json"
        cfg.write_text(json.dumps({"hub_url": enrolled.base, "device_id": enrolled.device_id, "agent_key": enrolled.agent_key}))
        monkeypatch.setattr(agent, "CONFIG_PATH", cfg)
        monkeypatch.setattr(agent, "WindowsPlatform", lambda: enrolled.platform)
        assert agent.main(["--once"]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output["connected"] is True and output["state"]["locked"] is False


# --------------------------------------------------------------------------- #
# Live view: parent-started, short, and announced on the PC
# --------------------------------------------------------------------------- #
class TestLiveView:
    def test_the_agent_announces_that_it_can_do_it(self, enrolled):
        assert enrolled.core.caps()["live_view"] is True

    def test_full_round_trip_with_the_hub(self, enrolled):
        core, device_id = enrolled.core, enrolled.device_id
        core.heartbeat_once()
        started = enrolled.parent("post", f"/admin/{device_id}/action", json={"action": "live_view", "payload": {"duration_s": 30}})
        assert started.status_code == 200, started.text
        core.poll_commands_once()                                   # receives the live_view command
        assert wait_for(lambda: enrolled.hub.live.get(device_id, {}).get("frames", 0) >= 1, timeout=5)
        # The parent can see the picture; the person at the PC was told, and the tray shows it.
        picture = enrolled.parent("get", f"/live/{device_id}")
        assert picture.status_code == 200 and picture.content[:3] == b"\xff\xd8\xff"
        assert any("viewing your screen" in message for _, message in enrolled.ui.notifications)
        assert enrolled.ui.levels[-1][0] == "warn" and "viewing your screen" in enrolled.ui.levels[-1][1]
        # The parent stops it: the agent stops sending and says so.
        enrolled.parent("post", f"/admin/{device_id}/action", json={"action": "stop_live_view"})
        core.poll_commands_once()
        assert wait_for(lambda: not core.live_active, timeout=5)
        # The flag clears a moment before the notice and the tray refresh, so wait for those too.
        assert wait_for(lambda: any(message == "Live view ended." for _, message in enrolled.ui.notifications), timeout=5)
        assert wait_for(lambda: enrolled.ui.levels[-1][0] == "ok", timeout=5)

    def test_it_stops_by_itself_when_the_hub_has_no_session(self, enrolled):
        core = enrolled.core
        core.heartbeat_once()
        assert core.start_live_view(30) is True                      # nobody asked the hub: it answers 409
        assert wait_for(lambda: not core.live_active, timeout=5)
        assert enrolled.parent("get", "/snapshots").json() == []   # and nothing was stored

    def test_not_while_locked_or_offline(self, enrolled):
        core = enrolled.core
        assert core.start_live_view(30) is False                    # never connected to the hub
        core.heartbeat_once()
        core.state["locked"] = True
        assert core.start_live_view(30) is False and not core.live_active
        assert enrolled.platform.shots == 0

    def test_only_one_session_at_a_time(self, enrolled):
        core = enrolled.core
        core.heartbeat_once()
        core.live_active = True                                     # one is already running
        assert core.start_live_view(30) is False

    def test_the_length_is_capped_on_the_pc_too(self, enrolled, monkeypatch):
        core = enrolled.core
        core.heartbeat_once()
        seen = []
        monkeypatch.setattr(core, "_live_loop", lambda seconds: seen.append(seconds))
        core.start_live_view(99999)
        assert wait_for(lambda: seen, timeout=2) and seen == [agent.LIVE_MAX_S]
        core.live_active = False
        core.start_live_view(1)
        assert wait_for(lambda: len(seen) == 2, timeout=2) and seen[1] == agent.LIVE_MIN_S

    def test_shutdown_ends_it(self, enrolled):
        core = enrolled.core
        core.heartbeat_once()
        enrolled.parent("post", f"/admin/{enrolled.device_id}/action", json={"action": "live_view", "payload": {"duration_s": 60}})
        core.poll_commands_once()
        assert wait_for(lambda: core.live_active, timeout=3)
        core.shutdown("test")
        assert wait_for(lambda: not core.live_active, timeout=5)


# --------------------------------------------------------------------------- #
# Hardened install: the agent folder is read-only for the child
# --------------------------------------------------------------------------- #
class TestReadOnlyInstallFolder:
    @pytest.fixture()
    def clean_logger(self):
        import logging

        root = logging.getLogger("himaya")
        before = list(root.handlers)
        yield root
        for handler in list(root.handlers):
            if handler not in before:
                handler.close()
                root.removeHandler(handler)

    def test_log_falls_back_to_the_users_own_folder(self, tmp_path, monkeypatch, clean_logger):
        blocker = tmp_path / "program_files_himaya"
        blocker.write_text("this is a file, so nothing can be created inside it")   # stands in for a folder the child cannot write
        local = tmp_path / "local"
        monkeypatch.setattr(agent, "LOG_PATH", blocker / "agent.log")
        monkeypatch.setenv("LOCALAPPDATA", str(local))
        agent.setup_logging(console=False)
        clean_logger.info("hello from a hardened install")
        import logging

        for handler in clean_logger.handlers:
            if isinstance(handler, logging.FileHandler):   # other tests may have left console handlers behind
                handler.flush()
        assert "hello from a hardened install" in (local / "HimayaAgent" / "agent.log").read_text(encoding="utf-8")

    def test_no_writable_place_for_the_log_is_not_fatal(self, tmp_path, monkeypatch, clean_logger):
        blocker = tmp_path / "blocked"
        blocker.write_text("x")
        monkeypatch.setattr(agent, "LOG_PATH", blocker / "agent.log")
        monkeypatch.delenv("LOCALAPPDATA", raising=False)
        before = len(clean_logger.handlers)
        agent.setup_logging(console=False)               # must not raise
        assert len(clean_logger.handlers) == before

    def test_an_unwritable_config_does_not_break_pausing(self, enrolled, tmp_path):
        core = enrolled.core
        blocker = tmp_path / "ro"
        blocker.write_text("x")
        core.config_path = blocker / "agent_config.json"  # cannot be written
        core.save_config()                                 # swallowed, as in a read-only install folder
        core.heartbeat_once()
        core.set_proxy_blackhole(True)
        assert enrolled.platform.proxy["server"] == agent.BLACKHOLE_PROXY
        core.set_proxy_blackhole(False)
        assert enrolled.platform.proxy["server"] in (None, "")
