# Himaya repository instructions

## Repository shape

Himaya is a multi-component family device safety platform:

- `Himaya/hub/` is the FastAPI hub. It serves the dashboard, exposes REST and WebSocket APIs, stores device/event/command/rule/snapshot data, and starts the DNS and LAN discovery services during the application lifespan.
- `Himaya/agent-windows/` is the Windows background agent. It communicates with the hub over HTTP, sends heartbeats and telemetry, polls remote commands, applies policy through the Windows hosts file, and uses Windows startup/notification facilities.
- `Himaya/himaya-mobile/` is the Android agent. It is a Gradle Android application with a foreground `AgentService`, Device Policy Manager actions, VPN detection/enforcement support, HTTP communication, and MediaProjection screenshot flow.
- `Himaya/dashboard/` is a React 19 + TypeScript + Vite frontend. Its current source is still the Vite starter UI; do not assume the richer cockpit described in the README exists in this checkout.

The primary runtime path is:

`dashboard or device agent -> hub REST/WebSocket API -> database and queued commands`

The hub also starts:

- DNS filtering on UDP port `5353`, forwarding allowed queries to Cloudflare Family and sinkholing blocked domains.
- LAN discovery/enrollment on UDP port `5354`.
- A heartbeat watchdog that marks online devices offline after more than 45 seconds without a heartbeat.
- A Render keep-alive task when a public URL is configured.

The hub uses SQLite by default (`Himaya/hub/himaya.db`) and switches to PostgreSQL when `DATABASE_URL` or `SUPABASE_DB_URL` is set. `Himaya/hub/database.py` provides the compatibility layer, including placeholder conversion and fallback behavior.

## Commands

Run commands from the component directory named in each section.

### Hub backend

```powershell
cd Himaya/hub
pip install -r requirements.txt
python main.py
```

The local hub is served at `http://localhost:8000`.

Run the executable integration checks individually:

```powershell
cd Himaya/hub
python test_phase1.py
python test_hub_full.py
python test_phase4_e2e.py
python test_production_hub.py
python test_internet_auto_enroll.py
```

These scripts start their own Uvicorn server on dedicated localhost ports and exercise HTTP, WebSocket, persistence, snapshots, rules, command queues, and DNS behavior. They are not pytest test functions and should be run as scripts. A single focused check is run by selecting one script, for example `python test_phase1.py`.

Build/run the hub container:

```powershell
cd Himaya/hub
docker build -t himaya-hub .
docker run -p 8000:8000 himaya-hub
```

### Dashboard

```powershell
cd Himaya/dashboard
npm install
npm run dev
npm run build
npm run lint
npm run preview
```

`npm run build` performs the TypeScript project build and Vite production build. `npm run lint` runs Oxlint. There is no configured dashboard test script; to validate one frontend area, use the build/lint commands after making the focused change.

### Android agent

Run from `Himaya/himaya-mobile` using the checked-in Gradle wrapper:

```powershell
.\gradlew.bat assembleDebug
.\gradlew.bat assembleRelease
.\gradlew.bat lint
.\gradlew.bat test
.\gradlew.bat connectedAndroidTest
.\gradlew.bat installDebug
```

For a focused Android test, use Gradle's test filtering with the fully qualified test class or method:

```powershell
.\gradlew.bat test --tests "com.himaya.agent.ExampleTest"
.\gradlew.bat test --tests "com.himaya.agent.ExampleTest.exampleMethod"
```

Only use `connectedAndroidTest` when an emulator or physical device is available. The module targets SDK 34, supports API 24+, and compiles with Java/Kotlin 17.

### Windows agent

```powershell
cd Himaya/agent-windows
pip install requests pillow win10toast
python himaya_windows_agent.py
.\run_agent.bat
```

The agent requires administrator rights for hosts-file DNS changes. Its logs are written under `%LOCALAPPDATA%\HimayaAgent\logs`.

## Backend implementation conventions

- Add FastAPI routes in `Himaya/hub/main.py`; add or update Pydantic request/response models in `Himaya/hub/models.py` and persistence operations in `Himaya/hub/database.py`.
- Preserve the event flow through `emit()`: events are persisted and broadcast to connected WebSocket clients. Do not insert the same event separately when calling `emit()`.
- Remote actions use the `RemoteAction` enum, are dispatched through `/admin/{device_id}/action`, persisted as queued commands, and consumed by `/agents/{device_id}/commands`. When adding an action, update the hub dispatch logic and both platform agents' command handling as applicable.
- Device liveness is heartbeat-driven. Agent heartbeat endpoints update `last_seen`; the hub watchdog owns the offline transition.
- Keep startup/shutdown work in the FastAPI `lifespan` context. DNS and discovery are threaded services, while watchdog and keep-alive work are asyncio tasks.
- Use the existing `DBConnection`/`get_connection()` abstraction rather than opening a raw database connection. SQL is written in SQLite-style `?` placeholders so the PostgreSQL wrapper can translate them.
- Snapshot files belong under `Himaya/hub/data/snapshots/`, with metadata stored in the database. Keep file-serving routes and metadata updates consistent.
- Avoid broad silent exception handling in new code. Existing network/device loops intentionally log and continue; new failure paths should follow the surrounding logger behavior and preserve an explicit status or response.

## Agent conventions

- Windows agent network calls go through `HubClient` and its candidate URL failover; do not bypass that client for ordinary hub operations.
- Android monitoring is implemented as long-running coroutines in the foreground `AgentService`: heartbeat/command polling every 20 seconds, VPN checks every 10 seconds, and policy sync every 60 seconds.
- Android protection must remain user-visible: the service runs with a persistent notification. Device Policy Manager and MediaProjection operations require the existing user/admin consent flows.
- Keep platform payloads aligned with the hub endpoint names and the shared concepts in `models.py`: device registration, heartbeat, policy sync, DNS block, VPN attempt, commands, and snapshots.

## Frontend conventions

- The dashboard uses React function components and hooks, TypeScript's strict unused-local/unused-parameter checks, Vite bundling, and Oxlint.
- Preserve the existing Vite/TypeScript settings in `tsconfig.app.json`; unused imports and parameters fail the build.
- If connecting the dashboard to live hub state, use the hub's `/ws` WebSocket stream for telemetry and the REST endpoints for commands/configuration. Confirm the API response shape in `main.py` before adding client assumptions.

## Configuration and deployment

- Local hub defaults to SQLite and port 8000. `DATABASE_URL` enables PostgreSQL/Supabase; `HIMAYA_PUBLIC_URL` supplies the public self-ping/enrollment URL.
- `Himaya/docker-compose.yml` maps the hub HTTP port 8000, DNS container port 5353 to host UDP 5355, and discovery UDP 5354; it also defines optional AdGuard Home and Watchtower services.
- Render deployment uses `Himaya/render.yaml` and `Himaya/hub/Dockerfile`; Render supplies `PORT`, and the Docker command starts `uvicorn main:app`.
- Do not commit credentials or connection strings. Treat `.env` and database files as local runtime state.

## Change workflow

Follow the repository's canonical process in `PROJECT_RULES.md`: SPEC -> PLAN -> EXECUTE -> VERIFY -> COMMIT. Prefer search-first, targeted reads and small changes. Before claiming completion, run the smallest relevant build, lint, or executable integration script and report the command/output. Use the commit format `type(scope): description` when a commit is requested.

When behavior crosses the hub/Windows/Android boundary, update every affected implementation and its relevant integration test rather than changing only one client.
