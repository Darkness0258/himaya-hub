"""Unit tests: filtering policy, DNS packets + live server, security primitives, installer templates."""
from __future__ import annotations

import socket
import struct
import threading
import time
from datetime import datetime

import pytest

import filtering
import security
import templates
from dns_server import DnsFilterServer, build_blocked_response, build_servfail, parse_question

dns = pytest.importorskip("dns.message", reason="dnspython is only needed to verify DNS packets")
import dns.rdatatype  # noqa: E402


def make_query(name: str, qtype: str = "A", txid: int = 0x1234) -> bytes:
    message = dns.message.make_query(name, qtype)
    message.id = txid
    return message.to_wire()


# --------------------------------------------------------------------------- #
# Filtering policy
# --------------------------------------------------------------------------- #
class TestDomainHelpers:
    @pytest.mark.parametrize("raw,expected", [
        ("TikTok.com", "tiktok.com"), ("https://www.Kick.com/path?q=1", "kick.com"), ("*.example.org", "example.org"),
        ("user:pw@host.example.com:8080/x", "host.example.com"), ("example.com.", "example.com"),
        ("not a domain", ""), ("", ""), ("localhost", ""), ("-bad-.com", ""), ("a..b.com", ""),
    ])
    def test_normalize(self, raw, expected):
        assert filtering.normalize_domain(raw) == expected

    def test_suffix_matching_does_not_overmatch(self):
        blocked = {"tiktok.com"}
        assert filtering.domain_matches("tiktok.com", blocked)
        assert filtering.domain_matches("v16m.tiktok.com", blocked)
        assert not filtering.domain_matches("nottiktok.com", blocked)
        assert not filtering.domain_matches("tiktok.com.evil.org", blocked)
        assert not filtering.domain_matches("com", {"com"})            # never match a bare TLD

    def test_blocklist_file_formats(self):
        text = "# comment\n0.0.0.0 ads.example.com\n127.0.0.1 localhost\n||tracker.net^\nplain.org  # inline\n! adblock comment\n"
        assert filtering.parse_blocklist_text(text) == {"ads.example.com", "tracker.net", "plain.org"}

    @pytest.mark.parametrize("now,start,end,expected", [
        (22 * 60, "21:00", "07:00", True), (3 * 60, "21:00", "07:00", True), (12 * 60, "21:00", "07:00", False),
        (7 * 60, "21:00", "07:00", False), (21 * 60, "21:00", "07:00", True),      # start inclusive, end exclusive
        (13 * 60, "12:00", "14:00", True), (15 * 60, "12:00", "14:00", False),
        (5, "09:00", "09:00", False), (5, "bad", "07:00", False),
    ])
    def test_bedtime_windows_including_overnight(self, now, start, end, expected):
        assert filtering.in_window(now, start, end) is expected


