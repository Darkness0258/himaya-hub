"""Himaya Auto-Discovery & Network Enrollment Service.

- Discovers LAN IP and external Public IP
- Runs UDP beacon & discovery responder on port 5354 so real devices on Wi-Fi auto-pair
- Generates 6-digit Quick Pairing PINs and QR codes for zero-touch enrollment
"""
from __future__ import annotations
import json
import random
import socket
import threading
import time
from typing import Optional

DISCOVERY_PORT = 5354
_cached_lan_ip: Optional[str] = None
_active_pin: str = "842019"


_cached_public_ip: Optional[str] = None
_cached_public_ip_time: float = 0.0


def get_lan_ip() -> str:
    global _cached_lan_ip
    if _cached_lan_ip:
        return _cached_lan_ip
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            _cached_lan_ip = ip
            return ip
    except Exception:
        return "127.0.0.1"


def get_public_ip() -> str:
    global _cached_public_ip, _cached_public_ip_time
    now = time.time()
    if _cached_public_ip and (now - _cached_public_ip_time < 300):
        return _cached_public_ip
    try:
        import requests
        res = requests.get("https://api.ipify.org", timeout=2)
        if res.ok:
            _cached_public_ip = res.text.strip()
            _cached_public_ip_time = now
            return _cached_public_ip
    except Exception:
        pass
    if _cached_public_ip:
        return _cached_public_ip
    return get_lan_ip()


def get_enrollment_pin() -> str:
    global _active_pin
    return _active_pin


def regenerate_enrollment_pin() -> str:
    global _active_pin
    _active_pin = f"{random.randint(100000, 999999)}"
    return _active_pin


class DiscoveryServer:
    """UDP Auto-Discovery Responder for LAN agents."""

    def __init__(self, http_port: int = 8000):
        self.http_port = http_port
        self.running = False
        self.sock: Optional[socket.socket] = None
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            self.sock.bind(("", DISCOVERY_PORT))
            self.sock.settimeout(2.0)
            print(f"[Auto-Discovery] Listening for real device probes on UDP port {DISCOVERY_PORT}")

            lan_ip = get_lan_ip()
            hub_url = f"http://{lan_ip}:{self.http_port}"

            while self.running:
                try:
                    data, addr = self.sock.recvfrom(1024)
                    msg = data.decode("utf-8", errors="ignore").strip()

                    if "HIMAYA_DISCOVER" in msg:
                        # Real agent on Wi-Fi is asking for the Hub!
                        response_payload = {
                            "type": "himaya_hub_info",
                            "hub_url": hub_url,
                            "lan_ip": lan_ip,
                            "http_port": self.http_port,
                            "hub_name": "Himaya Safety Hub",
                            "pin": get_enrollment_pin()
                        }
                        reply_bytes = json.dumps(response_payload).encode("utf-8")
                        self.sock.sendto(reply_bytes, addr)
                        print(f"[Auto-Discovery] Auto-pairing response sent to {addr[0]}")
                except socket.timeout:
                    continue
                except Exception:
                    break
        except Exception as e:
            print(f"[Auto-Discovery] Notice: Could not bind discovery port {DISCOVERY_PORT}: {e}")
        finally:
            if self.sock:
                self.sock.close()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
