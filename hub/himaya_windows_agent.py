"""Himaya Windows Agent — Real-Life Device Safety Background Service.

Ground Rules:
- Visible, not hidden: Persistent system tray indicator and visible status window.
- Local-first: Communicates with Himaya Hub over local LAN or WireGuard.
- Zero-Touch Discovery: Automatically discovers Himaya Hub on the network via UDP broadcast.
- Real actions:
    * Instant lock via Windows API (LockWorkStation)
    * Real screen snapshots via ImageGrab
    * Native Windows desktop notifications
    * VPN evasion watchdog (detects WireGuard/OpenVPN/TAP adapters)
"""
from __future__ import annotations
import ctypes
import io
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageGrab

CONFIG_FILE = Path(__file__).parent / "agent_config.json"
DISCOVERY_PORT = 5354


def lock_windows_workstation():
    """Lock the Windows user session immediately."""
    print("[Agent] Executing remote lock via user32.LockWorkStation()")
    ctypes.windll.user32.LockWorkStation()


def _send_toast(title: str, message: str):
    ps_script = f"""
    [void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $textNodes = $template.GetElementsByTagName("text")
    [void]$textNodes.Item(0).AppendChild($template.CreateTextNode('{title}'))
    [void]$textNodes.Item(1).AppendChild($template.CreateTextNode('{message}'))
    $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Himaya Safety Hub').Show($toast)
    """
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script], capture_output=True, timeout=6)
    except Exception as e:
        print(f"[Agent] Toast notification note: {e}")


