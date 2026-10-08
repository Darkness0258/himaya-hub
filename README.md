# Himaya — Family Device Safety Hub

A local-first system where one admin dashboard filters content, tracks activity, and remotely controls every device in the house — stronger than typical parental-control apps, built to survive VPNs and factory resets, but never covert.

## Mission
Build a local-first system where one admin dashboard filters content, tracks activity, and remotely controls every device in the house — stronger than typical parental-control apps, built to survive VPNs and factory resets, but never covert.

## Ground rules
- **Visible, not hidden.** Every managed device shows a persistent "Himaya active" indicator. No disguised icons, no stealth mode.
- **Local-first.** The hub runs on hardware you own. No third-party cloud touches family data by default.
- **Consent for adults.** Enroll adults only if they agree — this is a child-safety tool, not surveillance of people who haven't opted in.
- **Log events, not content.** Store what happened (blocked URL, VPN attempt, time online), never message or call content.

## Architecture
1. **Hub** — spare PC or Raspberry Pi at home. Runs the DNS filter, device registry, rules engine, dashboard, and event feed.
2. **Agents** — one per device. Android first (Kotlin), then Windows. iOS deferred to v2 — Apple's MDM/Screen Time APIs are far more restrictive, don't promise parity.
3. **Parent app** — web/PWA, reaches the hub remotely over WireGuard. Reuse PHANTOM's dashboard, WireGuard tunnel, and auth — most of this is assembly, not new code.

## Admin feature set
### Remote control — no limits
- Instant lock / unlock
- Force-close or block any app
- Pause internet for one device instantly
- Push a message/notification to the device
- Remote wipe (lost/stolen device only, separate confirmation step)
- Change filter rules or schedule from anywhere

### Screen visibility — two modes
| Mode | What it does | Why this shape |
| --- | --- | --- |
| Scheduled snapshots | Screenshot every N minutes (configurable), added to the activity timeline | What Bark and similar tools actually ship — catches patterns without a live feed |
| On-demand live view | Admin starts a real-time session on request | Android enforces a persistent, unremovable notification the whole time it's active — can't be hidden without rooting the device, which kills the Play Store listing and opens the device to real attackers. Build the UX like starting tech support, not switching on a hidden camera |

## Continuous monitoring loops
Each agent runs four background loops:
- **Heartbeat** — every 15–30s, agent → hub. Missed heartbeats trigger a "device went dark" alert.
- **VPN-guard** — watches `ConnectivityManager`/`onRevoke()` for new VPN interfaces; alerts instantly, blocks it if Device Owner mode is enrolled.
- **Policy sync** — every 60s or on push; remote rule changes apply without reinstalling.
- **Snapshot** — fires on the interval above, uploads over the WireGuard tunnel.

Hub side: a WebSocket feed pushes all four loops to the dashboard live.

## Stack
- Hub backend: FastAPI, or your PHANTOM Axum backend — device auth and WireGuard are already built
- Dashboard: React/TS, same pattern as PHANTOM
- Android agent: Kotlin — `DevicePolicyManager` (Device Owner mode), `VpnService`/`ConnectivityManager` (VPN-guard), `MediaProjection` (screenshots + share)
- Windows agent: C# or Rust service, running under a standard (non-admin) kid account
- iOS: v2, parked

## Build loop
Each phase ships something testable before the next starts:
0. Prove DNS filtering works — run AdGuard Home for an hour
1. Hub skeleton: device registry + WebSocket event feed
2. Android agent: heartbeat + DNS enforcement
3. VPN-guard loop + Device Owner enrollment
4. Remote actions: lock / block / pause / wipe
5. Snapshot loop + timeline UI
6. On-demand screen-share session — build this last, it's the highest-risk feature to get wrong

## Unverified — confirm before building
- Exact `DevicePolicyManager` + `DISALLOW_CONFIG_VPN` behavior on your target Android versions
- Whether any OEM (Samsung, Xiaomi) weakens the MediaProjection notification requirement — stock Android doesn't allow it
- If this ever becomes a product for other families rather than personal use: consent and disclosure requirements get stricter than "I own the hardware," and vary by country