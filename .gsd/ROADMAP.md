---
milestone: Himaya v1.0
version: 1.0.0
updated: 2026-10-08T01:48:00Z
---

# Roadmap — Himaya Family Device Safety Hub

> **Current Phase:** Phase 4: Remote Actions Pipeline & End-to-End Validation
> **Status:** in_progress

## Must-Haves (from SPEC)

- [x] Hub core: device registry, REST endpoints, and WebSocket event feed (Phase 1 verified)
- [x] Parent Web Dashboard: real-time dashboard UI with WebSocket feed and remote control buttons (Phase 2 verified)
- [x] Android agent foreground service with persistent visible notification and 4 background loops (Phase 3 verified)
- [x] Remote action dispatch and execution pipeline (Lock, Unlock, Pause Internet, Wipe) (Phase 4 active)
- [ ] Activity timeline and snapshot inspection gallery
- [ ] AdGuard Home DNS sinkhole integration and VPN tamper detection

---

## Phases

### Phase 1: Hub Skeleton & Event Feed
**Status:** ✅ Complete
**Objective:** Deliver working FastAPI hub with device registry, in-memory store, event feed, and WebSocket broadcaster.
**Requirements:** REQ-HUB-01, REQ-HUB-02, REQ-HUB-03

**Plans:**
- [x] Plan 1.1: Implement FastAPI hub models, routes, and WebSocket server (`Himaya/hub/main.py`)
- [x] Plan 1.2: Verify hub device registration, heartbeat, and remote action endpoints (`Himaya/hub/test_phase1.py`)

---

### Phase 2: Parent Web Dashboard
**Status:** ✅ Complete
**Objective:** Build a responsive, high-aesthetic Parent Web Cockpit displaying live device cards, telemetry indicators, remote action controls, and real-time WebSocket event timeline.
**Depends on:** Phase 1

**Plans:**
- [x] Plan 2.1: Scaffold dashboard application with modern UI design system, state management, and API/WebSocket client
- [x] Plan 2.2: Implement Device Cards (Online/Offline/Dark/Locked status, IP, last seen, quick actions)
- [x] Plan 2.3: Implement Live Activity Event Stream and Remote Control Panel with confirmation modals
- [x] Plan 2.4: Validate end-to-end dashboard integration against live Hub backend

---

### Phase 3: Android Agent Core & Resilient Background Loops
**Status:** ✅ Complete
**Objective:** Solidify Android Kotlin agent codebase, fix Gradle build configuration, wire foreground `AgentService`, enforce visible ongoing notification, and activate the 4 continuous background monitoring loops.
**Depends on:** Phase 1

**Plans:**
- [x] Plan 3.1: Clean up and validate Gradle configuration (`build.gradle.kts`, dependencies, Kotlin compiler targets)
- [x] Plan 3.2: Complete `AgentService` implementation with heartbeat loop, VPN-guard monitor, and policy sync
- [x] Plan 3.3: Wire `DeviceAdminReceiver` and `DevicePolicyManager` for hardware lock and security compliance
- [x] Plan 3.4: Complete `MainActivity` setup UI and persistent visible status indicator

---

### Phase 4: Remote Actions Execution Pipeline
**Status:** ✅ Complete
**Objective:** Establish bidirectional command delivery from Dashboard -> Hub -> Agent, allowing real-time execution of device lock, internet pause, notification push, and remote wipe.
**Depends on:** Phase 2, Phase 3

**Plans:**
- [x] Plan 4.1: Implement Hub agent command polling / queue channel (`/agents/{id}/commands`)
- [x] Plan 4.2: Implement Android Agent command receiver and native action execution handlers
- [x] Plan 4.3: End-to-end integration testing of Lock, Unlock, Pause Internet, and Push Alert commands (`test_phase4_e2e.py`)

---

### Phase 5: Snapshot Loop & Timeline UI
**Status:** ✅ Complete
**Objective:** Implement periodic scheduled screen capture on Android via `MediaProjection` and Windows via `PIL.ImageGrab`, with encrypted upload and snapshot gallery on Dashboard.
**Depends on:** Phase 4

**Plans:**
- [x] Plan 5.1: Hub endpoint for encrypted/authenticated snapshot upload and retrieval (`/agents/{id}/snapshot`)
- [x] Plan 5.2: Android MediaProjection capture service & Windows PIL snapshot loop
- [x] Plan 5.3: Dashboard Snapshot Timeline viewer with image modal inspection (`/snapshots`)

---

### Phase 6: Cloud Deployment, DNS Sinkhole & Security Hardening
**Status:** ✅ Complete
**Objective:** Connect Cloud hosting (Render.com Docker Service + Supabase PostgreSQL), built-in RFC 1035 UDP DNS sinkhole, zero-touch internet auto-enrollment, and production security hardening.
**Depends on:** Phase 5

**Plans:**
- [x] Plan 6.1: Docker & Render deployment (`render.yaml`, `hub/Dockerfile`) with dynamic port and health check
- [x] Plan 6.2: Dual database persistence (Supabase PostgreSQL via `DATABASE_URL` with SQLite WAL fallback)
- [x] Plan 6.3: Production security hardening (API key auth, SSRF protection, path traversal defenses)
- [x] Plan 6.4: Zero-touch Internet & LAN auto-enrollment (`/enroll/info`, `/enroll/win`, `/enroll/mobile`)

---

## Progress Summary

| Phase | Status | Plans | Complete |
|---|---|---|---|
| 1: Hub Skeleton & Event Feed | ✅ Complete | 2/2 | 100% |
| 2: Parent Web Dashboard | ✅ Complete | 4/4 | 100% |
| 3: Android Agent Core & Loops | ✅ Complete | 4/4 | 100% |
| 4: Remote Actions Pipeline | ✅ Complete | 3/3 | 100% |
| 5: Snapshot Loop & UI | ✅ Complete | 3/3 | 100% |
| 6: Cloud & Security Hardening | ✅ Complete | 4/4 | 100% |

---

*Last updated: 2026-10-11*
