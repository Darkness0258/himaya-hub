#!/usr/bin/env python3
"""Fill a Himaya hub with DEMO data so you can preview the dashboard.

Everything here is fake: invented device names, generated "screenshots" (drawn with Pillow, they
contain no real content) and made-up activity. Never run it against a hub that holds real family data.

    python tools/seed_demo.py --hub http://localhost:8000 --key hma_xxxxx
    python tools/seed_demo.py --hub http://localhost:8000 --key hma_xxxxx --db hub/data/himaya.db   # also back-fills 24h of history
    python tools/seed_demo.py --hub ... --key ... --keepalive                                       # keep the online devices "alive"

Needs: pip install requests pillow
"""
from __future__ import annotations

import argparse
import io
import json
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image, ImageDraw

DEVICES = [
    # name, platform, owner, online, caps
    ("Sarah's laptop", "windows", "child", True, {"os": "windows", "tray": True, "admin": False, "lock": True, "pause": "proxy", "hosts_blocking": False, "screenshots": True, "wipe": False}),
    ("Omar's tablet", "android", "child", False, {"os": "android", "lock": True, "vpn_dns": True, "pause": "dns", "screenshots": "on-request", "wipe": True}),
    ("Ayesha's phone", "android", "child", True, {"os": "android", "lock": True, "vpn_dns": True, "pause": "dns", "screenshots": "on-request", "wipe": True}),
    ("Dad's desktop", "windows", "adult", True, {"os": "windows", "tray": True, "admin": True, "lock": True, "pause": "proxy", "hosts_blocking": True, "screenshots": True, "wipe": False}),
]

BLOCKED = [("tiktok.com", "category:social"), ("roblox.com", "category:gaming"), ("pornhub.com", "category:adult"), ("kick.com", "custom"), ("discord.gg", "category:social"),
           ("bet365.com", "category:gambling"), ("instagram.com", "category:social"), ("twitch.tv", "category:social")]
APPS = ["Homework - Google Docs", "Minecraft", "Chrome - YouTube", "Spotify", "Khan Academy", "Roblox", "Word - Essay draft", "Calculator"]


def fake_screenshot(title: str, seed: int) -> bytes:
    """A made-up desktop: gradient wallpaper, a window with a title bar, a taskbar. No real content."""
    rnd = random.Random(seed)
    w, h = 1280, 800
    image = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(image)
    top = (rnd.randint(20, 60), rnd.randint(50, 110), rnd.randint(110, 190))
    bottom = (rnd.randint(10, 40), rnd.randint(20, 50), rnd.randint(60, 110))
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    x0, y0 = rnd.randint(80, 220), rnd.randint(60, 140)
    draw.rounded_rectangle((x0, y0, x0 + 820, y0 + 560), radius=14, fill=(245, 246, 250))
    draw.rounded_rectangle((x0, y0, x0 + 820, y0 + 44), radius=14, fill=(52, 66, 140))
    draw.rectangle((x0, y0 + 30, x0 + 820, y0 + 44), fill=(52, 66, 140))
    draw.text((x0 + 18, y0 + 14), title, fill=(255, 255, 255))
    for i in range(9):
        width = rnd.randint(320, 740)
        draw.rounded_rectangle((x0 + 30, y0 + 80 + i * 46, x0 + 30 + width, y0 + 96 + i * 46), radius=6, fill=(200 + rnd.randint(0, 30), 205 + rnd.randint(0, 25), 220))
    draw.rectangle((0, h - 48, w, h), fill=(18, 22, 44))
    for i in range(6):
        draw.rounded_rectangle((16 + i * 58, h - 40, 56 + i * 58, h - 8), radius=8, fill=(70 + i * 20, 90, 170))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=62)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hub", default="http://localhost:8000")
    parser.add_argument("--key", required=True, help="the hub's admin key")
    parser.add_argument("--db", help="path to the hub's SQLite file: also back-fill 24 hours of history (hub on this computer only)")
    parser.add_argument("--keepalive", action="store_true", help="keep sending heartbeats for the online devices until Ctrl+C")
    args = parser.parse_args()

    hub = args.hub.rstrip("/")
    parent = {"X-API-Key": args.key}
    api = requests.Session()

    def call(method: str, path: str, **kwargs):
        response = api.request(method, hub + path, timeout=15, **kwargs)
        if response.status_code >= 400:
            sys.exit(f"{method} {path} -> {response.status_code}: {response.text[:200]}")
        return response.json() if response.content else None

    existing = {d["name"] for d in call("get", "/devices", headers=parent)}
    agents = {}
    for name, platform, owner, online, caps in DEVICES:
        if name in existing:
            print(f"skip   {name} (already exists)")
            continue
        pin = call("get", "/enroll/info", headers=parent)["pin"]
        paired = call("post", "/enroll/pair", json={"pin": pin, "name": name, "platform": platform, "owner_type": owner})
        agents[name] = {"id": paired["device_id"], "headers": {"X-API-Key": paired["agent_key"]}, "online": online, "caps": caps, "platform": platform}
        print(f"paired {name} -> {paired['device_id']}")

    ids = {d["name"]: d["device_id"] for d in call("get", "/devices", headers=parent)}
    for name, info in agents.items():
        call("post", f"/agents/{info['id']}/heartbeat", headers=info["headers"], json={"ip": f"192.168.1.{random.randint(20, 90)}", "caps": info["caps"], "agent_version": "2.0.0"})

    # A few live-looking actions through the real API
    sarah, ayesha = ids.get("Sarah's laptop"), ids.get("Ayesha's phone")
    if sarah:
        call("post", f"/rules/{sarah}", headers=parent, json={"blocked_categories": ["adult", "gambling", "social"], "blocked_domains": ["kick.com", "tiktok.com"], "allowed_domains": ["discord.com"], "bedtime_enabled": True, "bedtime_start": "21:30", "bedtime_end": "07:00"})
    if ayesha:
        call("post", f"/admin/{ayesha}/action", headers=parent, json={"action": "pause"})
    if sarah and "Sarah's laptop" in agents:
        a = agents["Sarah's laptop"]
        for host in ("tiktok.com", "kick.com", "roblox.com"):
            call("post", f"/agents/{a['id']}/dns-block", headers=a["headers"], json={"host": host})
        call("post", f"/admin/{sarah}/action", headers=parent, json={"action": "push_notification", "payload": {"message": "Dinner is ready"}})
        call("post", f"/agents/{a['id']}/vpn-attempt", headers=a["headers"], json={"interface": "WireGuard Tunnel - WireGuard Tunnel"})
        for i in range(3):
            requests.post(f"{hub}/agents/{a['id']}/snapshot", headers=a["headers"], files={"file": ("s.jpg", fake_screenshot(random.choice(APPS), i), "image/jpeg")}, timeout=15)

    if args.db:
        backfill(Path(args.db), ids)

    print("\nDemo data is in. Open the dashboard and sign in with your admin key.")
    if args.keepalive:
        print("Keeping the online devices alive. Press Ctrl+C to stop.")
        try:
            while True:
                for name, info in agents.items():
                    if info["online"]:
                        requests.post(f"{hub}/agents/{info['id']}/heartbeat", headers=info["headers"], json={"caps": info["caps"], "agent_version": "2.0.0"}, timeout=10)
                time.sleep(10)
        except KeyboardInterrupt:
            pass
    return 0


