# What changed in this version (2.0.0)

This release finishes the product and fixes what stopped the first version from working end to end. Everything below was found by reading the code and then running it; where something could **not** be run in the environment used to produce this release, it says so.

## Read this first: upgrading

Pairing and authentication changed, so **existing devices must be re-enrolled once**.

1. Replace the project files with these (your `hub/.env` and `hub/data/` are not touched; this zip contains neither).
2. `hub/himaya.db` from the old version is copied into `hub/data/himaya.db` on first start. Your device list and old events carry over, but **old devices have no key**: remove them in the dashboard and add them again with a PIN.
3. Start the hub. It prints a new **admin key** once and saves it to `hub/data/admin_key.txt`. The dashboard asks for it.
4. Rebuild nothing: the new dashboard is already built into `hub/static`.
5. Windows PCs: uninstall the old agent (delete its startup entry), then run the one-liner from **Add a device**.
6. Android: build and install the new app, then pair it with a PIN.
7. **If you use Supabase:** the hub upgrades your existing tables in place (adds columns, creates `api_keys`) and turns on Row Level Security. Rotate the database password if `hub/.env` has ever left your computer.

## Why the first version did not work

These are the root causes, not the symptoms.

| Problem | Effect |
| --- | --- |
| `App.css` was never imported | The dashboard shipped unstyled. |
| `index.html` pointed at `/assets/...` but the hub only served `/static/...` | A blank page when opened from the hub. |
| The dashboard sent no API key | Every request was refused once parent authentication existed. |
| Both agents sent IPs, blocked hosts and VPN names in JSON bodies that the hub read from the query string | Those fields were silently lost. |
| The Windows agent parsed the hub's rules into a different schema | Rules were never applied (an exception swallowed by `except: pass`). |
| The Android app never closed its HTTP responses | A connection leaked per heartbeat. |
| Android targets API 34, which blocks plain HTTP by default | The app could not talk to a LAN hub at all. |
| `device_admin.xml` listed invalid policies | `lockNow()` would have been refused. |
| The Android VPN routed all traffic (`0.0.0.0/0`) into a tunnel nobody read | The phone would have lost its internet the moment it was switched on. |
| `RENDER=false` in `docker-compose.yml` was parsed as true | Local Docker runs behaved like a cloud deployment. |
| The SQLite file lived outside the Docker volume | All data was lost when the container was recreated. |

## Security

