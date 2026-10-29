#!/usr/bin/env python3
"""Check that a Himaya hub works, from the outside, in about ten seconds.

    python tools/smoke_test.py http://192.168.1.20:8000
    python tools/smoke_test.py https://himaya-hub.onrender.com

It asks for the admin key (what you type is hidden) or reads HIMAYA_ADMIN_KEY. Then it pretends to be one
Windows PC: it pairs a throwaway device called "smoke-test-xxxx", sends a heartbeat, a screenshot and a short
live view, checks the WebSocket, and finally DELETES the throwaway device. It never touches your real
devices and never prints a key or the PIN.

Run it before you test with a phone or a PC. If it passes, the hub, the network path and the database are
fine, and any later problem is in the app or on the device. If it fails, the line marked FAIL says what to
look at. Paste those lines (they contain no secrets) when asking for help.

Needs only Python 3.9+. The WebSocket check also needs `pip install websockets` (skipped without it).
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import ipaddress
import json
import os
import secrets
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# Not a real picture: the hub only checks the JPEG header bytes.
JPEG = b"\xff\xd8\xff\xe0" + b"HIMAYA-SMOKE-TEST-" * 20 + b"\xff\xd9"


# --------------------------------------------------------------------------- #
# Small HTTP client (standard library only)
# --------------------------------------------------------------------------- #
@dataclass
class Reply:
    status: int = 0
    body: bytes = b""
    ms: int = 0
    error: str = ""
    headers: Dict[str, str] = field(default_factory=dict)

    def json(self) -> Any:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def why(self) -> str:
        """The hub's own explanation of an error, or a short snippet."""
        if self.error:
            return self.error
        detail = self.json().get("detail") if isinstance(self.json(), dict) else None
        if isinstance(detail, str):
            return detail
        text = self.body[:120].decode("utf-8", "replace").strip().replace("\n", " ")
        return text or f"HTTP {self.status}"


def describe_error(error: BaseException) -> str:
    reason = getattr(error, "reason", error)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "the TLS certificate is not trusted for this name (use the exact https address, or --insecure for a test hub)"
    if isinstance(reason, (TimeoutError, ssl.SSLError)) or "timed out" in str(reason):
        return "timed out: nothing answered in time"
    if isinstance(reason, ConnectionRefusedError):
        return "connection refused: nothing is listening at that address and port"
    return str(reason) or error.__class__.__name__


def multipart(field_name: str, filename: str, content: bytes, content_type: str) -> Tuple[bytes, str]:
    boundary = "----himaya" + secrets.token_hex(8)
    head = f'--{boundary}\r\nContent-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\nContent-Type: {content_type}\r\n\r\n'
    return head.encode() + content + f"\r\n--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


class Client:
    def __init__(self, base: str, insecure: bool = False, timeout: int = 30):
        self.base = base
        self.timeout = timeout
        self.context = ssl.create_default_context()
        if insecure:
            self.context.check_hostname = False
            self.context.verify_mode = ssl.CERT_NONE
        self.opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self.context))

    def call(self, method: str, path: str, key: Optional[str] = None, body: Optional[dict] = None,
             file: Optional[bytes] = None, timeout: Optional[int] = None) -> Reply:
        headers = {"User-Agent": "himaya-smoke-test", "Accept": "application/json"}
        data: Optional[bytes] = None
        if key:
            headers["X-API-Key"] = key
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        if file is not None:
            data, headers["Content-Type"] = multipart("file", "frame.jpg", file, "image/jpeg")
        request = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        began = time.monotonic()
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                return Reply(response.status, response.read(), int((time.monotonic() - began) * 1000), headers=dict(response.headers))
        except urllib.error.HTTPError as error:
            return Reply(error.code, error.read() or b"", int((time.monotonic() - began) * 1000), headers=dict(error.headers))
        except Exception as error:  # noqa: BLE001 - every network failure becomes a readable message
            return Reply(error=describe_error(error), ms=int((time.monotonic() - began) * 1000))


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
class Report:
    def __init__(self, out: Callable[[str], None] = print):
        self.out = out
        self.passed = self.failed = self.warned = self.skipped = 0

    def ok(self, name: str, detail: str = "", ms: Optional[int] = None) -> None:
        self.passed += 1
        self.out(f"  [ ok ] {name:<20} {detail}" + (f"  ({ms} ms)" if ms is not None else ""))

    def fail(self, name: str, why: str, *hints: str) -> None:
        self.failed += 1
        self.out(f"  [FAIL] {name:<20} {why}")
        for hint in hints:
            self.out(f"           -> {hint}")

    def warn(self, text: str, hint: str = "") -> None:
        self.warned += 1
        self.out(f"  [warn] {text}")
        if hint:
            self.out(f"           -> {hint}")

    def skip(self, name: str, why: str) -> None:
        self.skipped += 1
        self.out(f"  [skip] {name:<20} {why}")

    def note(self, text: str) -> None:
        self.out(f"         {text}")


