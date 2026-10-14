"""Track the Bluetooth devices seen around Home Assistant and since when they are present."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

PRESENCE_GAP = timedelta(hours=1)  # Silent for longer than this: considered gone, its presence restarts on next signal
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
    """Record the Bluetooth devices seen and compute their presence.

    Bluetooth devices only send a signal from time to time: a device is present as long as it is
    not silent for longer than the gap, and present since its first signal after such a silence.
    """

    def __init__(self, gap: timedelta = PRESENCE_GAP, max_devices: int = PRESENCE_MAX_DEVICES) -> None:
        self.started: datetime = datetime.now()
        self.gap: timedelta = gap
        self._max_devices: int = max_devices
        self._devices: dict[str, BtSeenDevice] = {}

    def __len__(self) -> int:
        return len(self._devices)

    def record(self, address: str, source: str, name: str | None = None, rssi: int | None = None, now: datetime | None = None) -> None:
        """Record a signal of a device, received by the given source at the given time (can be in the past)."""
        now = now if now is not None else datetime.now()
        address = address.upper()
        dev = self._devices.get(address)
        if dev is None:
            if len(self._devices) >= self._max_devices:
                self.prune(now)
                if len(self._devices) >= self._max_devices:
                    return
            dev = BtSeenDevice(address, now, now, count=1)
            self._devices[address] = dev
        elif (now - dev.last_seen) > self.gap:
            # Gone and back: its presence restarts, its name is kept
            dev.first_seen = now
            dev.last_seen = now
            dev.count = 1
            dev.sources = set()
        elif now > dev.last_seen:
            dev.last_seen = now
            dev.count += 1
        elif now < dev.first_seen and (dev.first_seen - now) <= self.gap:
            dev.first_seen = now  # an older signal, known only now
        if name and name.replace("-", ":").upper() != address:
            dev.name = name
        if rssi is not None:
            dev.rssi = rssi
        dev.sources.add(source)

    def prune(self, now: datetime | None = None) -> None:
        """Remove the devices silent for longer than the gap."""
        now = now if now is not None else datetime.now()
        self._devices = {addr: dev for addr, dev in self._devices.items() if (now - dev.last_seen) <= self.gap}

    def present_since(self, min_duration: timedelta, now: datetime | None = None) -> list[BtSeenDevice]:
        """List the devices still present that sent signals over at least min_duration, oldest first."""
        self.prune(now)
        return sorted((dev for dev in self._devices.values() if (dev.last_seen - dev.first_seen) >= min_duration), key=lambda dev: dev.first_seen)
