"""Track the Bluetooth devices seen around Home Assistant and since when they are continuously present."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

PRESENCE_GAP = timedelta(minutes=10)  # Not seen for longer than this: considered gone, its presence restarts on next sight
PRESENCE_MAX_DEVICES = 5000


@dataclass
class BtSeenDevice:
    """A Bluetooth device seen around."""

    address: str
    first_seen: datetime
    last_seen: datetime
    name: str | None = None
    rssi: int | None = None
    count: int = 0
    sources: set[str] = field(default_factory=set)


class BleAdvPresenceTracker:
    """Record the Bluetooth devices seen and compute their continuous presence."""

    def __init__(self, gap: timedelta = PRESENCE_GAP, max_devices: int = PRESENCE_MAX_DEVICES) -> None:
        self.started: datetime = datetime.now()
        self._gap: timedelta = gap
        self._max_devices: int = max_devices
        self._devices: dict[str, BtSeenDevice] = {}

    def __len__(self) -> int:
        return len(self._devices)

    def record(self, address: str, source: str, name: str | None = None, rssi: int | None = None, now: datetime | None = None) -> None:
        """Record a device seen by the given source."""
        now = now if now is not None else datetime.now()
        address = address.upper()
        dev = self._devices.get(address)
        if dev is None:
            if len(self._devices) >= self._max_devices:
                self.prune(now)
                if len(self._devices) >= self._max_devices:
                    return
            dev = BtSeenDevice(address, now, now)
            self._devices[address] = dev
        elif (now - dev.last_seen) > self._gap:
            # Gone and back: its presence restarts, its name is kept
            dev.first_seen = now
            dev.count = 0
            dev.sources = set()
        dev.last_seen = now
        dev.count += 1
        if name and name.replace("-", ":").upper() != address:
            dev.name = name
        if rssi is not None:
            dev.rssi = rssi
        dev.sources.add(source)

    def prune(self, now: datetime | None = None) -> None:
        """Remove the devices not seen for longer than the gap."""
        now = now if now is not None else datetime.now()
        self._devices = {addr: dev for addr, dev in self._devices.items() if (now - dev.last_seen) <= self._gap}

    def present_since(self, min_duration: timedelta, now: datetime | None = None) -> list[BtSeenDevice]:
        """List the devices currently present and continuously seen for at least min_duration, oldest first."""
        now = now if now is not None else datetime.now()
        self.prune(now)
        return sorted((dev for dev in self._devices.values() if (now - dev.first_seen) >= min_duration), key=lambda dev: dev.first_seen)
