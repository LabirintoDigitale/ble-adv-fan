"""Universal BLE Remote: replay raw BLE Advertisements learned from any remote."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.event import EventDeviceClass, EventEntity
from homeassistant.const import CONF_NAME
from homeassistant.helpers.device_registry import DeviceInfo

from .adapters import BleAdvQueueItem
from .codecs.models import BleAdvAdvertisement
from .const import CONF_KEY_ID, CONF_RAW, DOMAIN, LEARNED_EVENT_TYPE
from .coordinator import BleAdvCoordinator

_LOGGER = logging.getLogger(__name__)

LEARNED_REPEAT = 9
LEARNED_INTERVAL = 30
LEARNED_DURATION = 750
KEY_RX_GAP = timedelta(seconds=1)  # Advs of the same key received with less than this gap belong to the same press


async def async_send_raw(coordinator: BleAdvCoordinator, adapter_ids: list[str], queue_id: str, raw: bytes, repeat: int, interval: int) -> None:
    """Advertise a raw BLE ADV on the given adapters."""
    for adapter_id in adapter_ids:
        qi = BleAdvQueueItem(None, repeat, LEARNED_DURATION, interval, [raw], 4 * repeat * interval)
        await coordinator.advertise(adapter_id, queue_id, qi)


class BleAdvLearnedKey:
    """A key learned from a remote."""

    def __init__(self, key_id: str, name: str, raw: bytes) -> None:
        self.key_id: str = key_id
        self.name: str = name
        self.raw: bytes = raw
        self.adv: BleAdvAdvertisement = BleAdvAdvertisement.FromRaw(raw)
        self.last_rx: datetime | None = None

    @classmethod
    def from_conf(cls, conf: dict[str, Any]) -> BleAdvLearnedKey:
        """Build from its config."""
        return cls(conf[CONF_KEY_ID], conf[CONF_NAME], bytes.fromhex(conf[CONF_RAW]))


class BleAdvLearnedRemote:
    """A remote whose keys were learned: each key can be replayed, and is notified when received."""

    def __init__(
        self,
        coordinator: BleAdvCoordinator,
        unique_id: str,
        name: str,
        adapter_ids: list[str],
        keys: list[BleAdvLearnedKey],
        repeat: int = LEARNED_REPEAT,
        interval: int = LEARNED_INTERVAL,
    ) -> None:
        self.coordinator: BleAdvCoordinator = coordinator
        self.unique_id: str = unique_id
        self.name: str = name
        self.adapter_ids: list[str] = adapter_ids
        self.keys: list[BleAdvLearnedKey] = keys
        self.repeat: int = repeat
        self.interval: int = interval
        self._event_entity: BleAdvLearnedEvent | None = None
        self._entities: list[BleAdvLearnedButton | BleAdvLearnedEvent] = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(identifiers={(DOMAIN, self.unique_id)}, name=self.name, hw_version=", ".join(self.adapter_ids), model="Learned BLE Remote")

    @property
    def available(self) -> bool:
        """Return True if one of the adapters is available."""
        return any(adapter_id in self.coordinator.get_adapter_ids() for adapter_id in self.adapter_ids)

    def add_entity(self, ent: BleAdvLearnedButton | BleAdvLearnedEvent) -> None:
        """Add an entity to this remote."""
        self._entities.append(ent)
        if isinstance(ent, BleAdvLearnedEvent):
            self._event_entity = ent

    def update_availability(self) -> None:
        """Update availability of the entities."""
        for ent in self._entities:
            if ent.hass is not None:
                ent.async_write_ha_state()

    async def async_send_key(self, key: BleAdvLearnedKey) -> None:
        """Replay a key."""
        _LOGGER.info(f"[{self.name}] Sending key '{key.name}'")
        # Ignore our own advertisements if heard back by another adapter
        key.last_rx = datetime.now() + timedelta(milliseconds=self.repeat * self.interval)
        await async_send_raw(self.coordinator, self.adapter_ids, self.unique_id, key.raw, self.repeat, self.interval)

    def on_raw_adv(self, adapter_id: str, _: str, adv: BleAdvAdvertisement) -> None:
        """Trigger the event entity when a learned key is received."""
        if adapter_id not in self.adapter_ids:
            return
        now = datetime.now()
        for key in self.keys:
            if key.adv == adv:
                new_press = key.last_rx is None or (now - key.last_rx) > KEY_RX_GAP
                key.last_rx = now if key.last_rx is None else max(now, key.last_rx)
                if new_press and self._event_entity is not None:
                    self._event_entity.trigger_key(key, adapter_id)


class BleAdvLearnedButton(ButtonEntity):
    """Button replaying a learned key."""

    _attr_has_entity_name = True

    def __init__(self, remote: BleAdvLearnedRemote, key: BleAdvLearnedKey) -> None:
        self._remote: BleAdvLearnedRemote = remote
        self._key: BleAdvLearnedKey = key
        self._attr_device_info = remote.device_info
        self._attr_unique_id = f"{remote.unique_id}_key_{key.key_id}"
        self._attr_name = key.name
        remote.add_entity(self)

    @property
    def available(self) -> bool:
        """Return if available."""
        return self._remote.available

    async def async_press(self) -> None:
        """Replay the key."""
        await self._remote.async_send_key(self._key)


class BleAdvLearnedEvent(EventEntity):
    """Event triggered when a learned key is received from the original remote."""

    _attr_has_entity_name = True
    _attr_device_class = EventDeviceClass.BUTTON
    _attr_translation_key = LEARNED_EVENT_TYPE

    def __init__(self, remote: BleAdvLearnedRemote) -> None:
        self._remote: BleAdvLearnedRemote = remote
        self._attr_device_info = remote.device_info
        self._attr_unique_id = f"{remote.unique_id}_{LEARNED_EVENT_TYPE}"
        self._attr_event_types = [key.name for key in remote.keys]
        remote.add_entity(self)

    @property
    def available(self) -> bool:
        """Return if available."""
        return self._remote.available

    def trigger_key(self, key: BleAdvLearnedKey, adapter_id: str) -> None:
        """Trigger the event for a received key."""
        if self.hass is None:
            return
        self._trigger_event(key.name, {CONF_KEY_ID: key.key_id, "adapter_id": adapter_id})
        self.async_write_ha_state()
