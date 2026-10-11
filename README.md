# 🛡️ Himaya — Family Device Safety & Defense Hub

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Darkness0258/himaya-hub)
[![GitHub Repository](https://img.shields.io/badge/GitHub-Repository-blue?logo=github)](https://github.com/Darkness0258/himaya-hub)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://hub.docker.com)

A real-time parental defense and device management platform where one centralized admin cockpit monitors telemetry, enforces DNS content sinkholing, logs activity, and remotely controls devices across the house and over the Internet.

---

## 🚀 One-Click Cloud Deployment (Render + Supabase)

You can host the entire Himaya Hub online 24/7 on Render's free tier with persistent WebSockets and multi-device support.

### Option 1: 1-Click Render Deploy
Click the button below to deploy directly from the GitHub repository:

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/Darkness0258/himaya-hub)

1. Sign in to [Render](https://render.com).
2. Connect your GitHub account and select repository: `Darkness0258/himaya-hub`.
3. Choose **Docker** as the runtime.
4. Set **Root Directory** to `hub` (or leave empty if using `render.yaml`).
5. (Optional) In **Environment Variables**, add:
   - `DATABASE_URL`: Your Supabase PostgreSQL Connection String (Transaction Pooler or Direct).
   - `HIMAYA_PUBLIC_URL`: Your Render service URL (e.g., `https://himaya-hub.onrender.com`).
6. Click **Create Web Service**. Your live hub will be up in ~2 minutes!

---

### Option 2: Supabase Cloud Database Setup (Optional)
By default, the Hub runs on zero-configuration SQLite. To scale with a cloud PostgreSQL database:
1. Create a free project at [Supabase](https://supabase.com).
2. Open the **SQL Editor** in Supabase and run the schema file located in [`hub/supabase_schema.sql`](hub/supabase_schema.sql).
3. In **Project Settings** > **Database**, copy your **Connection String (URI)**.
4. Add the connection string to Render's environment variables as `DATABASE_URL`.
   The Hub automatically detects `DATABASE_URL` and switches to PostgreSQL tables seamlessly!

---

## 💻 Running Locally

### 1. Start the Hub
```powershell
cd hub
pip install -r requirements.txt
python main.py
```
The dashboard will be live at: **`http://localhost:8000`**

### 2. Auto-Enroll Real Devices

#### Windows PC (1-Click Auto-Enroll):
Open PowerShell on any target PC and run:
```powershell
irm http://localhost:8000/enroll/win | iex
```
*(If deployed online, replace `http://localhost:8000` with your Render URL, e.g., `irm https://himaya-hub.onrender.com/enroll/win | iex`)*

This installer:
- Creates a persistent background agent in `%LOCALAPPDATA%\HimayaAgent`
- Sets up an automatic Windows startup trigger (`.vbs`) to survive reboots
- Sends real-time heartbeats and screen snapshots to the Hub
- Handles remote locks, internet pauses, and parental policy syncs

#### Android Phone / Tablet:
1. Open the dashboard and click **⚡ Auto-Enroll Devices**.
2. Scan the generated QR code or open:
   `http://<HUB_IP>:8000/enroll/mobile`
3. Enter the 6-digit Quick PIN to establish protected Device Owner status.

---

## 🛡️ Admin Cockpit Capabilities

### Remote Control & Defense
- **Instant Device Lock / Unlock**: Remotely freeze target screens with one click.
- **Internet Pause / Unpause**: Cut off network access immediately.
- **Content Filtering & DNS Sinkhole**: Real-time sinkholing of malicious domains, adult sites, and gambling trackers to `0.0.0.0`.
- **Bedtime Curfews & Schedules**: Automated cutoffs with configurable time windows.
- **Live Activity Telemetry**: Sub-second WebSocket stream with connection status, security alerts, and heartbeat watchdog (flags devices offline after 45s of missed beats).
- **Screen Timeline**: Visual inspection of periodic snapshot captures.

---

## 🏗️ Architecture

1. **Hub Backend**: FastAPI + Uvicorn + WebSockets + Dual DB (SQLite & PostgreSQL).
2. **DNS Sinkhole**: Custom UDP DNS proxy forwarding clean queries to Quad9/Cloudflare Family and sinkholing blacklisted domains.
3. **LAN Discovery**: UDP beacon responder on port 5354 for zero-touch local Wi-Fi pairing.
4. **Dashboard**: High-performance dark-mode cybersecurity cockpit with Chart.js, Lucide icons, and live WebSocket telemetry.
5. **Windows Agent**: Native Python background agent running silently with automatic failover and multi-homed endpoint switching.
6. **Android Agent**: Kotlin Device Policy Manager + VPNService for DNS enforcement and screenshot uploads.