class TestFilterEngine:
    def engine(self, **kwargs):
        engine = filtering.FilterEngine(**kwargs)
        devices = [
            {"device_id": "kid-pc", "ip": "192.168.1.20", "paused": False},
            {"device_id": "kid-tab", "ip": "192.168.1.21", "paused": True},
            {"device_id": "dad-pc", "ip": "192.168.1.22", "paused": False},
        ]
        rules = {
            "kid-pc": {"blocked_categories": ["social"], "blocked_domains": ["example.org"], "allowed_domains": ["discord.com"],
                       "bedtime_enabled": True, "bedtime_start": "21:00", "bedtime_end": "07:00"},
            "kid-tab": {"blocked_categories": [], "blocked_domains": []},
            "dad-pc": {"blocked_categories": [], "blocked_domains": []},
        }
        engine.refresh(devices, rules)
        return engine

    def at(self, hour, minute=0):
        return datetime(2026, 10, 14, hour, minute)

    def test_category_custom_and_allow_override(self):
        e = self.engine()
        noon = self.at(12)
        assert e.decide("192.168.1.20", "www.tiktok.com", noon).reason == "category:social"
        assert e.decide("192.168.1.20", "sub.example.org", noon).reason == "custom"
        assert not e.decide("192.168.1.20", "discord.com", noon).blocked              # explicit exception wins over the category
        assert not e.decide("192.168.1.20", "wikipedia.org", noon).blocked

    def test_bedtime_blocks_everything(self):
        e = self.engine()
        assert e.decide("192.168.1.20", "wikipedia.org", self.at(22)).reason == "bedtime"
        assert not e.decide("192.168.1.20", "wikipedia.org", self.at(8)).blocked

    def test_paused_device_blocks_everything_but_the_hub(self):
        e = self.engine(always_allow=["hub.example.com"])
        assert e.decide("192.168.1.21", "wikipedia.org", self.at(12)).reason == "paused"
        assert not e.decide("192.168.1.21", "hub.example.com", self.at(12)).blocked   # keep the agent able to unpause

    def test_per_device_isolation_and_unknown_clients(self):
        e = self.engine()
        assert not e.decide("192.168.1.22", "tiktok.com", self.at(12)).blocked        # dad's PC has no blocks
        assert e.decide("192.168.1.99", "pornhub.com", self.at(12)).blocked           # unknown client gets the safe default
        unknown = e.decide("192.168.1.99", "pornhub.com", self.at(12))
        assert unknown.device_id is None                                              # not attributed to some random device

    def test_custom_blocklist_files_extend_categories(self, tmp_path):
        (tmp_path / "social.txt").write_text("0.0.0.0 newsocial.example\n")
        (tmp_path / "Bad Name!.txt").write_text("ignored.example\n")
        e = filtering.FilterEngine(blocklist_dir=tmp_path)
        assert "newsocial.example" in e.categories["social"] and "tiktok.com" in e.categories["social"]
        assert all(" " not in name for name in e.categories)

    def test_effective_blocklist_for_agents(self):
        e = self.engine()
        domains = e.effective_blocked_domains({"blocked_categories": ["social"], "blocked_domains": ["x.test"], "allowed_domains": ["discord.com"]})
        assert "tiktok.com" in domains and "x.test" in domains and "discord.com" not in domains

    def test_timezone_is_applied(self):
        e = filtering.FilterEngine(timezone="Asia/Karachi")
        assert e.now().utcoffset().total_seconds() == 5 * 3600


# --------------------------------------------------------------------------- #
# DNS packets
# --------------------------------------------------------------------------- #
class TestDnsPackets:
    def test_parse_question(self):
        assert parse_question(make_query("Www.TikTok.com", "AAAA"))[:3] == ("www.tiktok.com", 28, 1)

    @pytest.mark.parametrize("garbage", [b"", b"\x00" * 5, b"\x12\x34" + b"\x01\x00\x00\x01" + b"\x00" * 6 + b"\xc0\x0c\x00\x01\x00\x01", b"\x00" * 12 + b"\x3fabc"])
    def test_malformed_packets_return_none(self, garbage):
        assert parse_question(garbage) is None

    def test_a_query_gets_0000(self):
        response = dns.message.from_wire(build_blocked_response(make_query("tiktok.com", "A"), 1))
        assert response.id == 0x1234 and response.rcode() == 0
        assert [r.address for rr in response.answer for r in rr] == ["0.0.0.0"]

    def test_aaaa_query_gets_colon_colon_not_an_a_record(self):
        """Regression: the old sinkhole answered AAAA/HTTPS with an A record."""
        response = dns.message.from_wire(build_blocked_response(make_query("tiktok.com", "AAAA"), 28))
        assert [r.address for rr in response.answer for r in rr] == ["::"]
        assert all(rr.rdtype == dns.rdatatype.AAAA for rr in response.answer)

    def test_other_types_get_empty_noerror(self):
        response = dns.message.from_wire(build_blocked_response(make_query("tiktok.com", "HTTPS"), 65))
        assert response.rcode() == 0 and response.answer == []

    def test_servfail_packet(self):
        assert dns.message.from_wire(build_servfail(make_query("x.com"))).rcode() == 2


