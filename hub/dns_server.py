"""Himaya DNS filtering resolver (UDP).

Devices that use the hub as their DNS server get:

* blocked domains answered with ``0.0.0.0`` (A) / ``::`` (AAAA), or an empty
  NOERROR answer for other record types, so clients move on immediately;
* the parent's per-device rules applied (categories, custom domains, exceptions,
  bedtime window and "pause internet"), via :class:`filtering.FilterEngine`;
* everything else forwarded to a family-safe upstream (Cloudflare 1.1.1.3 by
  default) with a proper SERVFAIL when the upstream is unreachable.

Differences from the first version
----------------------------------
* The sinkhole used to answer **every** query type with an A record. AAAA and
  HTTPS lookups (which browsers send constantly) got a malformed answer.
* The block list was a fixed set that ignored the parent's rules entirely.
* The server was an open resolver for anyone who could reach the port. Clients
  outside private/loopback/CGNAT ranges are now ignored unless explicitly allowed.
* A failed upstream lookup left the client hanging until its own timeout.
"""
from __future__ import annotations

import concurrent.futures
import logging
import socket
import struct
import threading
from typing import Callable, Dict, Optional, Tuple

import security
from filtering import Decision

log = logging.getLogger("himaya.dns")

QTYPE_A = 1
QTYPE_AAAA = 28


def parse_question(data: bytes) -> Optional[Tuple[str, int, int, int]]:
    """Parse the first question of a DNS query.

    Returns ``(qname, qtype, qclass, end_offset)`` or ``None`` if the packet is
    malformed. Compression pointers are rejected: they are not valid inside the
    question of a normal query and are a classic source of parser bugs.
    """
    if len(data) < 17:  # 12 header + root label + 4 type/class
        return None
    if int.from_bytes(data[4:6], "big") < 1:
        return None
    labels = []
    pos = 12
    total = 0
    while True:
        if pos >= len(data):
            return None
        length = data[pos]
        pos += 1
        if length == 0:
            break
        if length & 0xC0 or length > 63:
            return None
        if pos + length > len(data):
            return None
        labels.append(data[pos:pos + length].decode("latin-1"))
        pos += length
        total += length + 1
        if total > 253:
            return None
    if pos + 4 > len(data):
        return None
    qtype, qclass = struct.unpack(">HH", data[pos:pos + 4])
    return ".".join(labels).lower(), qtype, qclass, pos + 4


def build_blocked_response(query: bytes, qtype: int, ttl: int = 60) -> bytes:
    """Sinkhole answer matching the question's record type."""
    parsed = parse_question(query)
    if parsed is None:
        return b""
    qend = parsed[3]
    question = query[12:qend]
    recursion_desired = query[2] & 0x01
    flags = 0x8000 | (recursion_desired << 8) | 0x0080  # QR, RD echoed, RA, RCODE=0
    if qtype == QTYPE_A:
        answer = b"\xc0\x0c" + struct.pack(">HHIH", QTYPE_A, 1, ttl, 4) + b"\x00" * 4
        ancount = 1
    elif qtype == QTYPE_AAAA:
        answer = b"\xc0\x0c" + struct.pack(">HHIH", QTYPE_AAAA, 1, ttl, 16) + b"\x00" * 16
        ancount = 1
    else:
        answer, ancount = b"", 0
    header = query[:2] + struct.pack(">HHHHH", flags, 1, ancount, 0, 0)
    return header + question + answer


def build_servfail(query: bytes) -> bytes:
    parsed = parse_question(query)
    if parsed is None:
        return b""
    question = query[12:parsed[3]]
    recursion_desired = query[2] & 0x01
    flags = 0x8000 | (recursion_desired << 8) | 0x0080 | 0x0002  # RCODE=2 SERVFAIL
    return query[:2] + struct.pack(">HHHHH", flags, 1, 0, 0, 0) + question


