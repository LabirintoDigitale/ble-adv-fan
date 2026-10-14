"""Presence tracker tests."""

# ruff: noqa: S101
from datetime import datetime, timedelta

from ble_adv_fan.presence import BleAdvPresenceTracker


def test_presence_record() -> None:
    """Test recording devices and their continuous presence."""
    now = datetime.now()
    tracker = BleAdvPresenceTracker(timedelta(minutes=10))
    tracker.record("aa:bb:cc:dd:ee:01", "hci/1", "AA-BB-CC-DD-EE-01", -60, now - timedelta(minutes=70))
    for minutes in range(65, -1, -5):
        tracker.record("AA:BB:CC:DD:EE:01", "esp/proxy", None, None, now - timedelta(minutes=minutes))
    tracker.record("AA:BB:CC:DD:EE:02", "hci/1", "Lamp", -70, now - timedelta(minutes=30))
    tracker.record("AA:BB:CC:DD:EE:02", "hci/1", None, None, now)
    assert len(tracker) == 2

    devs = tracker.present_since(timedelta(hours=1), now)
    assert [dev.address for dev in devs] == ["AA:BB:CC:DD:EE:01"]
    dev = devs[0]
    assert dev.name is None  # the name was only the address
    assert dev.rssi == -60
    assert dev.sources == {"hci/1", "esp/proxy"}
    assert dev.count == 15
    assert dev.first_seen == now - timedelta(minutes=70)

    devs = tracker.present_since(timedelta(minutes=20), now)
    assert [dev.address for dev in devs] == ["AA:BB:CC:DD:EE:01"]  # gap of 30 minutes: EE:02 presence restarted
    tracker.record("AA:BB:CC:DD:EE:02", "hci/1", None, None, now)
    assert tracker.present_since(timedelta(0), now)[1].name == "Lamp"


def test_presence_prune() -> None:
    """Test devices gone are pruned, and the max number of devices."""
    now = datetime.now()
    tracker = BleAdvPresenceTracker(timedelta(minutes=10), 2)
    tracker.record("01", "s", now=now - timedelta(minutes=20))
    tracker.record("02", "s", now=now)
    tracker.record("03", "s", now=now)  # 01 pruned to make room
    assert len(tracker) == 2
    tracker.record("04", "s", now=now)  # no room
    assert len(tracker) == 2
    assert [dev.address for dev in tracker.present_since(timedelta(0), now)] == ["02", "03"]
    tracker.prune(now + timedelta(minutes=11))
    assert len(tracker) == 0
    tracker.record("05", "s")
    tracker.prune()
    assert len(tracker) == 1
    assert tracker.present_since(timedelta(hours=1)) == []
