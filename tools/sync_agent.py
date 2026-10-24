#!/usr/bin/env python3
"""Keep the hub's served copy of the Windows agent identical to the source of truth.

Source of truth : agent-windows/himaya_windows_agent.py
Served by the hub: hub/himaya_windows_agent.py  (it must live inside hub/ so the Docker image
                   built from the ./hub folder can serve it to new PCs)

    python tools/sync_agent.py          copy source -> hub
    python tools/sync_agent.py --check  exit 1 if they differ (used by the tests / CI)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "agent-windows" / "himaya_windows_agent.py"
TARGET = ROOT / "hub" / "himaya_windows_agent.py"


def normalise(data: bytes) -> bytes:
    return data.replace(b"\r\n", b"\n")


def main() -> int:
    if not SOURCE.is_file():
        print(f"missing {SOURCE}", file=sys.stderr)
        return 2
    wanted = normalise(SOURCE.read_bytes())
    current = normalise(TARGET.read_bytes()) if TARGET.is_file() else None
    if "--check" in sys.argv:
        if current == wanted:
            print("agent copies are in sync")
            return 0
        print("hub/himaya_windows_agent.py differs from agent-windows/himaya_windows_agent.py - run: python tools/sync_agent.py", file=sys.stderr)
        return 1
    if current == wanted:
        print("already in sync")
        return 0
    TARGET.write_bytes(wanted)
    print(f"copied {SOURCE.relative_to(ROOT)} -> {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