def is_private_host(host: str) -> bool:
    if host in ("localhost", "") or host.endswith(".local"):
        return True
    try:
        return ipaddress.ip_address(host).is_private
    except ValueError:
        return False


def normalize(raw: str) -> str:
    """`192.168.1.20:8000` -> http://..., `hub.example.com` -> https://..., trailing slash removed."""
    text = raw.strip().rstrip("/")
    if "://" not in text:
        host = text.split("/")[0].rsplit(":", 1)[0] if text.count(":") == 1 else text.split("/")[0]
        text = ("http://" if is_private_host(host) else "https://") + text
    return text


# --------------------------------------------------------------------------- #
# The checks
# --------------------------------------------------------------------------- #
def wake(client: Client, report: Report, patience_s: int) -> Reply:
    """Wait for /health. A free Render service can need a minute to wake up."""
    began = time.monotonic()
    told = False
    while True:
        reply = client.call("GET", "/health", timeout=20)
        if reply.status == 200 and isinstance(reply.json(), dict) and reply.json().get("service") == "himaya-hub":
            return reply
        if reply.status in (401, 403) or (reply.status == 404 and not reply.error):
            return reply   # something answered, but it is not (this) hub: waiting will not help
        if time.monotonic() - began > patience_s:
            return reply
        if not told:
            report.note("waiting for the hub to answer (a hosted service on a free plan can take a minute to wake up)...")
            told = True
        time.sleep(3)


def hints_for_unreachable(reply: Reply, base: str) -> List[str]:
    hints = []
    text = reply.body[:2000].decode("utf-8", "replace").lower()
    if "suspend" in text:
        hints.append("The host says the service is suspended (on Render: free hours used up). It returns when the allowance resets.")
    elif reply.status in (502, 503, 504):
        hints.append("The host answered but the hub behind it is not up: still starting, crashed, or suspended. Check the service's logs.")
    elif reply.status == 404:
        hints.append("Something answered, but it is not a Himaya hub. Check the address (and the port).")
    elif reply.status == 0:
        hints.append("Check the address and port, that the hub is running, and that this computer can reach it (same Wi-Fi? firewall?).")
    if "onrender.com" in base:
        hints.append("On Render: open the service page and check Events and Logs.")
    return hints or [f"Unexpected answer from the host (HTTP {reply.status})."]


