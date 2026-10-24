# Himaya Windows agent

`himaya_windows_agent.py` is the program that runs on a protected Windows PC. It is **always visible**: a "Himaya active" icon in the system tray (or a small window if the tray is unavailable). There is no hidden mode and no Quit entry.

## Install

Use the one-liner from the dashboard's **Add a device** page, in a normal PowerShell window (no Administrator needed). The installer explains what it will do, asks for consent and the pairing PIN, installs `requests`, `pillow` and `pystray` for the current user, puts the agent in `%LOCALAPPDATA%\HimayaAgent`, adds a Startup shortcut and starts it.

To run by hand (needs `agent_config.json` next to the script, which the installer writes):

```bash
python himaya_windows_agent.py --console     # logs on screen
python himaya_windows_agent.py --once        # contact the hub once, print the state, exit
```

## What it does

| Loop | Every | Does |
| --- | --- | --- |
| heartbeat | 20 s | Tells the hub it is online (with its IP and what it can enforce); receives the desired state (locked / paused / bedtime) and the screenshot interval |
| commands | 5 s | Messages, close an app, screenshot now, rule changes |
| enforce | 5 s | Re-locks while locked; applies or releases the internet pause |
| VPN guard | 45 s | Reports a new VPN adapter once |
| screenshots | the hub's setting | Sends a screenshot on the schedule (child PCs only) |

Lock and pause follow the hub's **state**, not one-off commands, so a missed command cannot leave the PC out of step.

## Enforcement and its limits

* **Lock:** `LockWorkStation()` repeatedly while locked.
* **Pause internet:** sets the per-user Windows proxy to a dead address (`127.0.0.1:9`) and restores the previous setting afterwards (the backup survives a crash). It covers browsers and most apps. The agent's own traffic ignores the proxy, so it can always be un-paused. Pointing the PC's DNS at the hub is stricter.
* **Website blocking:** a marked block in the hosts file. This needs the agent to run as Administrator; without it the agent says so and the hub DNS filter still works. The agent touches only its own `# HIMAYA BLOCKLIST` block and keeps the file's line endings.
* **Erase:** not available on Windows.
* **Tamper:** a user who can open Task Manager can end the process. The parent is told when the PC goes quiet. Use a standard (non-admin) child account.

## Uninstall

Run `uninstall.ps1` from the agent folder (the installer prints the command). It tells the hub, stops the agent, removes the startup shortcut, restores internet settings and removes the hosts block (the last needs Administrator).

## Files

* `agent_config.json`: hub addresses, device id and device key. Written by the installer. Not for sharing or committing.
* `agent.log`: rotating log.

The hub serves a copy of this file to new PCs from `hub/himaya_windows_agent.py`. **This folder is the source of truth**; after editing, run `python tools/sync_agent.py` (a test fails if they differ).
