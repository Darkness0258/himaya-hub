"""Himaya Built-in DNS Sinkhole & Filtering Proxy Server.

Listens for UDP DNS queries from network clients (Android VPN / Windows Agent / Local Router).
- Matches domains against blocklists and parental rules
- Sinkholes blocked domains to 0.0.0.0
- Logs blocks directly to Himaya Hub database and emits live security alerts
- Forwards clean queries to upstream secure resolver (Quad9 / Cloudflare Family)
"""
from __future__ import annotations
import socket
import struct
import threading
import time
from typing import Callable, Optional, Set

DEFAULT_UPSTREAM_DNS = ("1.1.1.3", 53)  # Cloudflare Family (malware + adult content blocking)

POPULAR_BLOCKLIST: Set[str] = {
    "tiktok.com",
    "ads.tiktok.com",
    "byteoversea.com",
    "pornhub.com",
    "xvideos.com",
    "xnxx.com",
    "gambling.com",
    "bet365.com",
    "roblox.com",
    "kick.com",
    "discord.gg",
    "omegle.com"
}


def parse_dns_name(data: bytes, offset: int = 12) -> tuple[str, int]:
    """Parse standard DNS QNAME label format."""
    labels = []
    curr = offset
    while curr < len(data):
        length = data[curr]
        if length == 0:
            curr += 1
            break
        curr += 1
        labels.append(data[curr:curr + length].decode("utf-8", errors="ignore"))
        curr += length
    return ".".join(labels).lower(), curr


def build_sinkhole_response(query_data: bytes, domain: str) -> bytes:
    """Construct a DNS A-record response pointing to 0.0.0.0 (Sinkhole)."""
    tx_id = query_data[:2]
    flags = b"\x81\x80"  # Standard query response, No error
    qdcount = query_data[4:6]
    ancount = b"\x00\x01"  # 1 Answer
    nscount = b"\x00\x00"
    arcount = b"\x00\x00"

    # Find end of question section
    _, qend = parse_dns_name(query_data, 12)
    qsection = query_data[12:qend + 4]  # includes QTYPE and QCLASS

    # Answer: Name pointer to question (0xC00C), Type A (1), Class IN (1), TTL 60, Length 4, IP 0.0.0.0
    answer = b"\xc0\x0c" + b"\x00\x01\x00\x01" + struct.pack(">I", 60) + b"\x00\x04" + b"\x00\x00\x00\x00"

    return tx_id + flags + qdcount + ancount + nscount + arcount + qsection + answer


class DnsFilterServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 5353, on_block_callback: Optional[Callable[[str, str], None]] = None):
        self.host = host
        self.port = port
        self.on_block_callback = on_block_callback
        self.running = False
        self.sock: Optional[socket.socket] = None
        self.thread: Optional[threading.Thread] = None
        self.custom_blocked: Set[str] = set(POPULAR_BLOCKLIST)

    def is_blocked(self, domain: str) -> bool:
        if domain in self.custom_blocked:
            return True
        for b in self.custom_blocked:
            if domain.endswith("." + b):
                return True
        return False

    def handle_request(self, data: bytes, client_addr: tuple[str, int]) -> None:
        try:
            if len(data) < 12:
                return
            domain, _ = parse_dns_name(data, 12)

            client_ip = client_addr[0]

            if self.is_blocked(domain):
                # Sinkhole
                resp = build_sinkhole_response(data, domain)
                if self.sock:
                    self.sock.sendto(resp, client_addr)
                if self.on_block_callback:
                    self.on_block_callback(client_ip, domain)
            else:
                # Forward to upstream secure DNS
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream_sock:
                    upstream_sock.settimeout(2.0)
                    upstream_sock.sendto(data, DEFAULT_UPSTREAM_DNS)
                    upstream_resp, _ = upstream_sock.recvfrom(4096)
                    if self.sock:
                        self.sock.sendto(upstream_resp, client_addr)
        except Exception:
            pass

    def run(self) -> None:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            except Exception:
                pass
            self.sock.bind((self.host, self.port))
            self.sock.settimeout(1.0)
            self.running = True

            while self.running:
                try:
                    data, addr = self.sock.recvfrom(4096)
                    threading.Thread(target=self.handle_request, args=(data, addr), daemon=True).start()
                except socket.timeout:
                    continue
                except Exception:
                    break
        except Exception as e:
            print(f"[DNS Engine] Notice: Could not bind DNS on {self.host}:{self.port} ({e})")
        finally:
            if self.sock:
                self.sock.close()

    def start(self) -> None:
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)