def run(base_url: str, key: str, insecure: bool = False, patience_s: int = 90, out: Callable[[str], None] = print) -> int:
    report = Report(out)
    base = normalize(base_url)
    client = Client(base, insecure=insecure)
    out(f"Himaya smoke test: {base}")
    if base.startswith("http://") and not is_private_host(base.split("//", 1)[1].split("/")[0].rsplit(":", 1)[0]):
        report.warn("Plain http to a public address: keys travel unencrypted.", "Use https:// away from home (docs/REMOTE-ACCESS.md).")

    # 1. Is a hub there at all?
    began = time.monotonic()
    reply = wake(client, report, patience_s)
    if reply.status != 200:
        report.fail("hub answers", reply.why(), *hints_for_unreachable(reply, base))
        return finish(report, out)
    version = reply.json().get("version", "?")
    report.ok("hub answers", f"version {version}", reply.ms)
    if time.monotonic() - began > 8:
        report.warn(f"The first answer took {int(time.monotonic() - began)} s.", "Normal if the service was asleep (free hosting). Devices will notice this delay the first time.")

    # 2. Is the admin key right?
    details_reply = client.call("GET", "/health/details", key)
    if details_reply.status == 401:
        report.fail("admin key", "this hub does not accept that key",
                    "Cloud hub: Render > your service > Environment > HIMAYA_ADMIN_KEY. Home hub: hub/data/admin_key.txt, or run `python main.py --reset-admin-key` in the hub folder.")
        return finish(report, out)
    if details_reply.status == 429:
        report.fail("admin key", "too many wrong keys were tried from this computer", "Wait a minute and try again.")
        return finish(report, out)
    if not details_reply.ok:
        report.fail("admin key", details_reply.why())
        return finish(report, out)
    details = details_reply.json()
    report.ok("admin key", f"database={details.get('database')}, devices={details.get('devices')}, online={details.get('online')}, up {details.get('uptime_s', 0)} s", details_reply.ms)

    # 3. What does the Enroll page offer?
    info_reply = client.call("GET", "/enroll/info", key)
    if not info_reply.ok:
        report.fail("enroll info", info_reply.why())
        return finish(report, out)
    info = info_reply.json()
    urls = ", ".join(f"{u.get('kind')}={u.get('url')}" for u in info.get("urls", []))
    report.ok("enroll info", urls or "no addresses listed", info_reply.ms)
    cloud = bool(info.get("is_cloud"))
    if cloud and details.get("database") == "sqlite":
        report.warn("This is a cloud hub using SQLite: devices and keys vanish whenever the service restarts or redeploys.",
                    "Set DATABASE_URL to a free PostgreSQL database (see docs/DEPLOY.md).")
    if cloud and not any(str(u.get("url", "")).startswith("https://") for u in info.get("urls", [])):
        report.warn("A cloud hub shows no https address on the Enroll page.", "Set HIMAYA_PUBLIC_URL to the service's https address.")
    if not cloud and not (details.get("dns") or {}).get("running"):
        report.warn("The hub's DNS filter is not running, so the hub is not filtering websites.", "Check HIMAYA_DNS_ENABLED and that nothing else uses the DNS port.")
    if cloud:
        report.note("Cloud hub: the website filter (DNS) is off by design; Android falls back to a public family-safe DNS.")

    # 4..8. Act as one throwaway Windows PC. Whatever happens, remove it at the end.
    name = f"smoke-test-{secrets.token_hex(2)}"
    device_id = ""
    try:
        paired = client.call("POST", "/enroll/pair", body={"pin": info.get("pin"), "name": name, "platform": "windows", "owner_type": "child"})
        if not paired.ok:
            report.fail("pairing", paired.why(), "The PIN comes from this hub's Enroll page; if it changed in between, run the test again.")
            return finish(report, out)
        device_id = paired.json()["device_id"]
        agent = paired.json()["agent_key"]
        report.ok("pairing", f"throwaway device '{name}'", paired.ms)

        steps: List[Tuple[str, Callable[[], None]]] = [
            ("heartbeat", lambda: check_heartbeat(client, report, key, agent, device_id)),
            ("screenshot", lambda: check_screenshot(client, report, key, agent, device_id)),
            ("live view", lambda: check_live(client, report, key, agent, device_id)),
            ("websocket", lambda: check_websocket(client, report, key, insecure)),
        ]
        for step_name, step in steps:
            try:
                step()
            except Exception as error:  # noqa: BLE001 - a broken step must not stop the cleanup
                report.fail(step_name, f"the check itself crashed: {error.__class__.__name__}: {error}")
    finally:
        if device_id:
            removed = client.call("DELETE", f"/devices/{device_id}", key)
            gone = removed.ok and not any(d.get("device_id") == device_id for d in client.call("GET", "/devices", key).json() or [])
            if gone:
                report.ok("cleanup", f"'{name}' removed", removed.ms)
            else:
                report.fail("cleanup", f"could not remove '{name}'", f"Delete it by hand in the dashboard (Devices > {name} > Remove).")
    return finish(report, out)


def check_heartbeat(client: Client, report: Report, key: str, agent: str, device_id: str) -> None:
    caps = {"os": "windows", "screenshots": True, "live_view": True}
    beat = client.call("POST", f"/agents/{device_id}/heartbeat", agent, {"caps": caps})
    if not beat.ok:
        report.fail("heartbeat", beat.why())
        return
    listed = [d for d in client.call("GET", "/devices", key).json() or [] if d.get("device_id") == device_id]
    if listed and listed[0].get("status") == "online":
        report.ok("heartbeat", "device shows as online", beat.ms)
    else:
        report.fail("heartbeat", "the device did not show as online after a heartbeat")


