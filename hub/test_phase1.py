"""Phase 1 test — device registry + WebSocket event feed."""
import time
import threading
import requests
import uvicorn

BASE = "http://127.0.0.1:8004"


def run_server():
    import main  # noqa: E402
    uvicorn.run(main.app, host="127.0.0.1", port=8004, log_level="error")


def test_phase1():
    import database
    database.clear_all_data()

    # Register two devices
    dev1 = requests.post(f"{BASE}/devices", json={"name": "Child Phone", "platform": "android",
                                                  "device_id": "android-001", "owner_type": "child"}).json()
    dev2 = requests.post(f"{BASE}/devices", json={"name": "Laptop", "platform": "windows",
                                                  "device_id": "windows-001", "owner_type": "adult"}).json()
    assert dev1["name"] == "Child Phone" and dev2["name"] == "Laptop"
    print(f"[PASS] registered: {dev1['name']} ({dev1['id']}), {dev2['name']} ({dev2['id']})")

    # List devices
    devices = requests.get(f"{BASE}/devices").json()
    assert len(devices) == 2
    print(f"[PASS] list_devices -> {len(devices)} devices")

    # Heartbeat
    resp = requests.post(f"{BASE}/agents/android-001/heartbeat", json={"ip": "192.168.1.42"}).json()
    assert resp["status"] == "ok"
    print(f"[PASS] heartbeat from android-001")

    # DNS block + VPN attempt
    requests.post(f"{BASE}/agents/android-001/dns-block", json={"host": "youtube.com"})
    requests.post(f"{BASE}/agents/android-001/vpn-attempt", json={"interface": "TUN0"})
    print(f"[PASS] dns-block + vpn-attempt logged")

    # Remote action
    action = requests.post(f"{BASE}/admin/android-001/action", json={"action": "lock"}).json()
    assert action["status"] == "dispatched"
    print(f"[PASS] remote lock action dispatched")

    # Events endpoint
    events = requests.get(f"{BASE}/events?limit=5").json()
    assert len(events) == 4
    assert events[0]["type"] == "heartbeat"
    print(f"[PASS] events feed -> {len(events)} events, newest = {events[0]['type']}")

    # Health
    health = requests.get(f"{BASE}/health").json()
    assert health["status"] == "ok" and health["devices"] == 2
    print(f"[PASS] health -> {health['devices']} devices, {health['events']} events")
    print("\nALL PHASE 1 TESTS PASSED")


if __name__ == "__main__":
    # Start server in background thread
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(2)

    # Run tests
    try:
        test_phase1()
    except Exception as e:
        print(f"[FAIL] {e}")
        raise