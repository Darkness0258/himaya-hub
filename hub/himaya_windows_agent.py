#!/usr/bin/env python3
"""Himaya Windows agent.

A small, *visible* family-safety agent for a Windows PC. Ground rules (from the
project spec): visible, not hidden; consent first; events not content.

What it does
------------
* Shows a "Himaya active" icon in the system tray the whole time it runs.
* Sends a heartbeat so the parent sees the PC is online (and is alerted if it goes dark).
* Follows the hub's *desired state*: locked / internet paused / bedtime.
* Applies the website block list (hosts file - needs Administrator; skipped otherwise).
* Warns the parent when a VPN adapter comes up.
* Child PCs only: sends a screenshot to the parent's own hub every N minutes.
* Runs parent commands: lock, send a message, close an app, screenshot now.

What it never does: log keystrokes, use the camera/microphone, read private messages,
or hide itself.

Install: use the one-liner from the dashboard's Enroll page (it asks for consent).
Run by hand: ``python himaya_windows_agent.py`` (``--console`` shows logs, ``--once`` checks the hub).

Requires: Python 3.9+, ``requests``, ``pillow``, ``pystray`` (the tray falls back to a small window).
"""
from __future__ import annotations

import argparse
import atexit
import io
import json
import logging
import logging.handlers
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

AGENT_VERSION = "2.0.0"
APP_DIR = Path(__file__).resolve().parent
CONFIG_PATH = APP_DIR / "agent_config.json"
LOG_PATH = APP_DIR / "agent.log"

HEARTBEAT_S = 20
COMMAND_POLL_S = 5
ENFORCE_S = 5
VPN_CHECK_S = 45
RULES_REFRESH_S = 300
DEFAULT_SNAPSHOT_S = 300
BLACKHOLE_PROXY = "127.0.0.1:9"
HOSTS_START = "# HIMAYA BLOCKLIST START"
HOSTS_END = "# HIMAYA BLOCKLIST END"

VPN_KEYWORDS = (
    "wireguard", "wintun", "tap-windows", "tap-win32", "openvpn", "nordlynx", "protonvpn", "expressvpn",
    "surfshark", "mullvad", "cyberghost", "windscribe", "tunnelbear", "hotspot shield", "anyconnect",
    "globalprotect", "pangp", "forticlient", "fortinet", "zerotier", "tailscale", "hamachi", "softether",
    "ivpn", "private internet access", "ipvanish", "hide.me", "psiphon", "vpn client",
)
PROTECTED_PROCESSES = {
    "explorer.exe", "winlogon.exe", "csrss.exe", "services.exe", "svchost.exe", "lsass.exe", "wininit.exe",
    "system", "smss.exe", "dwm.exe", "python.exe", "pythonw.exe", "py.exe",
}
ABOUT_TEXT = (
    "Himaya is a family safety program that your family set up on this computer.\n\n"
    "It shows this icon whenever it is running.\n\n"
    "What it does:\n"
    "  - tells your parent's hub that this computer is online\n"
    "  - lets your parent lock the screen, send you a message, or pause the internet\n"
    "  - blocks websites your parent chose\n"
    "  - warns your parent if a VPN app is started\n"
    "  - may take a screenshot every few minutes and send it to your parent's hub (never anywhere else)\n\n"
    "What it never does: record what you type, use the camera or microphone, or read private messages."
)

log = logging.getLogger("himaya.agent")


# --------------------------------------------------------------------------- #
# Hub client
# --------------------------------------------------------------------------- #
class HubUnreachable(Exception):
    pass


class AuthRejected(Exception):
    """The hub no longer accepts this device's key (device removed, or hub was reset)."""


