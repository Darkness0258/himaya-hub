"""Hub discovery: lets agents on the same Wi-Fi find the hub's address.

Security note
-------------
The first version of this beacon **replied with the pairing PIN** to anyone who
sent a UDP probe, which made the PIN worthless. Discovery now only reveals the
hub's *address*; authorisation still requires the PIN typed by a person.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import urllib.request
from typing import Optional

import config
import security

log = logging.getLogger("himaya.discovery")

_lan_cache = {"ip": None, "at": 0.0}
_public_cache = {"ip": None, "at": 0.0}


def get_lan_ip() -> str:
    """The hub machine's LAN address (cached for a minute).

    Inside Docker this is the container's bridge IP. Set ``HIMAYA_LAN_IP`` to the
    host's real LAN address in that case.
    """
    override = os.environ.get("HIMAYA_LAN_IP", "").strip()
    if override:
        return override
    now = time.time()
    if _lan_cache["ip"] and now - _lan_cache["at"] < 60:
        return _lan_cache["ip"]
    ip = "127.0.0.1"
    try:
        # UDP "connect" sends no packets; it only asks the OS which interface it would use.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
    except OSError:
        pass
    _lan_cache.update(ip=ip, at=now)
    return ip


def get_public_ip(timeout: float = 2.0) -> Optional[str]:
    """Public IP via a third-party service. Off by default (``HIMAYA_LOOKUP_PUBLIC_IP``)."""
    now = time.time()
    if _public_cache["ip"] and now - _public_cache["at"] < 600:
        return _public_cache["ip"]
    try:
        with urllib.request.urlopen("https://api.ipify.org", timeout=timeout) as response:  # noqa: S310 - fixed https URL
            ip = response.read().decode("ascii", "ignore").strip()
        if ip:
            _public_cache.update(ip=ip, at=now)
            return ip
    except (OSError, ValueError):
        pass
    return _public_cache["ip"]


class DiscoveryServer:
    """Answers ``HIMAYA_DISCOVER`` UDP probes from LAN clients."""

    def __init__(self, http_port: int, port: int = 5354, dns_port: Optional[int] = None):
        self.http_port = http_port
        self.port = port
        self.dns_port = dns_port
        self.running = False
        self.error: Optional[str] = None
        self.sock: Optional[socket.socket] = None
        self.thread: Optional[threading.Thread] = None
        self._ready = threading.Event()

    def reply_payload(self) -> bytes:
        lan_ip = get_lan_ip()
        return json.dumps(
            {
                "type": "himaya_hub_info",
                "hub_url": f"http://{lan_ip}:{self.http_port}",
                "lan_ip": lan_ip,
                "http_port": self.http_port,
                "dns_port": self.dns_port,
                "hub_name": "Himaya Safety Hub",
                "version": config.VERSION,
            }
        ).encode("utf-8")

    def _run(self) -> None:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind(("", self.port))
            self.sock.settimeout(1.0)
            self.running = True
        except OSError as exc:
            self.error = str(exc)
            log.warning("Discovery beacon could not bind UDP %s (%s). Agents will need the hub URL typed in.", self.port, exc)
            self._ready.set()
            return
        self._ready.set()
        log.info("Discovery beacon listening on UDP %s", self.port)
        try:
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                except socket.timeout:
                    continue
                except ConnectionResetError:  # Windows: ICMP unreachable after a previous reply
                    continue
                except OSError:
                    break
                if b"HIMAYA_DISCOVER" in data and security.is_lan_client(addr[0]):
                    try:
                        self.sock.sendto(self.reply_payload(), addr)
                    except OSError:
                        pass
        finally:
            self.running = False
            try:
                self.sock.close()
            except OSError:
                pass

    def start(self, wait: float = 1.5) -> bool:
        self.thread = threading.Thread(target=self._run, name="himaya-discovery", daemon=True)
        self.thread.start()
        self._ready.wait(wait)
        return self.running

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