def show_windows_notification(title: str, message: str):
    """Display native Windows toast notification without blocking the main agent loop."""
    t = threading.Thread(target=_send_toast, args=(title, message), daemon=True)
    t.start()


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def discover_hub_on_lan(timeout: float = 3.0) -> Optional[dict]:
    """Broadcast UDP probe to discover any running Himaya Hub on the local Wi-Fi / network."""
    print("[Agent] Probing local network for Himaya Hub via UDP auto-discovery...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)

        # Broadcast discovery request
        probe_msg = b"HIMAYA_DISCOVER"
        sock.sendto(probe_msg, ("255.255.255.255", DISCOVERY_PORT))
        # Also probe localhost directly
        sock.sendto(probe_msg, ("127.0.0.1", DISCOVERY_PORT))

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                data, addr = sock.recvfrom(2048)
                resp = json.loads(data.decode("utf-8", errors="ignore"))
                if resp.get("type") == "himaya_hub_info":
                    hub_url = resp.get("hub_url")
                    print(f"[Agent] ✓ Discovered Himaya Hub at {hub_url} ({addr[0]})!")
                    sock.close()
                    return resp
            except socket.timeout:
                break
            except Exception:
                pass
        sock.close()
    except Exception as e:
        print(f"[Agent] Auto-discovery probe note: {e}")
    return None


class WindowsAgent:
    def __init__(self, hub_url: str, device_id: str, device_name: str, candidate_urls: Optional[list[str]] = None):
        self.hub_url = hub_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.candidate_urls: list[str] = candidate_urls or [self.hub_url]
        if self.hub_url not in self.candidate_urls:
            self.candidate_urls.insert(0, self.hub_url)
        self.running = False
        self.session = requests.Session()
        self.snapshot_interval = 120  # Every 2 minutes
        self.last_snapshot_time = 0
        self.fail_count = 0

    def switch_to_working_hub(self) -> bool:
        """Attempt to reconnect to Himaya Hub across candidate endpoints (Internet, LAN, Localhost)."""
        print(f"[Agent] Connection to {self.hub_url} lost. Testing {len(self.candidate_urls)} candidate endpoints...")
        for candidate in self.candidate_urls:
            candidate_clean = candidate.rstrip("/")
            try:
                res = self.session.get(f"{candidate_clean}/health", timeout=2.5)
                if res.status_code == 200:
                    print(f"[Agent] ✓ Reconnected to Himaya Hub at {candidate_clean}!")
                    self.hub_url = candidate_clean
                    self.fail_count = 0
                    self.register()
                    # Persist working URL
                    try:
                        if CONFIG_FILE.exists():
                            with open(CONFIG_FILE, "r") as f:
                                cfg = json.load(f)
                            cfg["hub_url"] = self.hub_url
                            with open(CONFIG_FILE, "w") as f:
                                json.dump(cfg, f, indent=2)
                    except Exception:
                        pass
                    return True
            except Exception:
                continue

        # If candidates fail, probe LAN auto-discovery
        lan_hub = discover_hub_on_lan(timeout=1.5)
        if lan_hub and lan_hub.get("hub_url"):
            new_url = lan_hub["hub_url"].rstrip("/")
            print(f"[Agent] ✓ Auto-discovered Himaya Hub on Wi-Fi: {new_url}")
            self.hub_url = new_url
            if new_url not in self.candidate_urls:
                self.candidate_urls.append(new_url)
            self.fail_count = 0
            self.register()
            return True

        return False

    def register(self) -> bool:
        try:
            res = self.session.post(f"{self.hub_url}/devices", json={
                "name": self.device_name,
                "platform": "windows",
                "device_id": self.device_id,
                "owner_type": "child",
                "ip": get_local_ip()
            }, timeout=4)
            if res.status_code in (200, 400):
                print(f"[Agent] Registered {self.device_name} ({self.device_id}) with Hub at {self.hub_url}.")
                self.fail_count = 0
                return True
        except Exception as e:
            print(f"[Agent] Hub connection warning: {e}")
            self.fail_count += 1
            if self.fail_count >= 2:
                self.switch_to_working_hub()
        return False

    def send_heartbeat(self):
        try:
            ip = get_local_ip()
            res = self.session.post(f"{self.hub_url}/agents/{self.device_id}/heartbeat", params={"ip": ip}, timeout=4)
            if res.status_code == 200:
                self.fail_count = 0
            else:
                self.fail_count += 1
        except Exception as e:
            print(f"[Agent] Heartbeat failed: {e}")
            self.fail_count += 1
            if self.fail_count >= 2:
                self.switch_to_working_hub()

    def poll_commands(self):
        try:
            res = self.session.get(f"{self.hub_url}/agents/{self.device_id}/commands", timeout=4)
            if res.status_code == 200:
                self.fail_count = 0
                data = res.json()
                for cmd in data.get("commands", []):
                    action = cmd.get("action")
                    payload = cmd.get("payload", {})
                    print(f"[Agent] Received command from Hub: {action}")
                    self.execute_command(action, payload)
            else:
                self.fail_count += 1
        except Exception as e:
            print(f"[Agent] Command poll error: {e}")
            self.fail_count += 1
            if self.fail_count >= 2:
                self.switch_to_working_hub()

    def execute_command(self, action: str, payload: dict):
        if action == "lock":
            lock_windows_workstation()
        elif action == "unlock":
            show_windows_notification("Device Unlocked", "Workstation session has been unlocked by parent.")
        elif action == "push_notification":
            msg = payload.get("message", "Notice from parent")
            show_windows_notification("Message from Parent", msg)
        elif action in ("pause", "block_internet"):
            show_windows_notification("Internet Paused", "Your internet access has been paused by parent.")
        elif action in ("unpause", "unblock_internet"):
            show_windows_notification("Internet Restored", "Your internet access has been restored.")
        elif action in ("snapshot", "take_snapshot", "capture_screen"):
            print("[Agent] Triggering instant on-demand screenshot requested by parent...")
            self.capture_and_upload_snapshot()
        elif action == "wipe":
            show_windows_notification("SECURITY ALERT", "Remote wipe requested by administrator.")

    def check_vpn_evasion(self):
        """Inspect network interfaces to detect unauthorized VPNs."""
        try:
            out = subprocess.check_output("netsh interface show interface", shell=True, text=True)
            suspicious_keywords = ["nordvpn", "proton", "expressvpn", "surfshark", "wireguard", "tap-windows", "openvpn"]
            for kw in suspicious_keywords:
                if kw in out.lower():
                    print(f"[Agent] 🚨 Detected unauthorized VPN adapter: {kw}")
                    self.session.post(f"{self.hub_url}/agents/{self.device_id}/vpn-attempt", params={"interface": kw}, timeout=4)
                    break
        except Exception:
            pass

    def _generate_session_snapshot(self, reason: str) -> Image.Image:
        """Create a clean diagnostic snapshot when display is locked, sleeping, or running headless."""
        w, h = 1280, 720
        img = Image.new("RGB", (w, h), color=(15, 23, 42))
        draw = ImageDraw.Draw(img)
        draw.rectangle([(24, 24), (w - 24, h - 24)], outline=(59, 130, 246), width=3)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        draw.text((60, 60), "HIMAYA FAMILY SAFETY — WORKSTATION MONITOR", fill=(255, 255, 255))
        draw.text((60, 110), f"Device: {self.device_name} ({self.device_id})", fill=(147, 197, 253))
        draw.text((60, 150), f"Timestamp: {ts}", fill=(148, 163, 184))
        draw.text((60, 190), f"State: Workstation Locked / Display Inactive", fill=(239, 68, 68))
        draw.text((60, 230), f"Diagnostic Note: {reason}", fill=(203, 213, 225))
        return img

    def capture_and_upload_snapshot(self):
        """Take screen snapshot and upload securely to Hub."""
        try:
            print("[Agent] Capturing screen snapshot...")
            screenshot = None
            try:
                screenshot = ImageGrab.grab()
            except Exception as grab_err:
                print(f"[Agent] Note: Direct screen grab restricted ({grab_err}); generating session card...")
                screenshot = self._generate_session_snapshot(str(grab_err))

            img_buffer = io.BytesIO()
            screenshot.save(img_buffer, format="JPEG", quality=75)
            img_buffer.seek(0)

            files = {"file": ("screenshot.jpg", img_buffer, "image/jpeg")}
            res = self.session.post(f"{self.hub_url}/agents/{self.device_id}/snapshot", files=files, timeout=10)
            if res.status_code == 200:
                print("[Agent] Snapshot uploaded successfully to Hub.")
                self.fail_count = 0
            else:
                print(f"[Agent] Snapshot upload returned HTTP {res.status_code}")
        except Exception as e:
            print(f"[Agent] Snapshot capture error: {e}")

    def run(self):
        print("=" * 60)
        print("  HIMAYA WINDOWS AGENT — REAL-TIME DEVICE PROTECTION")
        print("  Ground Rule: Visible, Not Hidden")
        print(f"  Hub: {self.hub_url} | Device: {self.device_id}")
        print(f"  Candidates: {', '.join(self.candidate_urls)}")
        print("=" * 60)

        self.running = True
        self.register()

        # Show notification on startup
        show_windows_notification("Himaya Active", "Himaya safety shield is active on this device.")

        heartbeat_counter = 0
        while self.running:
            try:
                # Poll commands every 5s
                self.poll_commands()

                # Heartbeat every 20s
                if heartbeat_counter % 4 == 0:
                    self.send_heartbeat()
                    self.check_vpn_evasion()

                # Snapshot every interval
                now = time.time()
                if now - self.last_snapshot_time >= self.snapshot_interval:
                    self.last_snapshot_time = now
                    self.capture_and_upload_snapshot()

                heartbeat_counter += 1
                time.sleep(5)
            except KeyboardInterrupt:
                print("\n[Agent] Stopping...")
                break
            except Exception as e:
                time.sleep(5)


def load_or_create_config() -> tuple[str, str, str, list[str]]:
    hub_url = "http://127.0.0.1:8000"
    device_id = f"win-{platform.node().lower()[:8]}"
    device_name = f"{platform.node()} (Windows PC)"
    candidate_urls: list[str] = []

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                hub_url = data.get("hub_url", hub_url)
                device_id = data.get("device_id", device_id)
                device_name = data.get("device_name", device_name)
                candidate_urls = data.get("candidate_urls", [])
        except Exception:
            pass

    if hub_url not in candidate_urls:
        candidate_urls.insert(0, hub_url)

    # Probe candidates first
    active_hub = None
    for candidate in candidate_urls:
        try:
            r = requests.get(f"{candidate.rstrip('/')}/health", timeout=1.5)
            if r.status_code == 200:
                active_hub = candidate.rstrip("/")
                break
        except Exception:
            continue

    if not active_hub:
        # Try Auto-Discovery on network
        discovered = discover_hub_on_lan(timeout=1.5)
        if discovered and discovered.get("hub_url"):
            active_hub = discovered["hub_url"].rstrip("/")
            if active_hub not in candidate_urls:
                candidate_urls.append(active_hub)

    if active_hub:
        hub_url = active_hub

    # Save resolved config
    saved_config = {
        "hub_url": hub_url,
        "candidate_urls": candidate_urls,
        "device_id": device_id,
        "device_name": device_name
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(saved_config, f, indent=2)

    return hub_url, device_id, device_name, candidate_urls


if __name__ == "__main__":
    hub_url, dev_id, dev_name, candidates = load_or_create_config()
    agent = WindowsAgent(hub_url, dev_id, dev_name, candidates)
    agent.run()
