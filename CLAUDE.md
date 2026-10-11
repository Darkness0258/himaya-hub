# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Himaya** — Family Device Safety & Defense Hub. A real-time parental defense and device management platform with three main components:
1. **Hub Backend** (FastAPI + WebSockets + SQLite/PostgreSQL) — Central registry, DNS sinkhole, LAN discovery, event broadcasting
2. **Windows Agent** (Python) — Background protection engine with DNS filtering, screen lock, VPN detection, auto-enrollment
3. **Android Agent** (Kotlin/Gradle) — Device Policy Manager + VPNService for DNS enforcement and screenshot uploads
4. **Dashboard** (React 19 + TypeScript + Vite) — Cybersecurity cockpit with live WebSocket telemetry

## Recent Changes (Working Tree)
- **Dashboard Components** updated: ControlPanel, DeviceList, EventFeed, MetricCard, Overview
  - ControlPanel: Added `activeAction` state tracking, fixed import (removed unused `Clock`)
  - DeviceList: Simplified imports (Smartphone, ChevronRight), removed unused PlatformIcon component
  - EventFeed: Updated icon imports, changed screenshot icon from Clock to Camera
  - MetricCard: Fixed LucideIcon type import
  - Overview: Changed Devices icon to Monitor for online devices metric

## Build, Lint, Test Commands

### Hub Backend (Python/FastAPI)

```bash
cd Himaya/hub

# Install dependencies
pip install -r requirements.txt

# Run development server
python main.py
# Dashboard: http://localhost:8000

# Run tests
python test_phase1.py
python test_hub_full.py
python test_phase4_e2e.py
python test_production_hub.py
python test_internet_auto_enroll.py

# Run with Docker
docker build -t himaya-hub .
docker run -p 8000:8000 himaya-hub
```

### Windows Agent (Python)

```bash
cd Himaya/agent-windows

# Install dependencies (requests, pillow, win10toast)
pip install requests pillow win10toast

# Run agent directly
python himaya_windows_agent.py

# Or use the batch launcher
run_agent.bat

# Auto-enroll via PowerShell (1-click)
irm http://localhost:8000/enroll/win | iex
```

### Android Agent (Kotlin/Gradle)

```bash
cd Himaya/himaya-mobile

# Build debug APK
./gradlew assembleDebug

# Build release APK
./gradlew assembleRelease

# Install to connected device
./gradlew installDebug

# Run lint
./gradlew lint

# Run unit tests
./gradlew test

# Run connected Android tests (requires device/emulator)
./gradlew connectedAndroidTest
```

### Frontend Dashboard (React/TypeScript/Vite)

```bash
cd Himaya/dashboard

# Install dependencies
npm install

# Development server
npm run dev

# Type check + build
npm run build

# Lint
npm run lint

# Preview production build
npm run preview
```

## Architecture

### High-Level Data Flow
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Parent    │◄───►│   Hub API   │◄───►│  Windows    │
│  Dashboard  │ WS  │  (FastAPI)  │ HTTP│  Agent      │
│  (React)    │     │  Port 8000  │     │  (Python)   │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
                    ┌──────┴──────┐     ┌─────────────┐
                    │   SQLite    │     │  Android    │
                    │  / PostgreSQL    │  Agent      │
                    │  (Persistent)   │  (Kotlin)   │
                    └─────────────┘     └─────────────┘
                           ▲
                    ┌──────┴──────┐
                    │ DNS Sinkhole│
                    │  (UDP 5353) │
                    └─────────────┘
                    ┌─────────────┐
                    │LAN Discovery│
                    │  (UDP 5354) │
                    └─────────────┘
