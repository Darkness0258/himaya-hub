# Hub API

Base URL: the hub's address, for example `http://192.168.1.20:8000`. Bodies are JSON unless noted. Errors look like `{"detail": "..."}` (validation errors give a list under `detail`).

## Authentication

| Who | How | Can |
| --- | --- | --- |
| **Parent** | `X-API-Key: <admin key>` | Everything. |
| **Agent** | `X-API-Key: <device key>` (issued when the device pairs) | Only `/agents/<its own id>/...`, plus read its own device and rules. |
| **Anyone** | nothing | Public pages, `/health`, `/enroll/pair` (needs the PIN), signed screenshot links. |

Ten wrong keys from one address in a minute lock that address out for a minute (`429`). Only SHA-256 hashes of keys are stored.

## Public

| Method and path | Purpose |
| --- | --- |
| `GET /health` | `{"status":"ok","service":"himaya-hub","version":"2.0.0"}`. Nothing else. |
| `GET /`, `GET /dashboard` | The dashboard. |
| `POST /enroll/pair` | Pair a device. Body `{"pin":"123456","name":"...","platform":"windows|android|...","owner_type":"child|adult"}`. Returns `{"device_id","agent_key","device","dns_port"}`. The PIN is single use: wrong PINs are `403`, repeated ones `429`. The server picks the device id. |
| `GET /enroll/win` | PowerShell installer (asks for consent and the PIN). Takes no parameters. |
| `GET /enroll/win/agent.py`, `GET /enroll/win/uninstall.ps1` | Files the installer downloads. |
| `GET /enroll/mobile` | A small page for phones, with a strict CSP. It never contains the PIN. |
| `GET /enroll/qr?kind=lan\|internet` | PNG QR code of the phone page. |
| `GET /snapshots/<device>/<file>?exp=&sig=` | A screenshot, through a signed link valid for 15 minutes. The admin key also works. |

## Parent

| Method and path | Purpose |
| --- | --- |
| `GET /api/me` | Check a key: `{"role","device_id","version"}` (also works for agent keys). |
| `GET /api/stats` | Counts, a 24-hour histogram, top blocked sites. |
| `GET /api/categories` | Block-list categories and how many sites each has. |
| `GET /api/settings` | Version, storage, time zone, DNS filter status, retention. |
| `GET /health/details` | Uptime, counts, DNS/discovery status. |
| `POST /api/admin-key/rotate` | New admin key (refused if it comes from `HIMAYA_ADMIN_KEY`). |
| `GET /devices`, `GET /devices/<id>` | Devices. `state` is `locked`, `paused`, `online` or `offline`; `caps` says what the agent can enforce. |
| `POST /devices` | Create a device by hand (returns its key once). |
| `PATCH /devices/<id>` | Rename or change `owner_type`. |
| `DELETE /devices/<id>` | Remove it, revoke its key, delete its history and screenshots. |
| `GET /events?limit&before_id&device_id&type` | Newest first. `type` is comma separated. Max 500 per page. |
| `GET /rules/<id>` | Rules plus `bedtime_active` and `effective_blocked_domains` (categories expanded). Agents can read their own. |
| `POST /rules/<id>` | **Partial** update of `blocked_categories`, `blocked_domains`, `allowed_domains`, `bedtime_enabled`, `bedtime_start`, `bedtime_end` (`HH:MM`), `snapshot_interval_s` (0 or 60 to 3600). Domains are normalised; bad ones are `422`. |
| `POST /admin/<id>/action` | `{"action": ..., "payload": {...}}`. See below. |
| `GET /snapshots?device_id&limit&before_id`, `DELETE /snapshots/<id>` | Screenshot list (each with a signed `url`) and delete. |
| `GET /enroll/info` | The current PIN, its time left, and the addresses and commands for each way a device can reach the hub. |
| `POST /enroll/pin/regenerate`, `POST /enroll/public-url` | New PIN; set the away-from-home address. |

### Actions

| `action` | Effect | Payload |
| --- | --- | --- |
| `lock`, `unlock` | Sets the device's **state** (`locked`). The agent enforces it until changed. | none |
| `pause`, `unpause` (`block_internet`, `unblock_internet`) | Sets the **state** (`paused`). The hub DNS answers nothing for the device while paused. | none |
| `push_notification` | A message on the screen. | `{"message": "...", max 500}` |
| `force_close_app` | Close a program or background app. | `{"app": "chrome"}` |
| `snapshot` | Ask for a screenshot (Android asks the child to approve). | none |
| `wipe` | Erase an Android phone. | `{"confirm": "<device_id>"}`; anything else is `400` |

## Agent

All under `/agents/<device_id>/` with the device key.

| Method and path | Body | Returns |
| --- | --- | --- |
| `POST heartbeat` | `{"ip","caps","agent_version"}` (all optional) | `{"state":{"locked","paused","bedtime_active"},"snapshot_interval_s","dns_port"}` |
| `GET commands` | | `{"commands":[{"id","action","payload"}],"state":{...}}`. Each command is returned **once**. |
| `POST dns-block` | `{"host"}` | `{"status":"ok"}` |
| `POST vpn-attempt` | `{"interface"}` | `{"status":"ok"}` |
| `POST event` | `{"type":"agent_stopped\|enforcement_notice","data":{...}}` | `{"status":"ok"}` |
| `POST snapshot` | multipart field `file`, a JPEG up to 6 MB | `{"snapshot":{...,"url"}}` |

For compatibility the hub still accepts `ip`, `host` and `interface` as query parameters.

## WebSocket `/ws`

1. Connect, then send `{"type":"auth","key":"<admin key>"}` within 10 seconds. (The key is never accepted in the URL.)
2. The hub answers with `{"type":"snapshot","devices":[...],"events":[...]}`, then pushes:
   * `{"type":"event","event":{...}}`
   * `{"type":"device","device":{...}}`
   * `{"type":"device_removed","device_id":"..."}`
   * `{"type":"heartbeat","device_id":"...","timestamp":"..."}`
3. Send `{"type":"ping"}` to get `{"type":"pong"}`. A wrong key gets `{"type":"auth_failed"}` and close code `4401`.

## Event types

`dns_block`, `vpn_attempt`, `device_went_dark`, `device_online`, `device_paired`, `device_locked`, `device_unlocked`, `remote_action`, `policy_sync`, `screenshot`, `agent_stopped`, `enforcement_notice`. Heartbeats are live-only and never stored.
