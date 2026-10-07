# SPEC.md — Project Specification

> **Status**: `FINALIZED`
>
> ⚠️ **Planning Lock**: Requirements finalized. System is ready for phase execution.

## Vision
Himaya is a local-first family device safety hub where one central admin dashboard filters content, tracks device activity, and remotely controls every managed device in the household. It is engineered to be stronger than typical parental-control apps, resilient against VPN circumvention and factory resets, while adhering strictly to safety and transparency principles: always visible to the child (never covert/stealth), local-first with zero external cloud dependencies by default, and logging operational events rather than private communications.

## Goals
1. **Hub Backend & Real-Time Event Feed** — FastAPI local hub running device registry, DNS event ingestion, heartbeat watchdog ("device went dark" alerts), remote action command queue, and WebSocket feed.
2. **Parent Admin Web Dashboard** — State-of-the-art web application providing a unified command center: live device health status cards, instant remote action controls (lock, unlock, pause internet, push notification, remote wipe), real-time event timeline via WebSocket, and scheduled screenshot inspection gallery.
3. **Android Agent Client (Kotlin)** — High-resilience Android foreground service leveraging `DevicePolicyManager` (Device Owner / Admin mode), `VpnService` for DNS enforcement, VPN-guard watchdog, periodic heartbeats, remote command receiver, and `MediaProjection` scheduled snapshots with explicit user-visible indicator.
4. **AdGuard Home / DNS Integration** — Local DNS sinkhole integration routing client DNS traffic to block malicious/inappropriate domains and reporting blocks to the hub.
5. **Windows Agent (v1.5)** — Lightweight background service for managed Windows accounts to report telemetry and enforce basic lock/pause actions.

## Non-Goals (Out of Scope)
- **Covert Surveillance / Stealth Mode**: No disguised icons or hidden execution. Every managed device displays a persistent, unremovable notification and indicator.
- **Content Snooping**: Absolutely no keylogging, audio/microphone eavesdropping, camera spying, or capturing private message/call text.
- **iOS MDM**: Deferred to v2 due to Apple's restrictive Screen Time sandbox and lack of parity.

## Ground Rules & Constraints
- **Visible, not hidden**: Managed devices explicitly show active protection.
- **Local-first**: Operates on a local home server / Raspberry Pi / spare PC without external third-party cloud data leakage. Reaches remotely via WireGuard.
- **Consent for adults**: Enrolls children by default; adult devices require explicit consent.
- **Log events, not content**: Stores operational occurrences (blocked domains, VPN attempts, uptime, heartbeats, screen snapshots).
- **Target OS**: Hub on Python 3.10+ (FastAPI), Web Dashboard in modern React/Vite/TS, Android 8.0+ (API 26-34).

## Success Criteria
- [x] Hub skeleton: device registry, REST endpoints, and WebSocket feed operational (Phase 1 verified).
- [ ] Parent Web Dashboard: responsive, sleek UI with real-time WebSocket connection, device cards, remote action dispatch, and event log.
- [ ] Android Agent: Clean Gradle build, robust `AgentService` foreground service with persistent notification, automatic reconnection, heartbeat loop (15-30s), and DNS redirect.
- [ ] VPN-Guard & Policy Enforcement: Android agent detects unauthorized VPN attempts and notifies hub.
- [ ] Remote Actions Dispatch & Execution: Hub admin commands (lock, unlock, pause internet, push notification, wipe) dispatches and triggers target agents.
- [ ] Scheduled Snapshot Loop & Viewer: Periodic screenshot capture via MediaProjection with timeline viewing on dashboard.

## Technical Architecture Overview

| Component | Technology | Primary Function |
|---|---|---|
| **Hub** | Python / FastAPI / WebSockets | Central registry, rule coordination, event broadcasting, command routing |
| **Dashboard** | React / TypeScript / Vite | Real-time family safety cockpit for parent devices |
| **Android Agent** | Kotlin / Android SDK (minSdk 24, targetSdk 34) | Local enforcement, VPN sinkhole, heartbeat, remote action handler |
| **DNS Engine** | AdGuard Home / Docker Compose | DNS filtering and ad/malware domain blocking |

---

*Last updated: 2026-10-08*