```

### Key Components

| Component | Technology | Entry Point | Port |
|-----------|------------|-------------|------|
| Hub API | FastAPI 0.110+ | `Himaya/hub/main.py` | 8000 (HTTP), 5353 (DNS), 5354 (Discovery) |
| Dashboard | React 19 + Vite + TS | `Himaya/dashboard/` | Served by Hub |
| Windows Agent | Python 3.10+ | `Himaya/agent-windows/himaya_windows_agent.py` | — |
| Android Agent | Kotlin + Gradle 8.4 | `Himaya/himaya-mobile/app/` | — |
| DNS Engine | Custom UDP server | `Himaya/hub/dns_server.py` | 5353 |
| LAN Discovery | UDP beacon | `Himaya/hub/discovery.py` | 5354 |

### Database
- **Default**: SQLite (`Himaya/hub/himaya.db`) — zero-config local persistence
- **Cloud**: PostgreSQL via Supabase — set `DATABASE_URL` env var
- Schema: `Himaya/hub/supabase_schema.sql`
- Tables: `devices`, `events`, `commands`, `rules`, `snapshots`, `settings`

### Critical Files
- `Himaya/hub/main.py` — FastAPI app with lifespan, WebSocket, DNS, discovery, auto-enrollment
- `Himaya/hub/database.py` — Unified SQLite/PostgreSQL connection wrapper
- `Himaya/hub/dns_server.py` — RFC 1035 DNS sinkhole proxy
- `Himaya/hub/discovery.py` — LAN auto-discovery beacon
- `Himaya/agent-windows/himaya_windows_agent.py` — Windows background agent
- `Himaya/himaya-mobile/app/src/main/java/com/himaya/agent/AgentService.kt` — Android foreground service

## Deployment

### Render.com (1-Click)
1. Click "Deploy to Render" button in README or visit: `https://render.com/deploy?repo=https://github.com/Darkness0258/himaya-hub`
2. Connect GitHub, select repo `Darkness0258/himaya-hub`
3. Runtime: Docker, Root Directory: `hub`
4. Env vars: `DATABASE_URL` (Supabase), `HIMAYA_PUBLIC_URL` (Render URL)

### Local Development
```bash
# Terminal 1: Hub
cd Himaya/hub && python main.py

# Terminal 2: Windows Agent (on target PC)
irm http://localhost:8000/enroll/win | iex

# Terminal 3: Android enrollment
# Open http://localhost:8000/enroll/mobile and scan QR / enter PIN
```

## Key Patterns & Conventions

### Python (Hub & Windows Agent)
- Async/await with `asyncio` for concurrent loops (heartbeat, VPN guard, policy sync, command polling)
- `database.py` provides unified `DBConnection` context manager for both SQLite and PostgreSQL
- Events emitted via `emit()` function broadcast to WebSocket clients AND persist to DB
- Lifespan context manager for startup/shutdown of DNS server, discovery, watchdog, keep-alive

### Kotlin (Android Agent)
- Foreground service (`AgentService`) with persistent notification
- `DevicePolicyManager` for Device Owner / Admin mode enrollment
- `VpnService` implementation (`VpnAgent`) for DNS enforcement
- `MediaProjection` for screenshot capture with user-visible indicator
- OkHttp for HTTP, coroutines for async work

### TypeScript/React (Dashboard)
- Vite + React 19 + TypeScript
- `oxlint` for linting (fast Rust-based linter)
- Dark-mode cybersecurity cockpit with Chart.js, Lucide icons
- Live WebSocket telemetry feed at `/ws`

## Common Tasks

### Add a new API endpoint (Hub)
1. Add route in `main.py`
2. Add Pydantic models in `models.py` if needed
3. Add DB operations in `database.py` if needed
4. Write test in `test_*.py`

### Add a new remote action
1. Add action to `RemoteAction` enum in `models.py`
2. Handle in `/admin/{device_id}/action` endpoint in `main.py`
3. Implement execution in Windows Agent (`execute_command`) and Android Agent (`AgentService`)

### Modify DNS blocklist
- Via API: `POST /rules/{device_id}` with `blocked_domains` array
- Windows Agent applies via hosts file (`DNSEngine.apply()`)
- Android Agent enforces via `VpnService` DNS routing

### Test locally with multiple devices
1. Start hub: `cd Himaya/hub && python main.py`
2. Get enrollment info: `curl http://localhost:8000/enroll/info`
3. Windows: run PowerShell command from response
4. Android: scan QR or open mobile URL, enter PIN

## Important Notes

- **Windows Agent requires Administrator** for DNS hosts file modification
- **Android Agent requires Device Owner** mode (ADB: `dpm set-device-owner`)
- **DNS sinkhole** runs on port 5353 — configure device DNS to hub IP
- **Render free tier** sleeps after 15 min — keep-alive ping runs every 9 min
- **Heartbeat watchdog** flags devices offline after 45s missed beats
- **No external cloud deps by default** — SQLite local, Supabase optional

## Testing Verification

After changes, run the relevant test suite:
- Hub: `python test_production_hub.py` (comprehensive E2E)
- Windows Agent: manual test via `run_agent.bat` + check logs in `%LOCALAPPDATA%\HimayaAgent\logs`
- Android: `./gradlew connectedAndroidTest` on device/emulator
- Dashboard: `npm run build` + `npm run lint`