class HubClient:
    def __init__(self, urls: List[str], device_id: str, agent_key: str, session: Any = None):
        import requests  # imported lazily so unit tests can run without it

        self.urls = [u.rstrip("/") for u in dict.fromkeys(urls) if u]
        self.active = self.urls[0]
        self.device_id = device_id
        self.session = session or requests.Session()
        # Never route our own traffic through the system proxy: "pause internet" uses one.
        self.session.trust_env = False
        self.session.headers.update({"X-API-Key": agent_key, "User-Agent": f"himaya-agent/{AGENT_VERSION}"})
        self._requests = requests

    def _request(self, method: str, path: str, timeout=(4, 15), **kwargs):
        order = [self.active] + [u for u in self.urls if u != self.active]
        last: Optional[Exception] = None
        for base in order:
            try:
                response = self.session.request(method, base + path, timeout=timeout, **kwargs)
            except self._requests.RequestException as exc:
                last = exc
                continue
            if response.status_code in (401, 403):
                raise AuthRejected(response.text[:120])
            self.active = base
            return response
        raise HubUnreachable(str(last))

    def heartbeat(self, ip: str, caps: Dict[str, Any]) -> Dict[str, Any]:
        response = self._request("POST", f"/agents/{self.device_id}/heartbeat", json={"ip": ip, "caps": caps, "agent_version": AGENT_VERSION})
        response.raise_for_status()
        return response.json()

    def commands(self) -> Dict[str, Any]:
        response = self._request("GET", f"/agents/{self.device_id}/commands")
        response.raise_for_status()
        return response.json()

    def rules(self) -> Dict[str, Any]:
        response = self._request("GET", f"/rules/{self.device_id}")
        response.raise_for_status()
        return response.json()

    def report_vpn(self, interface: str) -> None:
        self._request("POST", f"/agents/{self.device_id}/vpn-attempt", json={"interface": interface})

    def report_event(self, event_type: str, data: Dict[str, Any]) -> None:
        self._request("POST", f"/agents/{self.device_id}/event", json={"type": event_type, "data": data}, timeout=(3, 6))

    def upload_snapshot(self, jpeg: bytes) -> None:
        response = self._request("POST", f"/agents/{self.device_id}/snapshot", files={"file": ("screen.jpg", jpeg, "image/jpeg")}, timeout=(5, 30))
        response.raise_for_status()


# --------------------------------------------------------------------------- #
# Hosts-file block list (needs Administrator)
# --------------------------------------------------------------------------- #
class HostsBlocklist:
    """Manages ONLY the marked Himaya block; everything else in the file is left alone.

    The first version cut the file at the start marker (losing any entries after
    it) and "restored" a stale backup on exit, overwriting changes made by other
    programs in the meantime.
    """

    _BLOCK_RE = re.compile(r"\r?\n?" + re.escape(HOSTS_START) + r".*?" + re.escape(HOSTS_END) + r"[ \t]*\r?\n?", re.DOTALL)

    def __init__(self, path: Optional[Path] = None, flush: Optional[Callable[[], None]] = None):
        windir = os.environ.get("SystemRoot", r"C:\Windows")
        self.path = Path(path) if path else Path(windir) / "System32" / "drivers" / "etc" / "hosts"
        self._flush = flush

    def _read(self) -> str:
        # Read bytes: read_text() would translate CRLF to LF and we would silently change the file's line endings.
        return self.path.read_bytes().decode("utf-8", errors="replace") if self.path.exists() else ""

    @staticmethod
    def _newline(text: str) -> str:
        return "\r\n" if "\r\n" in text else ("\n" if "\n" in text else "\r\n")

    def render(self, domains: List[str], newline: str) -> str:
        lines = [HOSTS_START, "# Managed by Himaya - do not edit between these markers"]
        for domain in domains[:2000]:
            lines.append(f"0.0.0.0 {domain}")
            if not domain.startswith("www."):
                lines.append(f"0.0.0.0 www.{domain}")
        lines.append(HOSTS_END)
        return newline.join(lines)

    def apply(self, domains: List[str]) -> bool:
        """Write the block (or remove it if ``domains`` is empty). Returns True if the file changed."""
        text = self._read()
        if not domains and HOSTS_START not in text:
            return False  # nothing of ours to remove; don't touch the file
        newline = self._newline(text)
        stripped = self._BLOCK_RE.sub(newline, text).rstrip("\r\n")
        new_text = stripped
        if domains:
            new_text = (stripped + newline + newline if stripped else "") + self.render(domains, newline)
        new_text += newline
        if new_text == text:
            return False
        with open(self.path, "w", encoding="utf-8", newline="") as handle:  # Path.write_text(newline=) needs 3.10+
            handle.write(new_text)
        if self._flush:
            self._flush()
        return True

    def remove(self) -> bool:
        return self.apply([])


