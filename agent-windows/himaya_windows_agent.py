#!/usr/bin/env python3
"""
Himaya Windows Agent — Background protection engine for family device safety.
Runs as a Python script via pythonw.exe (no console window).
"""

import asyncio
import json
import logging
import os
import platform
import sys
import time
import uuid
import winreg
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, List, Dict, Any

import requests

# Configure logging
LOG_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "HimayaAgent" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "agent.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("HimayaWindowsAgent")


@dataclass
class AgentConfig:
    hub_url: str
    candidate_urls: List[str]
    device_id: str
    device_name: str


@dataclass
class RuleSet:
    status: str = "active"
    enforcement: str = "strict"
    blocked_domains: List[str] = None
    allowed_domains: List[str] = None
    curfew_start: Optional[str] = None  # HH:MM
    curfew_end: Optional[str] = None

    def __post_init__(self):
        if self.blocked_domains is None:
            self.blocked_domains = []
        if self.allowed_domains is None:
            self.allowed_domains = []


class HubClient:
    """HTTP client for communicating with Himaya Hub."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.session = requests.Session()
        self.session.timeout = (5, 15)

    def _try_urls(self, path: str, method: str = "GET", **kwargs) -> Optional[requests.Response]:
        """Try all candidate URLs until one succeeds."""
        for base_url in self.config.candidate_urls:
            url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
            try:
                if method == "GET":
                    resp = self.session.get(url, **kwargs)
                elif method == "POST":
                    resp = self.session.post(url, **kwargs)
                else:
                    continue

                if resp.status_code < 500:
                    logger.debug(f"Request to {url} succeeded: {resp.status_code}")
                    return resp
            except Exception as e:
                logger.debug(f"Request to {url} failed: {e}")
        logger.warning(f"All candidate URLs failed for {path}")
        return None

    def check_health(self) -> bool:
        resp = self._try_urls("/health")
        return resp is not None and resp.status_code == 200

    def register_device(self) -> bool:
        payload = {
            "name": self.config.device_name,
            "platform": "windows",
            "device_id": self.config.device_id,
            "owner_type": "child"
        }
        resp = self._try_urls("/devices", method="POST", json=payload)
        return resp is not None and resp.status_code == 200

    def heartbeat(self, local_ip: str) -> bool:
        payload = {"ip": local_ip}
        path = f"/agents/{self.config.device_id}/heartbeat"
        resp = self._try_urls(path, method="POST", json=payload)
        return resp is not None and resp.status_code == 200

    def report_dns_block(self, host: str) -> bool:
        payload = {"host": host}
        path = f"/agents/{self.config.device_id}/dns-block"
        resp = self._try_urls(path, method="POST", json=payload)
        return resp is not None and resp.status_code == 200

    def report_vpn_attempt(self, interface: str) -> bool:
        payload = {"interface": interface}
        path = f"/agents/{self.config.device_id}/vpn-attempt"
        resp = self._try_urls(path, method="POST", json=payload)
        return resp is not None and resp.status_code == 200

    def get_commands(self) -> List[Dict[str, Any]]:
        path = f"/agents/{self.config.device_id}/commands"
        resp = self._try_urls(path, method="GET")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                return data.get("commands", [])
            except Exception:
                pass
        return []

    def policy_sync(self, rules: RuleSet) -> bool:
        payload = asdict(rules)
        path = f"/agents/{self.config.device_id}/policy-sync"
        resp = self._try_urls(path, method="POST", json=payload)
        return resp is not None and resp.status_code == 200

    def get_rules(self) -> Optional[RuleSet]:
        path = f"/rules/{self.config.device_id}"
        resp = self._try_urls(path, method="GET")
        if resp and resp.status_code == 200:
            try:
                data = resp.json()
                return RuleSet(**data)
            except Exception:
                pass
        return None


class DNSEngine:
    """DNS filtering engine using hosts file + Windows DNS cache."""

    def __init__(self, rules: RuleSet):
        self.rules = rules
        self.hosts_path = Path(r"C:\Windows\System32\drivers\etc\hosts")
        self.redirect_ip = "0.0.0.0"
        self._original_hosts: Optional[str] = None

    def apply(self) -> bool:
        """Apply DNS blocking by updating hosts file."""
        try:
            # Backup original if not already backed up
            if self._original_hosts is None:
                try:
                    self._original_hosts = self.hosts_path.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    self._original_hosts = ""

            # Read current
            current = self.hosts_path.read_text(encoding="utf-8", errors="ignore")

            # Build new hosts with blocklist
            block_marker = "# HIMAYA BLOCKLIST START"
            if block_marker in current:
                # Remove old blocklist section
                parts = current.split(block_marker)
                current = parts[0].rstrip() + "\n"

            # Build block entries
            lines = [block_marker]
            for domain in self.rules.blocked_domains:
                lines.append(f"{self.redirect_ip} {domain}")
                lines.append(f"{self.redirect_ip} www.{domain}")
            lines.append("# HIMAYA BLOCKLIST END")

            new_content = current + "\n" + "\n".join(lines) + "\n"
            self.hosts_path.write_text(new_content, encoding="utf-8")

            # Flush DNS cache
            self._flush_dns()
            logger.info(f"Applied DNS blocklist: {len(self.rules.blocked_domains)} domains")
            return True

        except PermissionError:
            logger.error("Permission denied writing hosts file. Run as Administrator.")
            return False
        except Exception as e:
            logger.error(f"Failed to apply DNS blocklist: {e}")
            return False

    def remove(self) -> bool:
        """Remove DNS blocking."""
        try:
            if self._original_hosts:
                self.hosts_path.write_text(self._original_hosts, encoding="utf-8")
            else:
                # Fallback: just remove our section
                current = self.hosts_path.read_text(encoding="utf-8", errors="ignore")
                if "# HIMAYA BLOCKLIST START" in current:
                    parts = current.split("# HIMAYA BLOCKLIST START")
                    before = parts[0]
                    if "# HIMAYA BLOCKLIST END" in parts[1]:
                        after = parts[1].split("# HIMAYA BLOCKLIST END", 1)[1]
                        self.hosts_path.write_text(before + after, encoding="utf-8")

            self._flush_dns()
            logger.info("Removed DNS blocklist")
            return True
        except Exception as e:
            logger.error(f"Failed to remove DNS blocklist: {e}")
            return False

    def _flush_dns(self) -> None:
        """Flush Windows DNS cache."""
        try:
            import subprocess
            subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=5)
        except Exception:
            pass

    def update_rules(self, rules: RuleSet) -> None:
        self.rules = rules
        if rules.status == "active" and rules.enforcement == "strict":
            self.apply()
        else:
            self.remove()


class VPNGuard:
    """Detects unauthorized VPN interfaces."""

    def __init__(self, client: HubClient):
        self.client = client

    def check(self) -> Optional[str]:
        """Check for active VPN interfaces. Returns interface name if found."""
        try:
            import subprocess
            # Get active network adapters
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object Name, InterfaceDescription"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                return None

            output = result.stdout.lower()
            vpn_keywords = ["vpn", "tunnel", "tap", "tun", "wireguard", "openvpn", "nordvpn",
                           "expressvpn", "protonvpn", "surfshark", "mullvad", "tailscale"]

            for keyword in vpn_keywords:
                if keyword in output:
                    # Try to get the actual interface name
                    lines = output.splitlines()
                    for line in lines:
                        if keyword in line.lower():
                            parts = line.split()
                            if parts:
                                return parts[0]
        except Exception as e:
            logger.debug(f"VPN guard check error: {e}")
        return None


class CurfewManager:
    """Manages internet access based on curfew schedule."""

    def __init__(self, rules: RuleSet, dns_engine: DNSEngine):
        self.rules = rules
        self.dns = dns_engine
        self._curfew_active = False

    def check(self) -> bool:
        """Check if curfew is active. Returns True if access should be blocked."""
        if not self.rules.curfew_start or not self.rules.curfew_end:
            self._curfew_active = False
            return False

        now = time.strftime("%H:%M")
        start = self.rules.curfew_start
        end = self.rules.curfew_end

        # Handle overnight curfew (e.g., 22:00 - 07:00)
        if start > end:
            is_curfew = now >= start or now <= end
        else:
            is_curfew = start <= now <= end

        if is_curfew != self._curfew_active:
            self._curfew_active = is_curfew
            if is_curfew:
                logger.info("Curfew started - blocking internet")
                # Temporarily block all internet by applying strict blocklist
                self.dns.apply()
            else:
                logger.info("Curfew ended - restoring internet")
                self.dns.apply()

        return is_curfew


class WindowsAgent:
    """Main Windows agent orchestrator."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.client = HubClient(config)
        self.rules = RuleSet()
        self.dns = DNSEngine(self.rules)
        self.vpn_guard = VPNGuard(self.client)
        self.curfew = CurfewManager(self.rules, self.dns)

        self.running = True
        self.heartbeat_interval = 20  # seconds
        self.vpn_check_interval = 10  # seconds
        self.policy_sync_interval = 60  # seconds
        self.command_poll_interval = 5  # seconds

    def get_local_ip(self) -> str:
        """Get local IP address."""
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    async def heartbeat_loop(self):
        while self.running:
            try:
                ip = self.get_local_ip()
                if self.client.heartbeat(ip):
                    logger.debug(f"Heartbeat sent from {ip}")
                else:
                    logger.warning("Heartbeat failed")
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")
            await asyncio.sleep(self.heartbeat_interval)

    async def vpn_guard_loop(self):
        while self.running:
            try:
                vpn_iface = self.vpn_guard.check()
                if vpn_iface:
                    logger.warning(f"Unauthorized VPN detected: {vpn_iface}")
                    self.client.report_vpn_attempt(vpn_iface)
            except Exception as e:
                logger.error(f"VPN guard error: {e}")
            await asyncio.sleep(self.vpn_check_interval)

    async def policy_sync_loop(self):
        while self.running:
            try:
                rules = self.client.get_rules()
                if rules:
                    self.rules = rules
                    self.dns.update_rules(rules)
                    self.curfew.rules = rules
                    self.client.policy_sync(rules)
                    logger.debug("Policy synced")
            except Exception as e:
                logger.error(f"Policy sync error: {e}")
            await asyncio.sleep(self.policy_sync_interval)

    async def command_loop(self):
        while self.running:
            try:
                commands = self.client.get_commands()
                for cmd in commands:
                    await self.execute_command(cmd)
            except Exception as e:
                logger.error(f"Command loop error: {e}")
            await asyncio.sleep(self.command_poll_interval)

    async def execute_command(self, cmd: Dict[str, Any]):
        action = cmd.get("action")
        payload = cmd.get("payload", {})
        logger.info(f"Executing remote action: {action}")

        if action == "lock":
            await self.lock_screen()
        elif action == "unlock":
            await self.unlock_screen()
        elif action == "wipe":
            await self.wipe_device()
        elif action in ("pause", "block_internet"):
            self.rules.status = "paused"
            self.dns.apply()
        elif action in ("unpause", "unblock_internet"):
            self.rules.status = "active"
            self.dns.apply()
        elif action == "push_notification":
            message = payload.get("message", "Message from parent")
            self.show_notification(message)
        elif action == "force_close_app":
            app_name = payload.get("app")
            if app_name:
                self.force_close_app(app_name)

    async def lock_screen(self):
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            logger.info("Screen locked via LockWorkStation")
        except Exception as e:
            logger.error(f"Lock screen failed: {e}")

    async def unlock_screen(self):
        # Cannot programmatically unlock - requires user interaction
        logger.info("Unlock requested - user must enter credentials")
        self.show_notification("Screen unlock requested. Enter your credentials.")

    async def wipe_device(self):
        logger.warning("WIPE COMMAND RECEIVED - This would trigger device reset")
        # In real implementation: use MDM/WMI to trigger reset
        # For safety, we only log and notify
        self.show_notification("⚠️ Remote wipe command received. Contact administrator.")

    def show_notification(self, message: str):
        try:
            import win10toast
            toaster = win10toast.ToastNotifier()
            toaster.show_toast("Himaya Agent", message, duration=10)
        except ImportError:
            logger.info(f"Notification: {message}")

    def force_close_app(self, app_name: str):
        try:
            import subprocess
            subprocess.run(["taskkill", "/f", "/im", app_name], capture_output=True, timeout=5)
            logger.info(f"Force closed app: {app_name}")
        except Exception as e:
            logger.error(f"Force close failed for {app_name}: {e}")

    async def run(self):
        logger.info("=" * 50)
        logger.info(f"Himaya Windows Agent starting")
        logger.info(f"Device: {self.config.device_name} ({self.config.device_id})")
        logger.info(f"Hub: {self.config.hub_url}")
        logger.info("=" * 50)

        # Initial registration
        if not self.client.check_health():
            logger.error("Hub health check failed - waiting for hub...")
            while not self.client.check_health() and self.running:
                await asyncio.sleep(5)

        self.client.register_device()

        # Initial policy fetch
        rules = self.client.get_rules()
        if rules:
            self.rules = rules
            self.dns.update_rules(rules)
            self.curfew.rules = rules

        # Start all loops concurrently
        await asyncio.gather(
            self.heartbeat_loop(),
            self.vpn_guard_loop(),
            self.policy_sync_loop(),
            self.command_loop(),
        )

    def stop(self):
        self.running = False
        logger.info("Agent stopping...")


def load_config() -> AgentConfig:
    """Load configuration from agent_config.json."""
    config_path = Path(os.environ.get("LOCALAPPDATA", "")) / "HimayaAgent" / "agent_config.json"
    if config_path.exists():
        with open(config_path, "r") as f:
            data = json.load(f)
        return AgentConfig(**data)

    # Fallback for direct execution
    computer = platform.node()
    user = os.environ.get("USERNAME", "user")
    device_id = f"win-{uuid.uuid4().hex[:8]}"
    return AgentConfig(
        hub_url="http://127.0.0.1:8000",
        candidate_urls=["http://127.0.0.1:8000"],
        device_id=device_id,
        device_name=f"{computer} ({user})"
    )


def ensure_admin() -> bool:
    """Check if running with Administrator privileges."""
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


async def main():
    config = load_config()
    logger.info(f"Loaded config: {config.device_id} -> {config.hub_url}")

    if not ensure_admin():
        logger.warning("Not running as Administrator. DNS filtering will be limited.")

    agent = WindowsAgent(config)

    try:
        await agent.run()
    except KeyboardInterrupt:
        logger.info("Interrupted")
    finally:
        agent.stop()


if __name__ == "__main__":
    asyncio.run(main())