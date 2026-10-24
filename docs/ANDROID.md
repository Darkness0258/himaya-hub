# Android agent

The Android app (`himaya-mobile`, package `com.himaya.agent`) pairs a phone with your hub, keeps a visible "Himaya is active" notification, and carries out what the parent sets: lock, messages, internet pause, website filtering, screenshot requests.

> **Status of this release:** the app was type-checked against the Android 34 platform, its resources and manifest were validated with `aapt`, and its protocol and DNS-packet code was tested against the real hub (see below). It has **not** been built with Gradle or run on a phone yet. Expect to fix small build-environment details the first time you open it in Android Studio.

## Build

You need Android Studio (Hedgehog or newer) or the command-line SDK, and JDK 17.

```bash
cd himaya-mobile
./gradlew assembleDebug            # Windows: gradlew.bat assembleDebug
# APK: app/build/outputs/apk/debug/app-debug.apk
./gradlew testDebugUnitTest        # the 16 unit tests
```

`local.properties` must point at your SDK (`sdk.dir=...`). Android Studio writes it for you. Do not commit it.

Install with `adb install -r app/build/outputs/apk/debug/app-debug.apk`, or copy the APK to the phone.

## Pair a phone

1. In the dashboard open **Add a device**, choose **Android phone**. It shows a QR code, a link and a 6-digit PIN.
2. Open the link on the phone (or scan the code). Himaya opens and asks **"Connect to this hub?"** with the address. Confirm only if it is yours.
3. Type the PIN, choose whether a child or an adult uses the phone, tap **Connect**.
4. Switch on the protections on the same screen:
   * **Lock and erase** (Device admin): lets the parent lock the phone and erase it if it is lost.
   * **Notifications** (Android 13+): needed for the visible indicator and for messages.
   * **Filter websites**: starts the DNS-only VPN described below.

The PIN is never put into a link or a QR code. A link can only pre-fill the hub address.

## What runs on the phone

| Part | What it does |
| --- | --- |
| `AgentService` | Foreground service with the permanent notification. Heartbeat every 20 s (reports IP and capabilities, receives the desired lock/pause/bedtime state), command poll every 5 s, VPN watch every 20 s. The loops start once however many places start the service. |
| `VpnAgent` | The website filter. See next section. |
| `ScreenShareService` | Takes **one** screenshot after the child approves Android's own capture dialog, uploads it and stops. |
| `DeviceAdminReceiver` | Device admin with only the `force-lock` and `wipe-data` policies. |
| `BootReceiver` | Restarts the agent after a reboot or an update. |
| `HubClient`, `DnsPacket`, `Http` | Pure Kotlin: the hub protocol and the DNS packet code. These are what the JVM tests exercise. |

### The website filter (DNS-only VPN)

The first version routed all traffic (`0.0.0.0/0`) into a tunnel and never read it, which would have cut the phone's internet the moment it started. The new filter adds exactly **one route**: a fake DNS server address (`10.111.222.2/32`). Only DNS lookups enter the tunnel; everything else uses the normal connection.

* Each lookup is forwarded to the hub's DNS filter, which applies this phone's rules (categories, blocked and allowed sites, bedtime, pause) and records blocks. If the hub does not answer within two seconds, a family-safe public resolver (`1.1.1.3`) is used so the phone keeps working away from home.
* While the parent has **paused** the phone (or bedtime is active) the app answers lookups with the sinkhole address itself, so the pause holds even when the hub cannot be reached.
* Himaya's own app is excluded from the tunnel, so it can always reach the hub, including to be told to un-pause.
* If the user switches the VPN off or another VPN replaces it, the agent tells the parent.

The hub's DNS filter has to be reachable on UDP (default port `5300`; the hub tells the phone which port in every heartbeat).

## What the phone cannot do

* **Silent or scheduled screenshots.** Android requires the user to approve a capture. A parent's request becomes a notification ("Your parent asked to see your screen. Tap to choose"). That is deliberate and matches Himaya's consent rule.
* **Block other VPNs.** It reports them. Blocking needs Device Owner mode and has not been verified on real devices.
* **Withstand strict Private DNS.** If the child sets Private DNS to a fixed hostname in Android's settings, lookups no longer pass through the filter.
* **Stay alive on every brand of phone.** Some makers kill background apps aggressively. If the dashboard often shows the phone offline, allow Himaya to run in the background in the phone's battery settings. On Android 15 and newer, the time limit on `dataSync` foreground services may need the foreground type changed when `targetSdk` moves past 34.

## Device Owner mode (optional)

`enroll-device-owner.bat` makes Himaya the Device Owner of a freshly reset phone, so a child cannot uninstall or disable it from Settings. It does not hide anything. It needs the phone to have no accounts yet. Without it, everything above still works through the normal **Lock and erase** switch.

## How this was checked

| Check | Result |
| --- | --- |
| Compile (type-check) of every Kotlin file against `android-34.jar`, with stand-ins for OkHttp and AppCompat | clean |
| `aapt` build of the manifest and all resources against the Android 34 resources | clean (it found a real style-inheritance error, now fixed) |
| 16 JUnit tests: DNS packet parsing and building, IPv4 checksums, the hub client's requests and error handling | pass on a plain JVM |
| 24 live contract checks: the app's real `HubClient` pairs with a running hub, sends heartbeats, reads commands and state, reports blocks, a VPN and events, uploads a screenshot, and is rejected after its device is removed | pass (`tools/android_contract_check/run.sh`) |
| DNS packets built by the Kotlin code, parsed by dnspython; IPv4 checksum verified independently | pass |
| Gradle build, running on a device, the VPN on a real network, screen capture | **not done** |
