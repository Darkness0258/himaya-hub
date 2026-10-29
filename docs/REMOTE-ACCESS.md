# Reaching the hub away from home

At home, devices reach the hub on your Wi-Fi (`192.168.x.x:8000`). Away from home they need another road in. This page helps you pick one and set it up.

## The short answer

| Device | Best way | Why |
| --- | --- | --- |
| Child's **Android phone** | **HTTPS** (Option A) or a cloud hub | An Android phone runs **one VPN at a time**, and Himaya's website filter *is* that VPN. A WireGuard VPN would switch the filter off. |
| Child's **Windows PC or laptop** | HTTPS (A) or WireGuard (B) | Either works. |
| **Parent's** phone or laptop (the dashboard) | HTTPS (A) or WireGuard (B) | These do not run Himaya's VPN, so there is no clash. |

What you get **away from home** on a child's Android phone:

* Lock, pause, messages, screenshots and rule changes all work (they use the hub over HTTPS).
* The website filter uses the hub's DNS only on your Wi-Fi. Away from home the phone uses a family-safe public resolver (`1.1.1.3`) after two seconds, so categories are blocked by that service but your own allow and block lists are not applied.

## First, find out if you can open a port (important in Pakistan)

Options A and B need your router to accept connections from the internet. Many home ISPs put customers behind **CGNAT**, which makes that impossible.

1. Look at the WAN or Internet IP address on your router's status page.
2. Search "what is my IP" in a browser.
3. If the two differ, or the router's address starts with `100.64` to `100.127`, you are behind CGNAT. Skip to **Option C**.

## Option A: HTTPS with Caddy (recommended)

Free certificate, renews by itself. The hub only ever sees encrypted traffic from outside.

1. **Get a name** that points at your home. DuckDNS is free: create `myfamily.duckdns.org` and set it to your home's public IP (it has an updater for when your IP changes).
2. **Open two ports** on your router, both forwarded to the hub computer: **TCP 80** and **TCP 443**. Never forward 8000 or 5300.
3. In `.env` (next to `docker-compose.yml`) add: `HIMAYA_DOMAIN=myfamily.duckdns.org`
4. Start it:

   ```
   docker compose -f docker-compose.yml -f docker-compose.https.yml up -d
   ```

   The first start takes a minute while the certificate is issued (port 80 must be reachable for that).
5. Check from a phone on mobile data (Wi-Fi off): open `https://myfamily.duckdns.org/health`. You should see `{"status":"ok",...}`.
6. Open the dashboard, then **Settings, Away from home**, and save `https://myfamily.duckdns.org`. **Add a device** now offers both addresses.
7. On a phone, type the address as `https://myfamily.duckdns.org` (include `https://`). Never paste a key into the address box: the app refuses it (from this release on).

What was checked: the configuration was validated with Caddy 2.8, and a hub behind Caddy was exercised over HTTPS (pairing, live view, WebSocket over `wss`, an oversized upload refused, and a forged `X-Forwarded-For` header not dodging the login limit). The certificate step itself needs a real domain, so that part is unverified.

## Option B: WireGuard (for PCs and the parent's own devices)

A private tunnel straight to the hub. Only the hub is reachable through it; the rest of the device's traffic does not go through your home.

1. Choose a name for your home (as in Option A, step 1).
2. Make the server config:

   ```
   python tools/wg_setup.py init --endpoint myfamily.duckdns.org
   ```

3. Forward **UDP 51820** on your router to the hub computer.
4. Start the tunnel on the hub computer: install WireGuard, then import `wireguard/server.conf` (Windows app) or run `sudo wg-quick up ./wireguard/server.conf` (Linux).
5. For each device: `python tools/wg_setup.py add parent-laptop`. Import the file it writes into the WireGuard app on that device (a QR code is shown for phones), then **delete the file**: it contains that device's private key.
6. In the dashboard, **Settings, Away from home**, save `http://10.8.0.1:8000`. The tunnel is already encrypted, so plain HTTP inside it is fine.

`wireguard/` is in `.gitignore`. It holds secret keys: do not share it or commit it. To remove a lost device: `python tools/wg_setup.py remove parent-laptop`, then restart the tunnel on the hub.

What was checked: the key maths matches the official test vectors (RFC 7748) and a second crypto library, and the generated files are consistent with each other. **The tunnel itself has not been run end to end**, and neither has DNS filtering through it.

## Option C: no open ports (CGNAT, or you do not want to open any)

* **A cloud hub** (Render, see [DEPLOY.md](DEPLOY.md)). Free plans have monthly limits and sleep when idle, so they suit testing better than daily use.
* **Cloudflare Tunnel** (free, needs a domain on Cloudflare). The hub computer makes an outbound connection, so no router changes are needed. Run `cloudflared tunnel --url http://localhost:8000` to try it: it prints a temporary `https://...trycloudflare.com` address, which changes every time. For a stable name, create a named tunnel in the Cloudflare dashboard. **Not tested here.**
* **A small rented server (VPS)** running the hub. Then Option A works there with no router at all.

## Safety checklist

* Forward **only** 80 and 443 (Option A) or UDP 51820 (Option B). Never 8000, never 5300.
* Reset any admin key that has ever been pasted into a chat, screenshot or the wrong box: `python main.py --reset-admin-key`.
* Keep `HIMAYA_TRUST_PROXY=1` **only** when the hub sits behind Caddy, as `docker-compose.https.yml` sets it. Without a proxy, leave it off, or anyone could forge the address the hub uses for its limits.
* Away from home, a child's phone should use `https://` addresses only.

## Troubleshooting

| Problem | Likely cause |
| --- | --- |
| "Could not reach http://..." | The address box contains something that is not an address (check for a key, a typo, or a missing `https://`). Or the phone is on a different network than the hub and you used the Wi-Fi address. |
| The certificate is never issued | Port 80 is not reaching the hub computer (router forwarding, firewall, or CGNAT). |
| `/health` works on Wi-Fi but not on mobile data | Port 443 is not forwarded, or the DuckDNS name points at an old IP. |
| The dashboard loads but live updates stop | A proxy in front is dropping WebSockets. Caddy handles them by default. |
| WireGuard connects but the hub does not answer | The hub computer's firewall blocks port 8000 on the tunnel interface. |

## What would make this better later

Away from home, the phone's DNS lookups cannot reach the hub (they are UDP). A small DNS-over-HTTPS endpoint on the hub would let the Android filter apply your own lists everywhere through the same HTTPS door. It is not built yet.
