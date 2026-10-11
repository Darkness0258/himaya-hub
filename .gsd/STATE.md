---
updated: 2026-10-11T23:14:00Z
---

# Project State — Himaya

## Current Position

**Milestone:** Himaya v1.0 Cloud & Production Release
**Phase:** Phase 6: Cloud Deployment & Security Hardening
**Status:** verified & deployed
**Plan:** Live Cloud Hub on Render.com (`https://himaya-hub.onrender.com`), Supabase DB support, and multi-device agents verified

## Last Action

- Deployed production Docker web service to Render.com (`https://himaya-hub.onrender.com`) with health check, dynamic port resolution, and live cloud telemetry.
- Integrated dual-mode database support: persistent Supabase PostgreSQL via `DATABASE_URL` with transaction pooling, falling back to local SQLite with WAL mode.
- Deployed React 19 + TypeScript SPA parent dashboard cockpit (`/dashboard`) directly served by FastAPI hub with real-time WebSockets (`/ws`), dark theme, and remote controls.
- Hardened Hub security with API key authentication, SSRF protection on public URL resolution, directory traversal prevention for snapshots, and timing-safe token verification.
- Upgraded Android mobile agent to Gradle 8.7, Android Gradle Plugin 8.5, and Kotlin 2.0.20 with `MediaProjection` screen sharing and `VpnAgent` DNS enforcement.
- Automated zero-touch auto-enrollment for both Internet (`https://himaya-hub.onrender.com/enroll/win`) and LAN targets with 6-digit Quick PIN pairing and QR code generation.
- All test suites passing (`test_phase1.py`, `test_hub_full.py`, `test_phase4_e2e.py`, `test_production_hub.py`, `test_internet_auto_enroll.py`).

## Active Decisions

| Decision | Choice | Made | Affects |
|---|---|---|---|
| Cloud Hosting | Render.com Web Service via Docker | 2026-10-11 | 24/7 online availability with HTTPS |
| Cloud Database | Supabase PostgreSQL via DATABASE_URL (SQLite local fallback) | 2026-10-11 | Global persistence & multi-instance scaling |
| Web Dashboard | React 19 + Vite compiled and served statically by FastAPI | 2026-10-11 | Unified single-port deployment on Render |
| Windows Lock | `ctypes.windll.user32.LockWorkStation()` | 2026-10-08 | Native non-destructive screen lock |
| Windows Capture | `PIL.ImageGrab.grab()` with JPEG compression | 2026-10-08 | Scheduled snapshots |
| Android Enrollment | ADB Device Owner mode (`dpm set-device-owner`) | 2026-10-08 | Unbreakable MDM compliance |

## Blockers

*None.*
