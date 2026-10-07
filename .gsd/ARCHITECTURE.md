# ARCHITECTURE.md — Himaya System Design

> **Architecture Status**: Baseline Defined
> **System Topology**: Local-First Distributed Hub & Agent Architecture

```
                       ┌─────────────────────────┐
                       │  Parent Web Dashboard   │
                       │   (React / TypeScript)  │
                       └────────────┬────────────┘
                                    │ HTTP / WebSocket
                                    ▼
       ┌────────────────────────────────────────────────────────┐
       │                   Himaya Hub (FastAPI)                 │
       │                                                        │
       │  ┌──────────────────┐            ┌──────────────────┐  │
       │  │ Device Registry  │            │  Event Stream    │  │
       │  │ & Status Monitor │            │ (WebSocket Feed) │  │
       │  └────────┬─────────┘            └────────▲─────────┘  │
       │           │                               │            │
       │  ┌────────▼─────────┐            ┌────────┴─────────┐  │
       │  │  Remote Actions  │            │  Watchdog Timer  │  │
       │  │  Command Router  │            │ (Went-Dark Loop) │  │
       │  └────────┬─────────┘            └──────────────────┘  │
       └───────────┼────────────────────────────────────────────┘
                   │ WireGuard Tunnel / Local Network
         ┌─────────┴───────────────────────┐
         │                                 │
         ▼                                 ▼
┌────────────────────────┐      ┌────────────────────────┐
│  Android Agent Client  │      │  Windows Agent Client  │
│  (Kotlin Foreground)   │      │   (C# / Python Core)   │
│                        │      │                        │
│ - DevicePolicyManager  │      │ - Standard User Lock   │
│ - VpnService (DNS)     │      │ - Network Throttle     │
│ - VPN-Guard Watcher    │      │ - Heartbeat Reporter   │
│ - Snapshot Scheduler   │      │                        │
│ - Visible Notification │      └────────────────────────┘
└────────────────────────┘
```

---

## 1. System Components

### 1.1 Himaya Hub (`Himaya/hub`)
- **Runtime**: Python 3.10+, FastAPI, Uvicorn, Pydantic v2.
- **Data Layer**: In-memory registry with planned SQLite persistence.
- **Key Modules**:
  - `main.py`: REST routes (`/devices`, `/events`, `/health`, `/agents/{id}/*`, `/admin/{id}/action`) and WebSocket `/ws` broadcaster.
  - `models.py`: Schemas for `Device`, `DeviceStatus`, `EventType`, `Event`, `RemoteAction`.
  - Background Watchdog: Monitors device heartbeats; automatically flags device as offline and broadcasts `device_went_dark` if missed.

### 1.2 Android Agent (`Himaya/himaya-mobile`)
- **Runtime**: Android SDK (minSdk 24, targetSdk 34), Kotlin 1.9+.
- **Key Subsystems**:
  - `MainActivity`: Configuration entry point and explicit UI indicator (Status: Active / Paused).
  - `AgentService`: Foreground service with persistent ongoing notification (`himaya_agent_channel`). Runs the 4 continuous background loops:
    1. *Heartbeat Loop*: Every 20s to `/agents/{id}/heartbeat`.
    2. *VPN-Guard Loop*: Watches network interfaces; alerts `/agents/{id}/vpn-attempt` if untrusted VPN activated.
    3. *Policy Sync Loop*: Fetches latest rules from hub.
    4. *Snapshot Loop*: Captures periodic screen frame via `MediaProjection` and uploads securely.
  - `DeviceAdminReceiver`: Enables `DevicePolicyManager` for remote lock (`lockNow()`) and wipe.
  - `VpnAgent`: Extends `VpnService` to capture DNS queries and direct to AdGuard Home or local DNS engine.

### 1.3 Parent Web Dashboard (`Himaya/dashboard`)
- **Runtime**: React 18 / TypeScript / Vite / Tailwind CSS / Lucide icons.
- **Capabilities**:
  - Real-time live status of all enrolled devices (Online, Offline, Dark, Paused, Locked).
  - Quick action controls: Instant Lock, Unlock, Pause Internet, Push Notification, Wipe with confirmation modal.
  - Live activity feed subscribing to Hub `/ws`.
  - Snapshot timeline gallery.
  - Responsive layout optimized for desktop and mobile PWA usage.

### 1.4 Local DNS Engine (`Himaya/docker`)
- **Runtime**: AdGuard Home deployed via Docker Compose.
- **Port**: 53 (DNS), 3000/80 (Web UI).
- **Function**: Sinkholes known tracking, adult, and malicious domain queries, providing upstream resolution.

---

## 2. Communication Protocol & Security

1. **Agent-to-Hub Authentication**:
   - HTTP Header or token-based device identifier verification.
   - All external access operates over WireGuard VPN or trusted local LAN.
2. **Event Notification Flow**:
   - Agent posts event (`/agents/{id}/dns-block`, `/agents/{id}/vpn-attempt`) -> Hub stores in chronological log -> Hub broadcasts via WebSocket to active parent dashboards.
3. **Command Execution Flow**:
   - Parent initiates action from Dashboard -> Hub posts to `/admin/{id}/action` -> Hub pushes command to agent via WebSocket/push poll -> Agent executes native policy (e.g. `DevicePolicyManager.lockNow()`).

---

*Last updated: 2026-10-08*
