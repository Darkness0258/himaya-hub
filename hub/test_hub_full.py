"""Comprehensive test for Himaya Hub — REST + WebSocket broadcast + Command Queue."""
import asyncio
import json
import threading
import time
import requests
import uvicorn
import websockets

BASE = "http://127.0.0.1:8005"
WS_URL = "ws://127.0.0.1:8005/ws"


def run_server():
    import main
    uvicorn.run(main.app, host="127.0.0.1", port=8005, log_level="error")


async def async_ws_test():
    async with websockets.connect(WS_URL) as ws:
        # Receive snapshot on connect
        snapshot_raw = await ws.recv()
        snapshot = json.loads(snapshot_raw)
        assert snapshot["type"] == "snapshot"
        print("[PASS] WS received snapshot:", len(snapshot.get("devices", [])), "devices")

        # Now trigger an action via REST
        resp = requests.post(f"{BASE}/admin/phone-test/action", json={
            "action": "lock",
            "payload": {"reason": "bedtime"}
        }).json()
        assert resp["status"] == "dispatched"
        print("[PASS] REST lock dispatched")

        # Receive live event via WS
        event_raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
        event = json.loads(event_raw)
        assert event["device_id"] == "phone-test"
        assert event["type"] == "device_locked"
        print("[PASS] WS live broadcast received event:", event["type"])


def test_full():
    import database
    database.clear_all_data()

    # 1. Register device
    dev = requests.post(f"{BASE}/devices", json={
        "name": "Sarah's Tablet",
        "platform": "android",
        "device_id": "phone-test",
        "owner_type": "child"
    }).json()
    assert dev["device_id"] == "phone-test"
    print("[PASS] registered Sarah's Tablet")

    # 2. Heartbeat
    hb = requests.post(f"{BASE}/agents/phone-test/heartbeat", params={"ip": "192.168.1.100"}).json()
    assert hb["status"] == "ok"
    print("[PASS] heartbeat ok")

    # 3. Test WebSocket live feed
    asyncio.run(async_ws_test())

    # 4. Check queued commands for agent
    cmds = requests.get(f"{BASE}/agents/phone-test/commands").json()
    assert len(cmds["commands"]) == 1
    assert cmds["commands"][0]["action"] == "lock"
    print("[PASS] agent consumed queued command:", cmds["commands"][0]["action"])

    # 5. Subsequent queue read should be empty (FIFO consumed)
    cmds_after = requests.get(f"{BASE}/agents/phone-test/commands").json()
    assert len(cmds_after["commands"]) == 0
    print("[PASS] command queue drained successfully")

    print("\n>>> ALL FULL HUB + WEBSOCKET INTEGRATION TESTS PASSED <<<")


if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)
    test_full()
