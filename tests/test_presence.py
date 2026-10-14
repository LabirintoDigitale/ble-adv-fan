"""Presence tracker tests."""

# ruff: noqa: S101
from datetime import datetime, timedelta

from ble_adv_fan.presence import BleAdvPresenceTracker


def test_presence_from_time_to_time() -> None:
    """Test a device sending a signal from time to time is present."""
    now = datetime.now()
    tracker = BleAdvPresenceTracker(timedelta(hours=1))
    # one signal every 25 minutes, over 75 minutes
    for minutes in (75, 50, 25, 0):
        tracker.record("aa:bb:cc:dd:ee:01", "hci/1", "AA-BB-CC-DD-EE-01", -60, now - timedelta(minutes=minutes))
    tracker.record("AA:BB:CC:DD:EE:01", "esp/proxy", None, None, now)  # same signal from another source
    # signals over 40 minutes only
    tracker.record("AA:BB:CC:DD:EE:02", "hci/1", "Lamp", -70, now - timedelta(minutes=50))
    tracker.record("AA:BB:CC:DD:EE:02", "hci/1", None, None, now - timedelta(minutes=10))
    # a single signal
    tracker.record("AA:BB:CC:DD:EE:03", "hci/1", None, None, now - timedelta(minutes=59))
    assert len(tracker) == 3

    devs = tracker.present_since(timedelta(hours=1), now)
    assert [dev.address for dev in devs] == ["AA:BB:CC:DD:EE:01"]
    dev = devs[0]
    assert dev.name is None  # the name was only the address
    assert dev.rssi == -60
    assert dev.sources == {"hci/1", "esp/proxy"}
    assert dev.count == 4
    assert dev.first_seen == now - timedelta(minutes=75)
    assert dev.last_seen == now

    assert [dev.address for dev in tracker.present_since(timedelta(minutes=30), now)] == ["AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02"]


def test_presence_gone_and_back() -> None:
    """Test a device silent for longer than the gap is gone, and its presence restarts when back."""
    now = datetime.now()
    tracker = BleAdvPresenceTracker(timedelta(hours=1))
    tracker.record("01", "hci/1", "Lamp", -70, now - timedelta(hours=3))
    tracker.record("01", "hci/1", None, None, now - timedelta(hours=2))
    tracker.record("01", "esp/proxy", None, None, now - timedelta(minutes=5))
    dev = tracker.present_since(timedelta(0), now)[0]
    assert (dev.name, dev.first_seen, dev.count, dev.sources) == ("Lamp", now - timedelta(minutes=5), 1, {"esp/proxy"})
    assert tracker.present_since(timedelta(0), now + timedelta(minutes=56)) == []  # silent for too long: gone


def test_presence_older_signal() -> None:
    """Test a signal older than the first one, known later (from the HA Bluetooth history)."""
    now = datetime.now()
    tracker = BleAdvPresenceTracker(timedelta(hours=1))
    tracker.record("01", "s", now=now - timedelta(minutes=10))
    tracker.record("01", "s", now=now)
    tracker.record("01", "s", now=now - timedelta(minutes=50))
    tracker.record("01", "s", now=now - timedelta(minutes=5))
    dev = tracker.present_since(timedelta(0), now)[0]
    assert (dev.first_seen, dev.last_seen, dev.count) == (now - timedelta(minutes=50), now, 2)
    tracker.record("01", "s", now=now - timedelta(hours=3))  # too old: ignored
    assert dev.first_seen == now - timedelta(minutes=50)


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
