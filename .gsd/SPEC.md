# SPEC.md — Project Specification

> **Status**: `FINALIZED`
>
> ⚠️ **Planning Lock**: Requirements finalized. System is ready for phase execution.

## Vision
Himaya is a modern family device safety and parental defense platform supporting dual deployment modes: **Cloud-First 24/7 Hosting** (deployed on Render with persistent Supabase PostgreSQL and secure HTTPS/WSS device telemetry) and **Zero-Config Local-First Mode** (running on local hardware with SQLite). One central parent dashboard filters content, tracks real-time activity, and remotely controls managed devices (Windows & Android) across the household and over the Internet. It is engineered to survive VPN circumvention and factory resets, while strictly adhering to transparency and safety principles: always visible to the child (never covert/stealth), and logging operational security events rather than private communications.

## Goals
1. **Cloud & Local Hub Backend** — FastAPI hub deployed to Render.com with dual database support (PostgreSQL via Supabase or local SQLite), DNS event ingestion, heartbeat watchdog ("device went dark" alerts), remote action command queue, and live WebSocket broadcaster (`/ws`).
2. **Parent Admin Cockpit Dashboard** — State-of-the-art React 19 + TypeScript + Vite web dashboard served directly by the Hub, featuring: live device health status cards, instant remote action controls (lock, unlock, pause internet, push notification, remote wipe), real-time event timeline via WebSocket, and scheduled screenshot inspection gallery with image lightbox zoom.
3. **Android Agent Client (Kotlin)** — High-resilience Android foreground service leveraging `DevicePolicyManager` (Device Owner / Admin mode), `VpnService` for DNS enforcement, VPN-guard watchdog, periodic heartbeats, remote command receiver, and `MediaProjection` scheduled snapshots with explicit user-visible indicator.
4. **Windows Agent (Python/PyWin32)** — Background protection engine with `user32.LockWorkStation()` locking, desktop snapshots, Windows toast alerts, hosts-file DNS filtering, and auto-enrollment via 1-click PowerShell command.
5. **DNS Engine & Content Filter** — Built-in RFC 1035 UDP DNS sinkhole forwarding clean queries to Quad9/Cloudflare Family and sinkholing blacklisted domains (adult, gambling, custom blocked domains) to 0.0.0.0.
6. **Zero-Touch Auto-Enrollment** — Dynamic LAN and Internet onboarding with 6-digit Quick PIN, QR code pairing for mobile, and 1-click PowerShell installer for Windows over HTTPS.

## Non-Goals (Out of Scope)
- **Covert Surveillance / Stealth Mode**: No disguised icons or hidden execution. Every managed device displays a persistent, unremovable notification and indicator.
- **Content Snooping**: Absolutely no keylogging, audio/microphone eavesdropping, camera spying, or capturing private message/call text.
- **iOS MDM**: Deferred to v2 due to Apple's restrictive Screen Time sandbox and lack of parity.

## Ground Rules & Constraints
- **Visible, not hidden**: Managed devices explicitly show active protection.
- **Cloud-Ready & Local-First**: Deploys seamlessly to Render.com connected to Supabase PostgreSQL, while remaining fully functional offline on local hardware with zero external cloud dependencies.
- **Consent for adults**: Enrolls children by default; adult devices require explicit consent.
- **Log events, not content**: Stores operational occurrences (blocked domains, VPN attempts, uptime, heartbeats, screen snapshots).
- **Target OS**: Hub on Python 3.10+ (FastAPI), Web Dashboard in modern React 19/Vite/TS, Android 8.0+ (API 26-34), Windows 10/11.

## Success Criteria
- [x] Hub skeleton: device registry, REST endpoints, and WebSocket feed operational (Phase 1 verified).
- [x] Parent Web Dashboard: responsive cockpit UI with real-time WebSocket connection, device cards, remote action dispatch, and event log (Phase 2 verified).
- [x] Android Agent: Clean Gradle 8.7 build, robust `AgentService` foreground service with persistent notification, automatic reconnection, heartbeat loop, and DNS redirect (Phase 3 verified).
- [x] Remote Actions Dispatch & Execution: Hub admin commands (lock, unlock, pause internet, push notification, wipe) dispatches and triggers target agents (Phase 4 verified).
- [x] Scheduled Snapshot Loop & Viewer: Periodic screenshot capture via MediaProjection with timeline viewing on dashboard (Phase 5 verified).
- [x] Cloud Deployment & Production Hardening: 1-Click Render.com deployment with Supabase PostgreSQL, HTTPS public enrollment, and API key authentication (Phase 6 verified).

## Technical Architecture Overview

| Component | Technology | Primary Function |
|---|---|---|
| **Hub Backend** | Python / FastAPI / WebSockets / Uvicorn | Central registry, rule coordination, event broadcasting, command routing |
| **Cloud Deployment** | Render.com Docker Service | 24/7 web service with auto-scaling, HTTPS, and keep-alive pinging |
| **Database** | Supabase (PostgreSQL) / SQLite 3 | Dual persistence engine with automated schema and pool support |
| **Dashboard** | React 19 / TypeScript / Vite / Chart.js | Real-time family safety cockpit for parent devices |
| **Android Agent** | Kotlin / Android SDK (API 26-34) / Gradle 8.7 | Local enforcement, VPN sinkhole, heartbeat, remote action handler |
| **Windows Agent** | Python / ctypes / PIL / Win10Toast | Screen lock, desktop snapshotting, hosts-file DNS filtering |
| **DNS Engine** | Built-in RFC 1035 UDP Proxy (5353) | DNS filtering and ad/malware domain blocking via Cloudflare upstream |

---

*Last updated: 2026-10-11*