# --------------------------------------------------------------------------- #
# Platform layer (real Windows implementation; tests substitute a fake)
# --------------------------------------------------------------------------- #
def _no_window_kwargs() -> Dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {}


class WindowsPlatform:
    REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

    # -- identity / privileges ---------------------------------------------- #
    def is_admin(self) -> bool:
        try:
            import ctypes

            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def local_ip(self) -> str:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))  # no packets are sent
                return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"

    # -- UI helpers ---------------------------------------------------------- #
    def lock_workstation(self) -> None:
        import ctypes

        ctypes.windll.user32.LockWorkStation()

    def message_box(self, title: str, text: str) -> None:
        """Blocking message box; callers run it in a thread."""
        try:
            import ctypes

            MB_OK, MB_ICONINFORMATION, MB_SYSTEMMODAL, MB_SETFOREGROUND = 0x0, 0x40, 0x1000, 0x10000
            ctypes.windll.user32.MessageBoxW(0, text, title, MB_OK | MB_ICONINFORMATION | MB_SYSTEMMODAL | MB_SETFOREGROUND)
        except Exception:
            log.info("%s: %s", title, text)

    # -- per-user proxy ("pause internet" without Administrator) ------------- #
    def read_proxy(self) -> Dict[str, Any]:
        import winreg

        out: Dict[str, Any] = {"enable": 0, "server": None, "override": None}
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH) as key:
            for field, name in (("enable", "ProxyEnable"), ("server", "ProxyServer"), ("override", "ProxyOverride")):
                try:
                    out[field] = winreg.QueryValueEx(key, name)[0]
                except FileNotFoundError:
                    pass
        return out

    def write_proxy(self, enable: int, server: Optional[str], override: Optional[str]) -> None:
        import ctypes
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.REG_PATH, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, int(enable))
            for name, value in (("ProxyServer", server), ("ProxyOverride", override)):
                if value:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
                else:
                    try:
                        winreg.DeleteValue(key, name)
                    except FileNotFoundError:
                        pass
        wininet = ctypes.windll.wininet
        wininet.InternetSetOptionW(None, 39, None, 0)  # INTERNET_OPTION_SETTINGS_CHANGED
        wininet.InternetSetOptionW(None, 37, None, 0)  # INTERNET_OPTION_REFRESH

    # -- system queries / actions --------------------------------------------- #
    def list_vpn_adapters(self) -> List[str]:
        script = "Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object { $_.Name + '|' + $_.InterfaceDescription }"
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, text=True, timeout=25, **_no_window_kwargs(),
            )
        except (OSError, subprocess.SubprocessError):
            return []
        found = []
        for line in result.stdout.splitlines():
            if any(word in line.lower() for word in VPN_KEYWORDS):
                found.append(line.replace("|", " - ").strip())
        return found

    def grab_screenshot_jpeg(self, quality: int = 55, max_width: int = 1280) -> bytes:
        from PIL import Image, ImageGrab

        image = ImageGrab.grab(all_screens=True).convert("RGB")
        if image.width > max_width:
            resample = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
        image = image.resize((max_width, int(image.height * max_width / image.width)), resample)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        return buffer.getvalue()

    def kill_process(self, image_name: str) -> bool:
        try:
            result = subprocess.run(["taskkill", "/IM", image_name, "/F"], capture_output=True, timeout=15, **_no_window_kwargs())
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def flush_dns(self) -> None:
        try:
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=15, **_no_window_kwargs())
        except (OSError, subprocess.SubprocessError):
            pass