def backfill(db_path: Path, ids: dict) -> None:
    """Spread believable events over the last 24 hours by writing straight to the hub's SQLite file."""
    root = Path(__file__).resolve().parent.parent / "hub"
    sys.path.insert(0, str(root))
    import database  # type: ignore

    database.configure(db_path)
    database.init_db()
    rnd = random.Random(7)
    now = datetime.now(timezone.utc)
    kids = [ids[n] for n in ("Sarah's laptop", "Omar's tablet", "Ayesha's phone") if n in ids]
    snap_dir = db_path.parent / "snapshots"
    count = 0
    for hours_ago in range(23, -1, -1):
        school = 7 <= (now - timedelta(hours=hours_ago)).astimezone().hour <= 20
        for _ in range(rnd.randint(1, 5) if school else rnd.randint(0, 1)):
            device = rnd.choice(kids)
            host, reason = rnd.choice(BLOCKED)
            stamp = now - timedelta(hours=hours_ago, minutes=rnd.randint(0, 55))
            database.insert_event(device, "dns_block", {"host": host, "reason": reason, "source": "hub-dns"}, stamp.isoformat())
            count += 1
    if "Omar's tablet" in ids:
        database.insert_event(ids["Omar's tablet"], "device_went_dark", {"name": "Omar's tablet"}, (now - timedelta(minutes=25)).isoformat())
        database.insert_event(ids["Omar's tablet"], "device_online", {"name": "Omar's tablet"}, (now - timedelta(hours=3)).isoformat())
    for device_id in kids[:1]:
        (snap_dir / device_id).mkdir(parents=True, exist_ok=True)
        for i in range(8):
            stamp = now - timedelta(minutes=12 * i + 4)
            filename = f"shot_demo_{i}.jpg"
            (snap_dir / device_id / filename).write_bytes(fake_screenshot(APPS[i % len(APPS)], 100 + i))
            with database.get_connection() as conn:
                conn.execute("INSERT INTO snapshots (device_id, filename, file_path, timestamp) VALUES (?, ?, ?, ?)", (device_id, filename, f"{device_id}/{filename}", stamp.isoformat()))
    print(f"back-filled {count} blocked-site events and 8 screenshots")


if __name__ == "__main__":
    sys.exit(main())