* **The pairing PIN was the constant `842019`**, printed on a public page, returned by an unauthenticated endpoint and **broadcast to the whole LAN** by the discovery beacon. It is now random, expires after 15 minutes, works once, is shown only to the signed-in parent, and is rate limited (and rotated when someone guesses).
* Parent endpoints, the WebSocket and screenshots were open. They now need the admin key; agents get a **per-device key** that can only talk to their own device and is revoked when the device is removed. Only hashes of keys are stored.
* Screenshots are served through short-lived signed links. They used to be readable by anyone who could guess a file name.
* **Script injection** in the Windows installer (a broken `_escape_powershell`) and **reflected XSS** on the mobile enrollment page via the `hub_url` parameter are fixed. The parameter is gone; the hub's own address is validated.
* The WebSocket accepted a `test_dns_block` message that injected fake events. Removed.
* The DNS filter was an **open resolver**; it now answers only LAN, loopback and CGNAT clients.
* `/health` leaked the hub's LAN and public IP and made a blocking call to a third-party service. It now returns three fields.
* CORS was `*` with credentials. It is off unless you list origins.
* An Android deep link or QR code used to **pair the phone to any hub automatically** (with the PIN in the link). It now only pre-fills the address, the person must confirm it, and the PIN is typed.
* Supabase: Row Level Security is switched on for all tables (the schema file did not, which exposes tables through Supabase's REST API).
* A wipe now needs the device name typed in the dashboard and is refused on non-Android devices.

## Fixed in the hub

* Partial rule updates wiped the blocklist. Updates now merge.
* The DNS sinkhole answered AAAA and HTTPS lookups with an A record. It now answers by type and applies each device's rules, bedtime and pause (it used to ignore the rules entirely).
* Blocked lookups from unknown clients were attributed to the first device in the list.
* The heartbeat watchdog ignored locked and paused devices, and crashed silently on PostgreSQL timestamps.
* Commands could be handed out twice by concurrent polls; the queue is now atomic.
* Unbounded growth: heartbeats were stored as events (one every 20 s per device). They are now live-only; events, commands and screenshots are pruned automatically.
* `python main.py --port` did not change the port the hub advertised.
* Discovery stopped for good on Windows after one ICMP error.
* Windows agent copies had diverged (the hub served the older one). `tools/sync_agent.py` and a test keep them identical.

## New

* **Dashboard**: a new UI (Home with a plain-language status sentence, Devices with a rules editor, Activity timeline, Screens, Add a device, Settings), sign-in, live updates over WebSocket with reconnect, light and dark themes, phone layout, and PWA metadata. Fonts are bundled so it works offline.
* **Windows agent**: rewritten. Tray indicator, lock, pause (per-user proxy, crash-safe), bedtime, hosts-file blocking that only touches its own marked block, VPN alerts, screenshots on the hub's schedule, uninstaller that tells the hub.
* **Windows installer**: explains what it does, asks for consent and the PIN, uses no hidden windows. Checked with PowerShell's own parser and run through its consent and pairing steps against a live hub.
* **Android**: pairing UI, a working DNS-only VPN, consent-based screenshot requests (with the stride, single-frame and Android 14 callback fixes), valid device-admin policies, persistent indicator, proper high-priority message channel, tamper reports.
* Per-device **capabilities** are reported, so the dashboard says plainly what Himaya can and cannot enforce on each device.
* Optional PostgreSQL support was tested with the whole suite, including a database created from the original Supabase schema.

## Removed

* The hand-written AdGuard Home config under `docker/` (it was hand-written, not in the format current AdGuard Home versions read, and had no admin account). AdGuard is now an optional compose profile that uses its own setup wizard.
* The old API test scripts (they tested the previous, unauthenticated API). Replaced by 233 automated tests (hub 133, Windows agent 38, dashboard 46, Android 16); see the README.
* Unused Android dependencies (coroutines, coil, media).

## Verified, and what was not

| Area | How it was checked |
| --- | --- |
| Hub | 133 automated tests; the real server was started and exercised (HTTP, WebSocket, DNS over UDP, discovery); the whole suite also ran on PostgreSQL 16, including a database created from your original Supabase schema. |
| Windows agent | 38 tests against a real hub; the PowerShell installer was parsed by PowerShell 7 and run through consent, PIN and pairing against a live hub, then the downloaded agent connected with the config it wrote. |
| Dashboard | 46 unit tests, lint, type-check and build; driven in headless Chromium at desktop and phone sizes, both themes, with a strict Content Security Policy, checking console errors, failed requests, horizontal overflow and colour contrast. |
| Android | Type-checked against the Android 34 platform; resources and manifest validated with `aapt`; 16 unit tests and 24 live contract checks run the app's real protocol and DNS-packet code against the real hub, and the packets were validated independently with dnspython. |
| **Not run** | The Android app was not built with Gradle or run on a device. The Windows-only steps were not run on Windows (shortcut creation, `pythonw`, registry proxy, `LockWorkStation`, hosts-file writes, tray icon). The Docker image and the Render deployment were not built. |

## About your repository

* Your git history (not these files) contains `hub/himaya.db`, two `sarah-tab-01` screenshots under `hub/data/snapshots/`, and `adguard/work/data/sessions.db`, which is **still tracked**. `.env` was never committed. If the repository is public and any of that was real, remove it: `git rm --cached adguard/work/data/sessions.db`, and consider `git filter-repo` for the history.
* The new `.gitignore` keeps databases, screenshots, keys and `.env` out of future commits.