# --------------------------------------------------------------------------- #
# Live UDP server (with a fake upstream)
# --------------------------------------------------------------------------- #
class FakeUpstream(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.settimeout(0.5)
        self.port = self.sock.getsockname()[1]
        self.running = True
        self.seen = []

    def run(self):
        while self.running:
            try:
                data, addr = self.sock.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                break
            self.seen.append(parse_question(data)[0])
            reply = dns.message.make_response(dns.message.from_wire(data))
            reply.answer.append(dns.rrset.from_text(self.seen[-1] + ".", 30, "IN", "A", "93.184.216.34"))
            self.sock.sendto(reply.to_wire(), addr)

    def stop(self):
        self.running = False
        self.sock.close()


def ask(port: int, name: str, qtype: str = "A", timeout: float = 3.0):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
        client.settimeout(timeout)
        client.sendto(make_query(name, qtype), ("127.0.0.1", port))
        return dns.message.from_wire(client.recvfrom(4096)[0])


@pytest.fixture()
def live_dns():
    upstream = FakeUpstream()
    upstream.start()
    engine = filtering.FilterEngine()
    engine.refresh([{"device_id": "kid", "ip": "127.0.0.1", "paused": False}], {"kid": {"blocked_categories": ["social"], "blocked_domains": []}})
    blocked_log = []
    server = DnsFilterServer(engine.decide, host="127.0.0.1", port=0, upstream=("127.0.0.1", upstream.port),
                             on_block=lambda ip, domain, decision: blocked_log.append((ip, domain, decision.reason)), upstream_timeout=0.4)
    assert server.start()
    yield server, upstream, blocked_log, engine
    server.stop()
    upstream.stop()


class TestLiveDnsServer:
    def test_blocks_and_forwards(self, live_dns):
        server, upstream, blocked_log, _ = live_dns
        blocked = ask(server.port, "www.tiktok.com")
        assert [r.address for rr in blocked.answer for r in rr] == ["0.0.0.0"]
        allowed = ask(server.port, "wikipedia.org")
        assert [r.address for rr in allowed.answer for r in rr] == ["93.184.216.34"]
        assert upstream.seen == ["wikipedia.org"]                          # blocked names never reach the upstream
        assert blocked_log == [("127.0.0.1", "www.tiktok.com", "category:social")]
        assert server.status()["blocked"] == 1

    def test_blocked_aaaa_is_a_valid_aaaa(self, live_dns):
        server, *_ = live_dns
        assert [r.address for rr in ask(server.port, "tiktok.com", "AAAA").answer for r in rr] == ["::"]

    def test_policy_changes_apply_immediately(self, live_dns):
        server, _, _, engine = live_dns
        engine.refresh([{"device_id": "kid", "ip": "127.0.0.1", "paused": True}], {"kid": {"blocked_categories": []}})
        assert [r.address for rr in ask(server.port, "wikipedia.org").answer for r in rr] == ["0.0.0.0"]   # paused -> everything blocked

    def test_servfail_instead_of_hanging_when_upstream_is_down(self, live_dns):
        server, upstream, *_ = live_dns
        upstream.stop()
        started = time.time()
        response = ask(server.port, "wikipedia.org")
        assert response.rcode() == 2 and time.time() - started < 2.5

    def test_public_clients_are_ignored(self, live_dns):
        """Not an open resolver: only LAN / loopback / CGNAT sources are served."""
        server, *_ = live_dns
        sent = []
        server._send = lambda payload, addr: sent.append(addr)             # type: ignore[assignment]
        server.handle_request(make_query("wikipedia.org"), ("8.8.8.8", 5353))
        assert sent == [] and server.status()["dropped"] == 1
        server.handle_request(make_query("tiktok.com"), ("100.64.1.2", 5353))   # CGNAT / Tailscale is allowed
        assert sent == [("100.64.1.2", 5353)]

    def test_responses_are_never_answered(self, live_dns):
        server, *_ = live_dns
        sent = []
        server._send = lambda payload, addr: sent.append(addr)             # type: ignore[assignment]
        reply = dns.message.make_response(dns.message.from_wire(make_query("tiktok.com")))
        server.handle_request(reply.to_wire(), ("127.0.0.1", 1))
        assert sent == []                                                  # prevents reflection loops

    def test_garbage_does_not_crash_the_server(self, live_dns):
        server, *_ = live_dns
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            for junk in (b"", b"\xff" * 50, b"\x00" * 12):
                client.sendto(junk, ("127.0.0.1", server.port))
        assert [r.address for rr in ask(server.port, "tiktok.com").answer for r in rr] == ["0.0.0.0"]

    def test_bind_failure_is_reported_not_raised(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        blocker.bind(("127.0.0.1", 0))
        try:
            server = DnsFilterServer(filtering.FilterEngine().decide, host="127.0.0.1", port=blocker.getsockname()[1])
            assert server.start() is False and server.error
        finally:
            blocker.close()


# --------------------------------------------------------------------------- #
# Security primitives
# --------------------------------------------------------------------------- #
class TestSecurity:
    def test_lan_client_detection(self):
        for ip in ("192.168.1.5", "10.0.0.2", "172.16.4.4", "127.0.0.1", "169.254.1.1", "100.64.0.9", "::1", "fd00::5", "::ffff:192.168.1.5"):
            assert security.is_lan_client(ip), ip
        for ip in ("8.8.8.8", "1.1.1.1", "203.0.113.9", "2001:4860:4860::8888", "not-an-ip", ""):
            assert not security.is_lan_client(ip), ip

    def fixed_pins(self, monkeypatch, *pins):
        sequence = iter(int(p) for p in pins)
        monkeypatch.setattr(security.secrets, "randbelow", lambda _n: next(sequence))

    def test_pin_expires_and_is_replaced(self, monkeypatch):
        self.fixed_pins(monkeypatch, "111111", "222222")
        pm = security.PinManager(ttl_s=60)
        assert pm.current()[0] == "111111"
        real = time.time
        monkeypatch.setattr(time, "time", lambda: real() + 61)
        assert pm.verify("111111", "1.1.1.1") == "bad"       # expired: the old PIN no longer works
        assert pm.current()[0] == "222222"

    def test_pin_is_single_use(self, monkeypatch):
        self.fixed_pins(monkeypatch, "111111", "222222")
        pm = security.PinManager()
        assert pm.verify("111111", "1.1.1.1") == "ok"
        assert pm.verify("111111", "1.1.1.1") == "bad"
        assert pm.current()[0] == "222222"

    def test_distributed_guessing_rotates_the_pin(self, monkeypatch):
        self.fixed_pins(monkeypatch, "111111", "222222")
        pm = security.PinManager(per_ip_failures=100, global_failures=4)
        for i in range(4):
            assert pm.verify("999999", f"10.0.0.{i}") == "bad"   # four different attackers
        assert pm.current()[0] == "222222"                       # PIN was invalidated by the attack
        assert pm.verify("111111", "10.0.0.99") == "bad"         # the old PIN is dead

    def test_signed_urls(self):
        secret = b"s" * 32
        exp = int(time.time()) + 60
        sig = security.sign_path(secret, "/snapshots/a/b.jpg", exp)
        assert security.verify_signature(secret, "/snapshots/a/b.jpg", exp, sig)
        assert not security.verify_signature(secret, "/snapshots/a/c.jpg", exp, sig)      # other file
        assert not security.verify_signature(secret, "/snapshots/a/b.jpg", exp + 1, sig)  # tampered expiry
        assert not security.verify_signature(b"x" * 32, "/snapshots/a/b.jpg", exp, sig)   # other secret
        old = int(time.time()) - 1
        assert not security.verify_signature(secret, "/snapshots/a/b.jpg", old, security.sign_path(secret, "/snapshots/a/b.jpg", old))

    def test_keys_are_hashed_and_prefixed(self):
        key = security.new_key(security.AGENT_PREFIX)
        assert key.startswith("hag_") and len(key) > 40
        assert security.hash_key(key) != key and len(security.hash_key(key)) == 64


# --------------------------------------------------------------------------- #
# Templates
# --------------------------------------------------------------------------- #
class TestTemplates:
    @pytest.mark.parametrize("bad", ['http://x";Start-Process calc;"', "http://x/path", "javascript:alert(1)", "http://a b", "http://x'y", "http://x`y", "https://a.com/?q=1", "ftp://x.com"])
    def test_unsafe_urls_rejected(self, bad):
        assert not templates.is_safe_base_url(bad)

    def test_installer_embeds_only_safe_urls_with_safe_quoting(self):
        script = templates.build_windows_installer(["http://192.168.1.7:8000", "https://evil'; calc; '", "https://ok.example.com"])
        assert "evil" not in script
        assert "@('http://192.168.1.7:8000', 'https://ok.example.com')" in script
        with pytest.raises(ValueError):
            templates.build_windows_installer(["javascript:1"])

    def test_installer_has_consent_and_no_hidden_execution(self):
        script = templates.build_windows_installer(["http://192.168.1.7:8000"])
        assert "Type YES" in script
        lowered = script.lower()
        assert "hidden" not in lowered and "wscript.shell" in lowered and ".vbs" not in lowered

    def test_mobile_page_is_escaped(self):
        page = templates.build_mobile_enroll_page("http://192.168.1.7:8000", 'n"><script>')
        assert "<script>" not in page.replace('<script nonce="n&quot;&gt;&lt;script&gt;">', "")
        with pytest.raises(ValueError):
            templates.build_mobile_enroll_page('http://x"><img src=x onerror=alert(1)>', "n")
