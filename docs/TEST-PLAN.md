# Test plan

Test from the inside out: **hub, then network, then device.** Each stage has a clear pass or fail. Stop at the first failure and fix it before moving on, because everything after it depends on it.

Paste back only what is marked "paste back". None of it contains a key or a PIN.

## Stage 0: before you start

* **Reset any key that has been seen.** An admin key that appeared in a screenshot or chat must be replaced. Cloud hub: Render, your service, Environment, `HIMAYA_ADMIN_KEY`. Home hub: `python main.py --reset-admin-key` in `hub/`.
* **Know what Render's free plan does** (it explains most "it doesn't work" moments):
  * It **sleeps** when idle and takes 30 to 60 seconds to wake. The hub pings itself every 9 minutes to stay awake, which makes it run around the clock and use most of the monthly free hours. A second always-on free service can use up the allowance. Check Render's usage page.
  * It has **no permanent disk**. Without `DATABASE_URL` (a free PostgreSQL such as Supabase), devices and keys vanish whenever it restarts.
  * The website filter (DNS) is **off** on a cloud hub by design.
* For daily family use a hub **at home** is better. Use Render for the test, or as a spare.

## Stage 1: the hub (about 1 minute)

```
python tools/smoke_test.py https://himaya-hub.onrender.com
```

It asks for the admin key, pretends to be one Windows PC, checks everything the hub does, and deletes its throwaway device.

| You see | Meaning |
| --- | --- |
| All `ok` and 0 failed (9 `ok`, or 8 plus a skipped WebSocket check if `pip install websockets` was not done) | The hub, the database and the network path are fine. Go on. |
| `waiting for the hub to answer...` | Render is waking up. It waits up to 90 seconds by default. |
| `FAIL hub answers` | The service is down, suspended, or the address is wrong. Read the line under it. |
| `FAIL admin key` | Wrong key for this hub. |
| `warn ... cloud hub using SQLite` | Set `DATABASE_URL` or your devices will vanish on restart. |

**Paste back:** the whole output.

## Stage 2: Android

1. Build in Android Studio. If it fails, paste the **first** red error, not the last, and guess its kind first: version, missing SDK, or Kotlin.
2. On the phone: Add a device on the dashboard, Android, scan the QR code (or type the address, never a key, plus the PIN).
3. Switch on protection (step 2 in the app) and accept the VPN prompt.
4. Look at the app. It should match `docs/android-redesign-preview.png`: the shield logo, gold section titles, gold Connect button. This image is a mock render of the resource files, not a real screenshot, so small differences are normal.

| Do this on the dashboard | The phone should |
| --- | --- |
| Open the device | Show as online within seconds |
| Lock | Lock its screen (needs the "Lock and erase" permission, granted in the app) |
| Pause internet | Stop loading websites and apps (Himaya answers every lookup with a dead end) |
| Screenshot now | Ask you to approve the capture, then show the picture |
| Turn the VPN off on the phone | Cause a warning on the dashboard |

**Tecno, Infinix and itel phones:** their battery managers often kill background apps. If Himaya goes offline after a few minutes, allow it to auto-start and set battery usage to "no restrictions" in the phone's settings.

**Paste back:** what differed from the table, and the first red error if the build failed.

## Stage 3: Windows (use a spare PC or a test account)

1. Add a device, Windows. Paste the one line into PowerShell, give consent, type the PIN. A Himaya icon should appear near the clock.
2. Screenshot now: a picture appears on the dashboard.
3. **Live view** (new): the button is on the device page.
   * The PC shows a notice and the tray icon changes.
   * The picture updates about once a second and stops by itself after a minute.
   * Pressing Stop (or closing the window) ends it on the PC too.
   * It is refused if the PC is locked or offline, or if screenshots are off for that device.
4. Lock and Pause work as on Android.

## Stage 4: hardening (spare PC only)

Follow [TAMPER-RESISTANCE.md](TAMPER-RESISTANCE.md). In short: Standard account for the child, run `harden.ps1 -DryRun`, then for real, then check that deleting the folder fails and that ending the program brings it back within 5 minutes. `harden.ps1 -Remove` undoes it. **It has never been run on a real PC, so expect to find something.** That is what this stage is for.

## Stage 5: away from home (optional)

Only if you have a domain and can open ports. See [REMOTE-ACCESS.md](REMOTE-ACCESS.md). If your ISP uses CGNAT, use Cloudflare Tunnel or a rented server instead.

## Not bugs

* The first request to a sleeping Render service is slow.
* On a cloud hub the Android website filter falls back to a public family-safe DNS.
* Android asks you to approve each screen capture. That is deliberate.
* "smoke-test-xxxx" entries in the activity feed after Stage 1 are harmless.