def check_screenshot(client: Client, report: Report, key: str, agent: str, device_id: str) -> None:
    sent = client.call("POST", f"/agents/{device_id}/snapshot", agent, file=JPEG)
    if not sent.ok:
        report.fail("screenshot", sent.why())
        return
    snapshot = sent.json().get("snapshot", {})
    fetched = client.call("GET", snapshot.get("url", "/none"))
    if fetched.ok and fetched.body == JPEG:
        report.ok("screenshot", "uploaded and read back through a signed link", sent.ms + fetched.ms)
    else:
        report.fail("screenshot", f"could not read it back ({fetched.why()})")
    if snapshot.get("id"):
        client.call("DELETE", f"/snapshots/{snapshot['id']}", key)


def check_live(client: Client, report: Report, key: str, agent: str, device_id: str) -> None:
    started = client.call("POST", f"/admin/{device_id}/action", key, {"action": "live_view", "payload": {"duration_s": 15}})
    if not started.ok:
        report.fail("live view", started.why())
        return
    url = started.json().get("live", {}).get("url", "/none")
    sent = client.call("POST", f"/agents/{device_id}/live-frame", agent, file=JPEG)
    shown = client.call("GET", url)
    client.call("POST", f"/admin/{device_id}/action", key, {"action": "stop_live_view"})
    after = client.call("POST", f"/agents/{device_id}/live-frame", agent, file=JPEG)
    if sent.ok and shown.ok and shown.body == JPEG and after.status == 409:
        report.ok("live view", "start, picture, stop: and no pictures accepted after stop", started.ms + sent.ms + shown.ms)
    else:
        report.fail("live view", f"start={started.status} frame={sent.status} read={shown.status} after-stop={after.status} (expected 200, 200, 200, 409)")


def check_websocket(client: Client, report: Report, key: str, insecure: bool) -> None:
    try:
        import websockets
    except ImportError:
        report.skip("websocket", "install the check with: pip install websockets")
        return
    url = client.base.replace("http", "ws", 1) + "/ws"
    use_ssl = client.context if url.startswith("wss://") else None

    async def talk() -> str:
        async with websockets.connect(url, ssl=use_ssl, open_timeout=20) as socket:
            await socket.send(json.dumps({"type": "auth", "key": key}))
            first = json.loads(await asyncio.wait_for(socket.recv(), 10))
            return str(first.get("type"))

    began = time.monotonic()
    try:
        kind = asyncio.run(talk())
    except Exception as error:  # noqa: BLE001
        report.fail("websocket", f"{error.__class__.__name__}: {error}",
                    "The dashboard's live updates use this. A proxy in front of the hub may be dropping WebSockets.")
        return
    if kind == "snapshot":
        report.ok("websocket", "connected, signed in, got the first update", int((time.monotonic() - began) * 1000))
    else:
        report.fail("websocket", f"expected a 'snapshot' message first, got '{kind}'")


def finish(report: Report, out: Callable[[str], None]) -> int:
    out("")
    out(f"  {report.passed} ok, {report.warned} warnings, {report.failed} failed, {report.skipped} skipped")
    if report.failed:
        out("  Not healthy. Fix the FAIL lines first, from the top. Nothing above them can be trusted.")
    else:
        out("  Healthy. Any problem from here is in the app or on the device, not the hub or the network.")
        out("  (The activity feed now shows a few 'smoke-test-xxxx' entries. They are harmless.)")
    return 1 if report.failed else 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check that a Himaya hub works, from the outside.")
    parser.add_argument("url", help="the hub address, like http://192.168.1.20:8000 or https://himaya-hub.onrender.com")
    parser.add_argument("--key", help="the admin key (better: leave this out and type it when asked, or set HIMAYA_ADMIN_KEY)")
    parser.add_argument("--insecure", action="store_true", help="do not verify the TLS certificate (only for a test hub)")
    parser.add_argument("--patience", type=int, default=90, help="seconds to wait for a sleeping hub to wake up (default 90)")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    key = args.key or os.environ.get("HIMAYA_ADMIN_KEY") or getpass.getpass("Admin key (hidden): ").strip()
    if not key:
        print("No admin key given.", file=sys.stderr)
        return 2
    if key.startswith("hag_"):
        print("That is a device key (hag_...). This test needs the parent's admin key.", file=sys.stderr)
        return 2
    return run(args.url, key.strip(), insecure=args.insecure, patience_s=args.patience)


if __name__ == "__main__":
    sys.exit(main())