class DnsFilterServer:
    def __init__(
        self,
        decide: Callable[[str, str], Decision],
        host: str = "0.0.0.0",
        port: int = 5300,
        upstream: Tuple[str, int] = ("1.1.1.3", 53),
        on_block: Optional[Callable[[str, str, Decision], None]] = None,
        allow_public_clients: bool = False,
        upstream_timeout: float = 2.0,
        workers: int = 16,
    ):
        self.decide = decide
        self.host = host
        self.port = port
        self.upstream = upstream
        self.on_block = on_block
        self.allow_public_clients = allow_public_clients
        self.upstream_timeout = upstream_timeout
        self.workers = workers
        self.running = False
        self.error: Optional[str] = None
        self.sock: Optional[socket.socket] = None
        self.thread: Optional[threading.Thread] = None
        self._pool: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._ready = threading.Event()
        self._stats_lock = threading.Lock()
        self.stats: Dict[str, int] = {"queries": 0, "blocked": 0, "upstream_errors": 0, "dropped": 0}

    # -- request handling --------------------------------------------------- #
    def _bump(self, key: str) -> None:
        with self._stats_lock:
            self.stats[key] += 1

    def _send(self, payload: bytes, addr) -> None:
        if payload and self.sock:
            try:
                self.sock.sendto(payload, addr)
            except OSError:
                pass

    def _forward(self, data: bytes) -> Optional[bytes]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as upstream:
                upstream.settimeout(self.upstream_timeout)
                upstream.sendto(data, self.upstream)
                while True:
                    response, source = upstream.recvfrom(4096)
                    # Ignore anything that isn't the answer to *our* query from the upstream.
                    if source[0] == self.upstream[0] and response[:2] == data[:2]:
                        return response
        except (socket.timeout, OSError):
            return None

    def handle_request(self, data: bytes, addr) -> None:
        try:
            client_ip = addr[0]
            if not self.allow_public_clients and not security.is_lan_client(client_ip):
                self._bump("dropped")
                return
            if len(data) < 12 or data[2] & 0x80:  # too short, or a *response* (never answer those)
                return
            parsed = parse_question(data)
            if parsed is None:
                return
            qname, qtype, _qclass, _end = parsed
            self._bump("queries")
            decision = self.decide(client_ip, qname)
            if decision.blocked:
                self._bump("blocked")
                self._send(build_blocked_response(data, qtype), addr)
                if self.on_block:
                    try:
                        self.on_block(client_ip, qname, decision)
                    except Exception:  # never let telemetry break resolution
                        log.exception("DNS block callback failed")
                return
            response = self._forward(data)
            if response is None:
                self._bump("upstream_errors")
                response = build_servfail(data)
            self._send(response, addr)
        except Exception:
            log.debug("DNS request handling error", exc_info=True)

    # -- lifecycle ---------------------------------------------------------- #
    def run(self) -> None:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.bind((self.host, self.port))
            self.port = self.sock.getsockname()[1]
            self.sock.settimeout(1.0)
            self.running = True
            self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="dns")
        except OSError as exc:
            self.error = str(exc)
            log.warning("DNS filter could not bind %s:%s (%s). Website filtering via hub DNS is disabled.", self.host, self.port, exc)
            self._ready.set()
            if self.sock:
                self.sock.close()
            return
        self._ready.set()
        log.info("DNS filter listening on UDP %s:%s (upstream %s:%s)", self.host, self.port, *self.upstream)
        try:
            while self.running:
                try:
                    data, addr = self.sock.recvfrom(4096)
                except socket.timeout:
                    continue
                except ConnectionResetError:  # Windows reports ICMP port-unreachable this way
                    continue
                except OSError:
                    break
                if self._pool and self.running:
                    self._pool.submit(self.handle_request, data, addr)
        finally:
            self.running = False
            if self._pool:
                self._pool.shutdown(wait=False)
            try:
                self.sock.close()
            except OSError:
                pass

    def start(self, wait: float = 1.5) -> bool:
        self.thread = threading.Thread(target=self.run, name="himaya-dns", daemon=True)
        self.thread.start()
        self._ready.wait(wait)
        return self.running

    def stop(self) -> None:
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)

    def status(self) -> Dict[str, object]:
        with self._stats_lock:
            stats = dict(self.stats)
        return {"running": self.running, "port": self.port, "upstream": f"{self.upstream[0]}:{self.upstream[1]}", "error": self.error, **stats}
