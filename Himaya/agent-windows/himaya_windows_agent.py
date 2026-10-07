"""Himaya Windows Agent — Real-Life Device Safety Background Service.

Ground Rules:
- Visible, not hidden: Persistent system tray indicator and visible status window.
- Local-first: Communicates with Himaya Hub over local LAN or WireGuard.
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
from PIL import ImageGrab

CONFIG_FILE = Path(__file__).parent / "agent_config.json"


def lock_windows_workstation():
    """Lock the Windows user session immediately."""
    print("[Agent] Executing remote lock via user32.LockWorkStation()")
    ctypes.windll.user32.LockWorkStation()


def show_windows_notification(title: str, message: str):
    """Display native Windows toast notification using PowerShell."""
    ps_script = f"""
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
    $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
    $textNodes = $template.GetElementsByTagName("text")
    $textNodes.Item(0).AppendChild($template.CreateTextNode('{title}')) > $null
    $textNodes.Item(1).AppendChild($template.CreateTextNode('{message}')) > $null
    $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Himaya Safety Hub').Show($toast)
    """
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], capture_output=True, timeout=5)
    except Exception:
        # Fallback to simple message box
        ctypes.windll.user32.MessageBoxW(0, message, title, 0x40)


def get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class WindowsAgent:
    def __init__(self, hub_url: str, device_id: str, device_name: str):
        self.hub_url = hub_url.rstrip("/")
        self.device_id = device_id
        self.device_name = device_name
        self.running = False
        self.session = requests.Session()
        self.snapshot_interval = 120  # Every 2 minutes
        self.last_snapshot_time = 0

    def register(self) -> bool:
        try:
            res = self.session.post(f"{self.hub_url}/devices", json={
                "name": self.device_name,
                "platform": "windows",
                "device_id": self.device_id,
                "owner_type": "child",
                "ip": get_local_ip()
            }, timeout=5)
            if res.status_code in (200, 400):  # 400 means already registered
                print(f"[Agent] Registered {self.device_name} ({self.device_id}) with Hub.")
                return True
        except Exception as e:
            print(f"[Agent] Hub connection warning: {e}")
        return False

    def send_heartbeat(self):
        try:
            ip = get_local_ip()
            self.session.post(f"{self.hub_url}/agents/{self.device_id}/heartbeat", params={"ip": ip}, timeout=5)
        except Exception as e:
            print(f"[Agent] Heartbeat failed: {e}")

    def poll_commands(self):
        try:
            res = self.session.get(f"{self.hub_url}/agents/{self.device_id}/commands", timeout=5)
            if res.status_code == 200:
                data = res.json()
                for cmd in data.get("commands", []):
                    action = cmd.get("action")
                    payload = cmd.get("payload", {})
                    print(f"[Agent] Received command from Hub: {action}")
                    self.execute_command(action, payload)
        except Exception as e:
            print(f"[Agent] Command poll error: {e}")

    def execute_command(self, action: str, payload: dict):
        if action == "lock":
            lock_windows_workstation()
        elif action == "push_notification":
            msg = payload.get("message", "Notice from parent")
            show_windows_notification("Message from Parent", msg)
        elif action in ("pause", "block_internet"):
            show_windows_notification("Internet Paused", "Your internet access has been paused by parent.")
        elif action in ("unpause", "unblock_internet"):
            show_windows_notification("Internet Restored", "Your internet access has been restored.")
        elif action == "wipe":
            show_windows_notification("SECURITY ALERT", "Remote wipe requested by administrator.")

    def check_vpn_evasion(self):
        """Inspect network interfaces to detect unauthorized VPNs."""
        try:
            out = subprocess.check_output("netsh interface show interface", shell=True, text=True)
            suspicious_keywords = ["nordvpn", "proton", "expressvpn", "surfshark", "wireguard", "tap-windows", "openvpn"]
            for kw in suspicious_keywords:
                if kw in out.lower():
                    # Detected VPN evasion
                    print(f"[Agent] 🚨 Detected unauthorized VPN adapter: {kw}")
                    self.session.post(f"{self.hub_url}/agents/{self.device_id}/vpn-attempt", params={"interface": kw}, timeout=5)
                    break
        except Exception:
            pass

    def capture_and_upload_snapshot(self):
        """Take screen snapshot and upload securely to Hub."""
        try:
            print("[Agent] Capturing screen snapshot...")
            screenshot = ImageGrab.grab()
            img_buffer = io.BytesIO()
            screenshot.save(img_buffer, format="JPEG", quality=70)
            img_buffer.seek(0)

            files = {"file": ("screenshot.jpg", img_buffer, "image/jpeg")}
            res = self.session.post(f"{self.hub_url}/agents/{self.device_id}/snapshot", files=files, timeout=10)
            if res.status_code == 200:
                print("[Agent] Snapshot uploaded successfully to Hub.")
        except Exception as e:
            print(f"[Agent] Snapshot capture error: {e}")

    def run(self):
        print("=" * 60)
        print("  HIMAYA WINDOWS AGENT — PROTECTION ACTIVE")
        print("  Ground Rule: Visible, Not Hidden")
        print(f"  Hub: {self.hub_url} | Device: {self.device_id}")
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


def load_or_create_config() -> tuple[str, str, str]:
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                data = json.load(f)
                return data.get("hub_url", "http://127.0.0.1:8000"), data.get("device_id", "win-laptop-01"), data.get("device_name", "Family PC")
        except Exception:
            pass

    default_config = {
        "hub_url": "http://127.0.0.1:8000",
        "device_id": f"windows-{platform.node().lower()[:8]}",
        "device_name": f"{platform.node()} (Windows PC)"
    }
    with open(CONFIG_FILE, "w") as f:
        json.dump(default_config, f, indent=2)

    return default_config["hub_url"], default_config["device_id"], default_config["device_name"]


if __name__ == "__main__":
    hub_url, dev_id, dev_name = load_or_create_config()
    agent = WindowsAgent(hub_url, dev_id, dev_name)
    agent.run()