# --------------------------------------------------------------------------- #
# Tray indicator (always visible) with a tiny-window fallback
# --------------------------------------------------------------------------- #
def draw_icon(level: str = "ok"):
    """Procedural 64px icon: lapis disc with an eight-point star. ``level``: ok | warn | off."""
    from PIL import Image, ImageDraw
    import math

    size = 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    colours = {"ok": ((35, 58, 140), (230, 191, 115)), "warn": ((120, 70, 20), (255, 200, 90)), "off": ((70, 76, 96), (170, 176, 196))}
    disc, star = colours.get(level, colours["ok"])
    draw.ellipse((2, 2, size - 2, size - 2), fill=disc)
    points = []
    for i in range(16):
        radius = 26 if i % 2 == 0 else 13
        angle = math.pi / 8 * i - math.pi / 2
        points.append((size / 2 + radius * math.cos(angle), size / 2 + radius * math.sin(angle)))
    draw.polygon(points, fill=star)
    return image


class TrayUI:
    """System tray icon. There is deliberately no Quit entry: the indicator stays visible."""

    def __init__(self, platform: Any, get_status: Callable[[], str], get_extra: Callable[[], str]):
        self.platform = platform
        self.get_status = get_status
        self.get_extra = get_extra
        self.icon = None
        self.level = "ok"
        self._tk_root = None

    def run_blocking(self, on_ready: Callable[[], None]) -> None:
        try:
            import pystray
        except Exception:
            log.warning("pystray is not installed; using a small status window instead")
            self._run_tk(on_ready)
            return
        menu = pystray.Menu(
            pystray.MenuItem("Himaya is active", None, enabled=False),
            pystray.MenuItem(lambda item: self.get_status(), None, enabled=False),
            pystray.MenuItem(lambda item: self.get_extra(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("What does Himaya do?", lambda icon, item: threading.Thread(
                target=self.platform.message_box, args=("About Himaya", ABOUT_TEXT), daemon=True).start()),
        )
        self.icon = pystray.Icon("himaya", draw_icon("ok"), "Himaya active", menu)
        self.icon.run(setup=lambda icon: (setattr(icon, "visible", True), on_ready()))

    def _run_tk(self, on_ready: Callable[[], None]) -> None:
        try:
            import tkinter as tk
        except Exception:
            log.error("No tray and no tkinter: running without a visible indicator is not allowed.")
            raise SystemExit("Himaya needs the 'pystray' package (pip install pystray pillow) to show its indicator.")
        root = tk.Tk()
        root.title("Himaya is active")
        root.geometry("320x120")
        root.resizable(False, False)
        label = tk.Label(root, text="Himaya is active on this computer", font=("Segoe UI", 11, "bold"), pady=10)
        label.pack()
        status = tk.Label(root, text="", font=("Segoe UI", 10))
        status.pack()
        extra = tk.Label(root, text="", font=("Segoe UI", 9))
        extra.pack()
        root.protocol("WM_DELETE_WINDOW", root.iconify)  # closing minimises; it never exits
        self._tk_root = root

        def refresh() -> None:
            status.config(text=self.get_status())
            extra.config(text=self.get_extra())
            root.after(2000, refresh)

        root.after(100, lambda: (on_ready(), refresh()))
        root.mainloop()

    def set_level(self, level: str, tooltip: str) -> None:
        if self.icon is not None:
            try:
                if level != self.level:
                    self.icon.icon = draw_icon(level)
                self.icon.title = tooltip[:120]
            except Exception:
                pass
        self.level = level

    def notify(self, title: str, message: str) -> None:
        if self.icon is not None:
            try:
                self.icon.notify(message, title)
                return
            except Exception:
                pass
        threading.Thread(target=self.platform.message_box, args=(title, message), daemon=True).start()

    def stop(self) -> None:
        if self.icon is not None:
            try:
                self.icon.stop()
            except Exception:
                pass
        if self._tk_root is not None:
            try:
                self._tk_root.after(0, self._tk_root.destroy)
            except Exception:
                pass


# --------------------------------------------------------------------------- #
# Agent core
# --------------------------------------------------------------------------- #
class AgentCore:
    def __init__(self, config: Dict[str, Any], client: HubClient, platform: Any, ui: Optional[Any] = None,
                 config_path: Optional[Path] = None, hosts_path: Optional[Path] = None):
        self.config = config
        self.client = client
        self.platform = platform
        self.ui = ui
        self.config_path = config_path
        self.stop_event = threading.Event()
        self.state: Dict[str, Any] = {"locked": False, "paused": False, "bedtime_active": False}
        self.rules: Dict[str, Any] = {}
        self.snapshot_interval = DEFAULT_SNAPSHOT_S
        self.connected = False
        self.auth_ok = True
        self.last_snapshot = time.time()
        self.last_rules_fetch = 0.0
        self.was_locked = False
        self.was_paused = False
        self.known_vpns: set = set()
        self.is_admin = platform.is_admin()
        self.hosts = HostsBlocklist(path=hosts_path, flush=getattr(platform, "flush_dns", None))
        self.hosts_enabled = self.is_admin
        self._lock = threading.Lock()
        self.dns_port: Optional[int] = None

    # -- capabilities / status text ------------------------------------------ #
    def caps(self) -> Dict[str, Any]:
        return {
            "os": "windows", "tray": self.ui is not None, "admin": self.is_admin, "lock": True,
            "pause": "proxy", "hosts_blocking": self.hosts_enabled, "screenshots": True, "wipe": False,
        }

    def status_text(self) -> str:
        if not self.auth_ok:
            return "This PC was removed from the hub"
        if not self.connected:
            return "Can't reach the hub right now"
        if self.state["locked"]:
            return "Locked by your parent"
        if self.state["paused"]:
            return "Internet paused by your parent"
        if self.state["bedtime_active"]:
            return "Bedtime: internet is off"
        return "Connected to the hub"

    def extra_text(self) -> str:
        interval = self.snapshot_interval
        if interval <= 0:
            return "Screenshots: off"
        return f"Screenshots: every {max(1, round(interval / 60))} min"

    def _refresh_ui(self) -> None:
        if not self.ui:
            return
        if not self.auth_ok or not self.connected:
            level = "off"
        elif self.state["locked"] or self.state["paused"] or self.state["bedtime_active"]:
            level = "warn"
        else:
            level = "ok"
        self.ui.set_level(level, f"Himaya active - {self.status_text()}")

    def notify(self, title: str, message: str) -> None:
        log.info("notify: %s - %s", title, message)
        if self.ui:
            self.ui.notify(title, message)

    # -- hub conversation ------------------------------------------------------ #
    def apply_hub_state(self, reply: Dict[str, Any]) -> None:
        state = reply.get("state") or {}
        with self._lock:
            self.state = {
                "locked": bool(state.get("locked")),
                "paused": bool(state.get("paused")),
                "bedtime_active": bool(state.get("bedtime_active")),
            }
            interval = reply.get("snapshot_interval_s")
            if isinstance(interval, int):
                self.snapshot_interval = interval
            self.dns_port = reply.get("dns_port")
        self._refresh_ui()

    def heartbeat_once(self) -> None:
        try:
            reply = self.client.heartbeat(self.platform.local_ip(), self.caps())
        except HubUnreachable:
            if self.connected:
                log.warning("Lost contact with the hub")
            self.connected = False
            self._refresh_ui()
            return
        except AuthRejected:
            self.handle_auth_rejected()
            return
        if not self.connected:
            log.info("Connected to the hub at %s", self.client.active)
        self.connected = True
        self.auth_ok = True
        self.apply_hub_state(reply)
        if time.time() - self.last_rules_fetch > RULES_REFRESH_S:
            self.refresh_rules()

    def handle_auth_rejected(self) -> None:
        if self.auth_ok:
            self.auth_ok = False
            self.notify("Himaya", "The hub no longer recognises this computer. Internet and screen locks are released.")
            log.error("Hub rejected our key - releasing all enforcement")
        self.connected = False
        self.state = {"locked": False, "paused": False, "bedtime_active": False}
        self.release_enforcement()
        self._refresh_ui()

    def refresh_rules(self) -> None:
        try:
            self.rules = self.client.rules()
        except (HubUnreachable, AuthRejected, Exception) as exc:  # noqa: BLE001 - never crash the loop
            log.debug("rules fetch failed: %s", exc)
            return
        self.last_rules_fetch = time.time()
        self.apply_hosts()

    def apply_hosts(self) -> None:
        if not self.hosts_enabled:
            return
        domains = list(self.rules.get("effective_blocked_domains") or [])
        try:
            if self.hosts.apply(domains):
                log.info("Updated hosts-file block list (%d domains)", len(domains))
        except PermissionError:
            self.hosts_enabled = False
            log.warning("Cannot write the hosts file (not Administrator). Website blocking via the hosts file is off.")
            self.report_enforcement("Website blocking needs Administrator rights on this PC; it is switched off here.")
        except OSError as exc:
            log.warning("hosts file error: %s", exc)

    def report_enforcement(self, message: str) -> None:
        try:
            self.client.report_event("enforcement_notice", {"message": message})
        except Exception:  # noqa: BLE001
            pass

    # -- commands ---------------------------------------------------------------- #
    def poll_commands_once(self) -> None:
        try:
            reply = self.client.commands()
        except HubUnreachable:
            return
        except AuthRejected:
            self.handle_auth_rejected()
            return
        if reply.get("state"):
            self.apply_hub_state({"state": reply["state"], "snapshot_interval_s": self.snapshot_interval, "dns_port": self.dns_port})
        for command in reply.get("commands", []):
            try:
                self.execute(command.get("action", ""), command.get("payload") or {})
            except Exception:  # noqa: BLE001
                log.exception("Command %s failed", command.get("action"))

    def execute(self, action: str, payload: Dict[str, Any]) -> None:
        log.info("command: %s", action)
        if action == "push_notification":
            message = str(payload.get("message", ""))[:500]
            if message:
                threading.Thread(target=self.platform.message_box, args=("Message from your parent", message), daemon=True).start()
        elif action == "force_close_app":
            self.close_app(str(payload.get("app", "")))
        elif action == "snapshot":
            self.snapshot_once("requested")
        elif action == "policy_sync":
            self.refresh_rules()
        elif action == "wipe":
            self.report_enforcement("Remote wipe is not supported on Windows PCs.")
        # lock / unlock / pause / unpause / block_internet / unblock_internet are *state*: they arrive via
        # the heartbeat and the command poll's state block, so a missed command can never leave us out of sync.

    def close_app(self, name: str) -> bool:
        name = name.strip()
        if not re.match(r"^[A-Za-z0-9_. -]{1,80}$", name):
            return False
        image = name if name.lower().endswith(".exe") else name + ".exe"
        if image.lower() in PROTECTED_PROCESSES:
            self.report_enforcement(f"Refused to close protected program {image}.")
            return False
        return bool(self.platform.kill_process(image))

    # -- enforcement ----------------------------------------------------------------- #
    def want_internet_paused(self) -> bool:
        return bool(self.state["paused"] or self.state["bedtime_active"])

    def enforce_once(self) -> None:
        locked = self.state["locked"]
        if locked:
            if not self.was_locked:
                self.notify("Himaya", "Your parent locked this computer.")
            try:
                self.platform.lock_workstation()
            except Exception:  # noqa: BLE001
                log.exception("LockWorkStation failed")
        elif self.was_locked:
            self.notify("Himaya", "Your parent unlocked this computer.")
        self.was_locked = locked

        paused = self.want_internet_paused()
        try:
            self.set_proxy_blackhole(paused)
        except Exception:  # noqa: BLE001
            log.exception("Could not change the internet pause setting")
        if paused and not self.was_paused:
            if self.state["bedtime_active"] and not self.state["paused"]:
                end = self.rules.get("bedtime_end", "")
                self.notify("Himaya", f"Bedtime: the internet is off{' until ' + end if end else ''}.")
            else:
                self.notify("Himaya", "Your parent paused the internet.")
        elif self.was_paused and not paused:
            self.notify("Himaya", "The internet is back on.")
        self.was_paused = paused

    def set_proxy_blackhole(self, on: bool) -> None:
        try:
            current = self.platform.read_proxy()
        except Exception:  # not Windows / registry unavailable
            return
        engaged = current.get("enable") == 1 and current.get("server") == BLACKHOLE_PROXY
        if on and not engaged:
            if current.get("server") != BLACKHOLE_PROXY:  # never back up our own blackhole (e.g. a child switched it off)
                self.config["proxy_backup"] = {"enable": current.get("enable", 0), "server": current.get("server"), "override": current.get("override")}
                self.save_config()
            self.platform.write_proxy(1, BLACKHOLE_PROXY, "<local>")
            log.info("Internet paused (per-user proxy blackhole)")
        elif not on and engaged:
            backup = self.config.pop("proxy_backup", None) or {}
            server = backup.get("server")
            if server == BLACKHOLE_PROXY:
                server = None
            enable = int(backup.get("enable") or 0) if server else 0
            self.platform.write_proxy(enable, server, backup.get("override") if server else None)
            self.save_config()
            log.info("Internet restored")

    def release_enforcement(self) -> None:
        """Undo everything that could leave the PC without internet (used on exit / when removed)."""
        try:
            self.set_proxy_blackhole(False)
        except Exception:  # noqa: BLE001
            log.exception("Could not release proxy")
        if self.hosts_enabled:
            try:
                self.hosts.remove()
            except OSError:
                pass

    def save_config(self) -> None:
        if not self.config_path:
            return
        try:
            self.config_path.write_text(json.dumps(self.config, indent=2), encoding="utf-8")
        except OSError:
            log.debug("could not save config")

    # -- VPN guard ---------------------------------------------------------------------- #
    def vpn_check_once(self) -> None:
        current = set(self.platform.list_vpn_adapters())
        for adapter in sorted(current - self.known_vpns):
            log.warning("VPN adapter detected: %s", adapter)
            try:
                self.client.report_vpn(adapter)
            except (HubUnreachable, AuthRejected):
                current.discard(adapter)  # report again next round
        self.known_vpns = current

    # -- screenshots -------------------------------------------------------------------- #
    def snapshot_due(self, now: float) -> bool:
        return self.snapshot_interval > 0 and now - self.last_snapshot >= self.snapshot_interval

    def snapshot_once(self, reason: str = "scheduled") -> bool:
        if self.state["locked"] or not self.connected:
            return False
        try:
            jpeg = self.platform.grab_screenshot_jpeg()
            self.client.upload_snapshot(jpeg)
        except (HubUnreachable, AuthRejected):
            return False
        except Exception:  # noqa: BLE001 - e.g. no desktop available
            log.exception("Screenshot failed (%s)", reason)
            return False
        self.last_snapshot = time.time()
        log.info("Screenshot sent (%s, %d KB)", reason, len(jpeg) // 1024)
        return True

    # -- loops ----------------------------------------------------------------------------- #
    def _loop(self, name: str, interval: float, fn: Callable[[], None]) -> None:
        failures = 0
        while not self.stop_event.is_set():
            try:
                fn()
                failures = 0
            except Exception:  # noqa: BLE001
                failures += 1
                log.exception("%s loop error", name)
            delay = interval if failures == 0 else min(60.0, interval * (2 ** min(failures, 4)))
            if not self.auth_ok:
                delay = max(delay, 30.0)
            self.stop_event.wait(delay)

    def _snapshot_tick(self) -> None:
        if self.snapshot_due(time.time()):
            self.snapshot_once("scheduled")

    def start_threads(self) -> List[threading.Thread]:
        specs = [
            ("heartbeat", HEARTBEAT_S, self.heartbeat_once),
            ("commands", COMMAND_POLL_S, self.poll_commands_once),
            ("enforce", ENFORCE_S, self.enforce_once),
            ("vpn", VPN_CHECK_S, self.vpn_check_once),
            ("snapshots", 5, self._snapshot_tick),
        ]
        threads = []
        for name, interval, fn in specs:
            thread = threading.Thread(target=self._loop, args=(name, interval, fn), name=f"himaya-{name}", daemon=True)
            thread.start()
            threads.append(thread)
        return threads

    def shutdown(self, reason: str = "stopped") -> None:
        if self.stop_event.is_set():
            return
        self.stop_event.set()
        self.release_enforcement()
        try:
            self.client.report_event("agent_stopped", {"reason": reason})
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def load_config(path: Optional[Path] = None) -> Dict[str, Any]:
    path = path or CONFIG_PATH
    config = json.loads(path.read_text(encoding="utf-8-sig"))  # utf-8-sig: PowerShell 5 writes a BOM
    missing = [key for key in ("hub_url", "device_id", "agent_key") if not config.get(key)]
    if missing:
        raise ValueError("agent_config.json is missing: " + ", ".join(missing))
    return config


def setup_logging(console: bool) -> None:
    root = logging.getLogger("himaya")
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        file_handler = logging.handlers.RotatingFileHandler(LOG_PATH, maxBytes=200_000, backupCount=2, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        pass
    if console and sys.stderr is not None:
        stream = logging.StreamHandler()
        stream.setFormatter(fmt)
        root.addHandler(stream)


def acquire_single_instance() -> bool:
    """One agent per user session (a named mutex on Windows)."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        handle = ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\HimayaAgentSingleton")
        already = ctypes.windll.kernel32.GetLastError() == 183  # ERROR_ALREADY_EXISTS
        acquire_single_instance.handle = handle  # type: ignore[attr-defined]  # keep it alive
        return not already
    except Exception:
        return True


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Himaya Windows agent")
    parser.add_argument("--console", action="store_true", help="also print log lines to the console")
    parser.add_argument("--once", action="store_true", help="contact the hub once, print the result and exit")
    parser.add_argument("--version", action="store_true")
    args = parser.parse_args(argv)
    if args.version:
        print(AGENT_VERSION)
        return 0

    setup_logging(args.console or args.once)
    platform = WindowsPlatform()
    try:
        config = load_config()
    except (OSError, ValueError) as exc:
        message = f"Himaya is not set up on this computer ({exc}). Run the installer from the Enroll page of your Himaya dashboard."
        log.error(message)
        if not args.once:
            platform.message_box("Himaya", message)
        print(message, file=sys.stderr)
        return 2

    urls = [config["hub_url"]] + list(config.get("candidate_urls") or [])
    client = HubClient(urls, config["device_id"], config["agent_key"])

    if args.once:
        core = AgentCore(config, client, platform, ui=None, config_path=CONFIG_PATH)
        core.heartbeat_once()
        print(json.dumps({"connected": core.connected, "hub": client.active, "state": core.state, "snapshot_interval_s": core.snapshot_interval}, indent=2))
        return 0 if core.connected else 1

    if not acquire_single_instance():
        log.info("Another Himaya agent is already running; exiting.")
        return 0

    core = AgentCore(config, client, platform, ui=None, config_path=CONFIG_PATH)
    tray = TrayUI(platform, core.status_text, core.extra_text)
    core.ui = tray
    atexit.register(lambda: core.shutdown("process exit"))

    def on_ready() -> None:
        core.notify("Himaya", "Himaya is active on this computer.")
        core.start_threads()

    try:
        tray.run_blocking(on_ready)
    except KeyboardInterrupt:
        pass
    finally:
        core.shutdown("tray closed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
