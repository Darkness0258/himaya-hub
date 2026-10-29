# Security notes

Himaya holds a family's activity and screenshots, so it is built to fail closed. This page explains the model, what is and is not protected, and what you should do.

## Credentials

| Secret | Who has it | Stored as | If it leaks |
| --- | --- | --- | --- |
| **Admin key** (`hma_...`) | The parent | SHA-256 hash in the database. Also in `data/admin_key.txt` (mode 600) unless set with `HIMAYA_ADMIN_KEY`. | Create a new one in Settings, or `python main.py --reset-admin-key`. |
| **Device key** (`hag_...`) | One device | SHA-256 hash in the `api_keys` table; plaintext only on the device. | Remove the device in the dashboard: its key stops working at once. |
| **Pairing PIN** | Shown to the signed-in parent | In memory only | Random, 15 minutes, single use, rate limited. Guessing triggers a new PIN. |
| **Screenshot links** | The dashboard | HMAC signature, 15 minutes | They expire; the secret is generated per hub. |

Keys have 256 bits of randomness, so a fast hash is appropriate. They are not passwords people choose.

## What is protected

* Every parent and agent route needs a key. Agents are confined to their own device.
* PIN enrollment cannot be brute-forced (5 tries per address, 12 overall per 5 minutes, then the PIN changes).
* The WebSocket authenticates with a first message, so keys never appear in URLs or logs.
* The dashboard is served with a strict Content Security Policy (no inline scripts), `nosniff`, no framing, no referrer.
* Generated PowerShell and HTML only ever embed validated addresses (`http(s)://host[:port]`) and are escaped.
* Uploads are checked: JPEG only, size limited. Paths are resolved and confined to the screenshot folder.
* The DNS filter and discovery beacon answer only LAN, loopback, link-local and CGNAT (Tailscale-style) addresses.
* On PostgreSQL / Supabase, Row Level Security is switched on for every table.

* **Live view is short, parent-started and visible.** It runs for at most two minutes, only if screenshots are allowed for that device, only on a device that is online and unlocked, and the child sees a notice and a changed tray icon while it runs. Pictures are held in the hub's memory only: never saved to disk or the database, and discarded when it ends. It is recorded in the activity log.

## What is not protected (read this)

* **Plain HTTP on your Wi-Fi.** Keys and screenshots cross the LAN unencrypted unless you put the hub behind HTTPS. On a home network that is a modest risk; away from home use HTTPS (a reverse proxy or a cloud hub) or WireGuard: see [REMOTE-ACCESS.md](REMOTE-ACCESS.md). The Android app allows cleartext on purpose, because a LAN hub has no certificate.
* **Tamper resistance.** Himaya is visible and tamper-*evident* by default. A child who can run Task Manager can stop the Windows agent; the parent is alerted when the device goes quiet. Use a standard (non-admin) Windows account, and optionally `agent-windows/harden.ps1`, which stops the child deleting or uninstalling it and brings it back within 5 minutes if closed. Android Device Owner mode is stricter and is opt-in. What each level stops, and does not, is in [TAMPER-RESISTANCE.md](TAMPER-RESISTANCE.md).
* **Android Private DNS (strict mode)** and DNS-over-HTTPS in a browser bypass any DNS filter. The agent reports the filter or VPN being switched off; it cannot lock those settings without Device Owner mode.
* **Local access.** Anyone who can read the hub's data folder can read screenshots and `admin_key.txt`. Keep the hub computer protected, and keep `hub/data` out of backups you share.
* **Cloud free tiers** (Render) erase the local SQLite file when the service restarts. Use `DATABASE_URL` (PostgreSQL), and understand that screenshots would still be on the host's temporary disk.

## Your checklist

1. Keep the hub on a computer only you can log into. Never forward port 8000 or 5300 to the internet. Use HTTPS or WireGuard ([REMOTE-ACCESS.md](REMOTE-ACCESS.md)).
2. Never paste an admin or device key (`hma_...`, `hag_...`) into a chat, a screenshot or the hub address box. If you did, reset it: `python main.py --reset-admin-key`.
3. If `hub/.env` or a database password has ever been shared or committed, change it.
4. Remove devices you no longer use (it revokes their keys).
5. Tell the people whose devices you add. Adults must agree.
6. Check `data/` is not inside a folder that syncs to a cloud drive.

## Reporting a problem

Open an issue in your repository, or fix it and add a test. The test suites (`hub/tests`, `agent-windows/tests`) include regressions for every vulnerability listed in [CHANGES.md](../CHANGES.md).
