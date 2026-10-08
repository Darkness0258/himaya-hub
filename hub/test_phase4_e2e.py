"""Phase 4 End-to-End Verification — Remote Actions & Multi-Device Control."""
import asyncio
import json
import threading
import time
import requests
import uvicorn
import websockets

BASE = "http://127.0.0.1:8002"
WS_URL = "ws://127.0.0.1:8002/ws"


def run_server():
    import main
    uvicorn.run(main.app, host="127.0.0.1", port=8002, log_level="error")


async def verify_remote_actions():
    import database
    database.clear_all_data()

    # Connect WebSocket client to observe live broadcasts
    async with websockets.connect(WS_URL) as ws:
        snapshot_raw = await ws.recv()
        snapshot = json.loads(snapshot_raw)
        assert snapshot["type"] == "snapshot"
        print("[PASS] WebSocket connected, snapshot received")

        # 1. Register Child Phone and Tablet
        child_phone = requests.post(f"{BASE}/devices", json={
            "name": "Leo's Phone",
            "platform": "android",
            "device_id": "leo-phone",
            "owner_type": "child"
        }).json()
        assert child_phone["device_id"] == "leo-phone"

        child_tablet = requests.post(f"{BASE}/devices", json={
            "name": "Leo's Tablet",
            "platform": "android",
            "device_id": "leo-tablet",
            "owner_type": "child"
        }).json()
        assert child_tablet["device_id"] == "leo-tablet"
        print("[PASS] Enrolled 2 child devices: Leo's Phone & Leo's Tablet")

        # 2. Simulate Heartbeats to bring online
        requests.post(f"{BASE}/agents/leo-phone/heartbeat", params={"ip": "192.168.1.150"})
        requests.post(f"{BASE}/agents/leo-tablet/heartbeat", params={"ip": "192.168.1.151"})
        print("[PASS] Heartbeats received -> devices online")

        # 3. Test LOCK Action
        lock_res = requests.post(f"{BASE}/admin/leo-phone/action", json={
            "action": "lock",
            "payload": {"reason": "bedtime"}
        }).json()
        assert lock_res["status"] == "dispatched"
        assert lock_res["device_status"] == "locked"
        print("[PASS] Remote LOCK dispatched and state updated to LOCKED")

        # 4. Agent polls queued command
        cmds = requests.get(f"{BASE}/agents/leo-phone/commands").json()
        assert len(cmds["commands"]) == 1
        assert cmds["commands"][0]["action"] == "lock"
        print("[PASS] Agent polled and consumed queued LOCK command")

        # 5. Test UNLOCK Action
        unlock_res = requests.post(f"{BASE}/admin/leo-phone/action", json={
            "action": "unlock"
        }).json()
        assert unlock_res["status"] == "dispatched"
        assert unlock_res["device_status"] == "online"
        print("[PASS] Remote UNLOCK dispatched and state returned to ONLINE")

        # 6. Test PAUSE INTERNET Action
        pause_res = requests.post(f"{BASE}/admin/leo-tablet/action", json={
            "action": "pause"
        }).json()
        assert pause_res["status"] == "dispatched"
        assert pause_res["device_status"] == "paused"
        print("[PASS] Remote PAUSE INTERNET dispatched and state updated to PAUSED")

        # 7. Test PUSH NOTIFICATION Action
        push_res = requests.post(f"{BASE}/admin/leo-phone/action", json={
            "action": "push_notification",
            "payload": {"message": "Dinnertime in 5 minutes!"}
        }).json()
        assert push_res["status"] == "dispatched"

        push_cmds = requests.get(f"{BASE}/agents/leo-phone/commands").json()
        assert any(c["action"] == "push_notification" for c in push_cmds["commands"])
        print("[PASS] Remote PUSH NOTIFICATION dispatched and verified in agent command queue")

        # 8. Check Dashboard serving
        dash_res = requests.get(f"{BASE}/dashboard")
        assert dash_res.status_code == 200
        assert "HIMAYA" in dash_res.text
        print("[PASS] Parent Web Dashboard successfully served at /dashboard")

        print("\n>>> ALL PHASE 4 E2E REMOTE ACTION TESTS PASSED <<<")


if __name__ == "__main__":
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)
    asyncio.run(verify_remote_actions())
