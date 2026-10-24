"""The hub serves its own copy of the Windows agent (the Docker image only contains hub/)."""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "agent-windows" / "himaya_windows_agent.py"
SERVED = ROOT / "hub" / "himaya_windows_agent.py"


@pytest.mark.skipif(not SOURCE.is_file(), reason="running from the hub folder alone (e.g. inside the Docker image)")
def test_served_agent_is_identical_to_the_source_of_truth():
    """Fails when someone edits agent-windows/ and forgets: python tools/sync_agent.py"""
    assert SERVED.read_bytes().replace(b"\r\n", b"\n") == SOURCE.read_bytes().replace(b"\r\n", b"\n")


def test_served_agent_is_the_new_visible_agent():
    text = SERVED.read_text(encoding="utf-8")
    assert "class HubClient" in text and "pystray" in text
    assert "WindowStyle Hidden" not in text and "--hidden" not in text
