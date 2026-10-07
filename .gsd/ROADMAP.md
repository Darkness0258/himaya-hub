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
**Status:** 🔄 In Progress
**Objective:** Establish bidirectional command delivery from Dashboard -> Hub -> Agent, allowing real-time execution of device lock, internet pause, notification push, and remote wipe.
**Depends on:** Phase 2, Phase 3

**Plans:**
- [x] Plan 4.1: Implement Hub agent command polling / queue channel (`/agents/{id}/commands`)
- [x] Plan 4.2: Implement Android Agent command receiver and native action execution handlers
- [ ] Plan 4.3: End-to-end integration testing of Lock, Unlock, Pause Internet, and Push Alert commands

---

### Phase 5: Snapshot Loop & Timeline UI
**Status:** ⬜ Not Started
**Objective:** Implement periodic scheduled screen capture on Android via `MediaProjection` and display snapshot gallery on Dashboard.
**Depends on:** Phase 4

**Plans:**
- [ ] Plan 5.1: Hub endpoint for encrypted/authenticated snapshot upload and retrieval (`/agents/{id}/snapshot`)
- [ ] Plan 5.2: Android MediaProjection capture service with user consent and status notification
- [ ] Plan 5.3: Dashboard Snapshot Timeline viewer with timestamp inspection

---

### Phase 6: DNS Sinkhole Integration & Hardening
**Status:** ⬜ Not Started
**Objective:** Connect AdGuard Home Docker engine to Hub, route Android DNS through VpnService, and test VPN circumvent block.
**Depends on:** Phase 5

**Plans:**
- [ ] Plan 6.1: Docker compose configuration and Hub DNS block webhook ingestion
- [ ] Plan 6.2: Validate Android VPN-guard loop alerts on unauthorized tunnel changes
- [ ] Plan 6.3: Comprehensive audit and end-to-end verification

---

## Progress Summary

| Phase | Status | Plans | Complete |
|---|---|---|---|
| 1: Hub Skeleton & Event Feed | ✅ Complete | 2/2 | 100% |
| 2: Parent Web Dashboard | ✅ Complete | 4/4 | 100% |
| 3: Android Agent Core & Loops | ✅ Complete | 4/4 | 100% |
| 4: Remote Actions Pipeline | 🔄 In Progress | 2/3 | 66% |
| 5: Snapshot Loop & UI | ⬜ Not Started | 0/3 | 0% |
| 6: DNS Sinkhole & Hardening | ⬜ Not Started | 0/3 | 0% |

---

*Last updated: 2026-10-08*
