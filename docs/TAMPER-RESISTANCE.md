# Tamper resistance: the decision

## The decision

Himaya is **visible and tamper-evident first**, and **tamper-resistant only where that is cheap and honest**. You choose per device, in three levels:

| Level | Name | What it is | Status |
| --- | --- | --- | --- |
| 0 | **Evident** (default) | Normal install. If the protection is stopped or removed, you are told. | Built and tested |
| 1 | **Hardened** (opt-in) | The agent moves where only an Administrator can change it, and comes back by itself if closed. | Windows: `agent-windows/harden.ps1` (not yet run on a real PC). Android: Device Owner (`himaya-mobile/enroll-device-owner.bat`). |
| 2 | **Unstoppable** | A Windows service the child cannot end. | **Not built. Decided against for now** (see below). |

Three rules hold at every level. They are part of what Himaya is, not settings:

1. **Himaya stays visible.** The tray icon, the notices and the Android notification never go away.
2. **The parent is told** when protection stops, goes quiet or is removed.
3. **Adults are only monitored by agreement.** Hardening is for a child's device, and the child should know.

## What stops what

"Child" means a child using a **Standard** Windows account. A child who is a local Administrator can undo any of this, so give a child a Standard account first.

| What the child tries (Windows) | Level 0 | Level 1 (`harden.ps1`) | Level 2 (not built) |
| --- | --- | --- | --- |
| Delete the Startup shortcut or the agent folder | Works. You are told it stopped. | **Blocked** (files are in `C:\Program Files\Himaya`, job made by an administrator) | Blocked |
| Run the uninstall script | Works. You are told. | **Blocked** (the uninstall script is not on the PC) | Blocked |
| End the program in Task Manager | Works until the next sign-in | Works, but it **returns within 5 minutes**. The hub shows offline (after about 75 s), then online. | Blocked |
| Read the device key and fake "I'm fine" messages while the agent is dead | Possible | Possible (the key file is readable by the child) | Blocked |
| Replace the Python the agent runs on | Possible | Possible if Python is in the child's own folder. Install Python for all users to prevent it. | Blocked |
| Use a different account, Safe Mode, or boot from USB | Possible | Possible | Possible |

| What the child tries (Android) | Device Admin (default) | Device Owner (opt-in) |
| --- | --- | --- |
| Uninstall the app | Must first remove the admin permission. **You are told.** | Blocked |
| Turn the Himaya VPN off or replace it with another VPN | Possible. **You are told.** | Can be kept on |
| Factory reset | Possible (you see it go offline) | Possible (a reset removes the owner too) |
| Private DNS or DNS-over-HTTPS in a browser | Bypasses the website filter. You are told if the VPN stops. | Same |

## Why not Level 2 now

A Windows service runs in a separate session with no desktop. It cannot take screenshots of the child's screen or show them a notice. A real Level 2 is therefore **two programs** (a protected service plus a helper in the child's session) that must trust each other, plus an installer that runs as SYSTEM. That is a lot of new security surface to get right, and it still does not help against a child who is an Administrator.

Level 1 closes the easy attacks (delete it, uninstall it, forget it) at a small fraction of the risk. Revisit Level 2 only if the Level 1 gaps above turn out to matter in real use.

## Recommended setup

| Child | Windows | Android |
| --- | --- | --- |
| Young (under about 12) | Standard account + **Level 1** | **Device Owner** on a freshly reset phone |
| Teenager | Standard account, Level 0 or 1 | Device Admin (default). Talk about why it is there. |
| Adult by agreement | Level 0, screenshots off | Level 0 |

## How to harden a Windows PC (Level 1)

Do this on a **spare PC or a test account first**: `harden.ps1` has been syntax-checked and its logic run against stand-ins for the Windows commands, but it has **not been run on a real Windows PC yet**.

1. Make the child's account a **Standard** user (Settings, Accounts, Family and other users, Change account type).
2. Sign in as the child and run the normal Himaya installer from the dashboard (Add a device).
3. Tell the child what you are about to do.
4. As the parent, open **PowerShell as Administrator** in the `agent-windows` folder and look first:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\harden.ps1 -ChildUser sarah -DryRun
   ```

5. Run it for real (drop `-DryRun`). The hub shows "Himaya was hardened on this PC".
6. Check it worked, signed in as the child:
   * The agent folder under `AppData\Local\HimayaAgent` and the Startup shortcut are gone.
   * `C:\Program Files\Himaya` cannot be changed or deleted.
   * End `pythonw.exe` in Task Manager. The tray icon returns within 5 minutes, and the dashboard shows the PC offline, then online.
7. To undo everything: `.\harden.ps1 -ChildUser sarah -Remove`.

What the script does is short and printed as it runs: it copies the agent to `C:\Program Files\Himaya`, gives the child read-and-run access only, creates a Task Scheduler job that starts the agent at sign-in and every 5 minutes (extra starts are ignored while it runs), and removes the old per-user copy.

Website blocking from the hosts file needs Administrator rights, which a Standard account does not have. For strong website filtering on a hardened PC, point the PC's DNS at the hub (see [DEPLOY.md](DEPLOY.md)). A Standard user cannot change network settings without an administrator password.

## How to harden an Android phone (Level 1)

Device Owner can only be set on a phone with **no accounts on it** (a fresh or freshly reset phone). Follow `himaya-mobile/enroll-device-owner.bat` and [ANDROID.md](ANDROID.md). It cannot be added later without a reset, which is why it is an up-front choice.

## What you see when someone tampers

| Event in the dashboard | Meaning |
| --- | --- |
| "Himaya was stopped on this device" | The agent was closed or uninstalled on purpose (it says so as it exits). |
| "Went offline", then "Back online" | No check-in for 75 seconds. Could be a closed laptop or a dead battery, or the program was ended. |
| "A VPN was started" | Another VPN came up on the device (it can take over from Himaya's website filter). |
| "Himaya can't enforce a rule here" | Something Himaya relies on was switched off. On Android the message says what, for example the VPN or the device admin permission. |
| "Himaya was hardened on this PC" (green) | You ran `harden.ps1`. Good news, not a problem. |

## Limits, honestly

* No software on a child's own device can stop a determined, technical child. The goal is to stop the easy attacks and make the others noticeable.
* A hardened install lets a Standard user end the running program for up to 5 minutes. The hub shows it.
* The best protection is a child who knows why Himaya is there. Tell them.
