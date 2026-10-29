# Deployment

## On a computer at home (recommended)

```bash
cd hub
pip install -r requirements.txt
python main.py            # or hub\start_hub.bat on Windows
```

Data lives in `hub/data/` (database, screenshots, `admin_key.txt`, optional `blocklists/`). **Back up that folder** to keep your devices when you move to another computer; copy it over and start the hub.

Keep the computer on. A spare laptop or a Raspberry Pi is ideal. Give it a fixed address in your router so devices always find it.

## Docker

```bash
cp .env.example .env       # set HIMAYA_LAN_IP to the host's LAN address
docker compose up -d --build
docker compose exec himaya-hub cat /app/data/admin_key.txt      # the admin key
```

* Data is in the named volume `himaya-data`, so it survives rebuilds.
* The container cannot know the host's LAN address, so set `HIMAYA_LAN_IP`, or enrollment links show an unusable Docker address.
* LAN discovery (UDP broadcast) does not cross Docker's bridge. On Linux you can use `network_mode: host`; otherwise type the hub address into the phone app.

### Optional: AdGuard Home for the whole network

```bash
docker compose --profile adguard up -d
```

It needs host port 53 (on Ubuntu, free it from `systemd-resolved`). Open `http://<host>:3000` once and create the AdGuard admin account in its setup wizard. Himaya's own DNS filter does not need AdGuard.

## Render (free cloud hosting) with Supabase

A cloud hub means your family's activity lives on someone else's computer. Prefer a home hub unless you need it.

1. Create a free PostgreSQL database (for example on Supabase) and copy its connection string.
2. Push this repository to GitHub, then in Render choose **New, Blueprint** and select it (`render.yaml`).
3. In the service's **Environment** tab set `DATABASE_URL` to the connection string and `HIMAYA_PUBLIC_URL` to your `https://...onrender.com` address. Render generates `HIMAYA_ADMIN_KEY`: read it there and use it to sign in.
4. Add devices from the dashboard, choosing the **Away from home** address.

Notes:

* The free plan sleeps when idle and has **no permanent disk**. Without `DATABASE_URL`, devices and keys vanish whenever the service restarts, and screenshots always live on temporary disk. The hub prints a warning at start-up when it sees this.
* The hub pings its own address every 9 minutes to stay awake (`HIMAYA_KEEPALIVE`).
* Cloud mode turns the DNS filter and the LAN beacon off: UDP does not reach a web service. Website filtering on a cloud hub therefore applies only where agents enforce it themselves (the Windows hosts file).
* The hub upgrades Supabase tables in place and turns on Row Level Security so the project's REST API cannot read them.

## Reaching the hub away from home

Phones and laptops leave your Wi-Fi. The full guide is [REMOTE-ACCESS.md](REMOTE-ACCESS.md). In short:

1. **HTTPS with Caddy** and a DuckDNS name: `docker compose -f docker-compose.yml -f docker-compose.https.yml up -d`. Best for children's Android phones, because a phone can run only one VPN and Himaya's website filter uses it.
2. **WireGuard** (`python tools/wg_setup.py`) for PCs and the parent's own devices.
3. A cloud hub (above), or Cloudflare Tunnel, if your ISP does not let you open ports (CGNAT).

Never forward port 8000 or 5300 to the internet.

Once a public address is saved, **Add a device** offers both addresses and the installer lists both, trying the Wi-Fi one first.

## Use the hub as your devices' DNS server

The hub's DNS filter listens on UDP `5300` by default, which only apps that can pick a port (the Android app does) can use. To make a Windows PC, or your whole network, use it:

1. Run the filter on port 53: set `HIMAYA_DNS_PORT=53` (Windows: no special rights; Linux: run as root or grant the capability; Docker: `"53:53/udp"`). Check nothing else holds port 53 (`netstat -ano | findstr :53`).
2. Set the PC's network adapter DNS to the hub's address, or set the router's DHCP DNS server to it.
3. Rules, bedtime and pause then apply per device, matched by IP address. Give those devices fixed addresses.

Unknown devices that use the hub get only the default adult-content and gambling blocking. To add your own categories, drop `name.txt` files (one domain per line, hosts-file format also works) into `hub/data/blocklists/`.

## Time zone

Bedtime uses the hub's time zone. Set `HIMAYA_TIMEZONE` (for example `Asia/Karachi`) if the hub runs in UTC, as most containers do.

## Updating

Replace the project files, keep `hub/data` and `hub/.env`, restart. The database upgrades itself. After changing the dashboard source run `npm run build` in `dashboard/`; it writes into `hub/static`.
