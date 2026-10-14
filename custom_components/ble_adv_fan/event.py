"""Event Handling."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .device import BleAdvDevice, BleAdvEvent
from .learned_remote import BleAdvLearnedEvent, BleAdvLearnedRemote


async def async_setup_entry(_: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Entry setup."""
    device: BleAdvDevice | BleAdvLearnedRemote = entry.runtime_data
    if isinstance(device, BleAdvLearnedRemote):
        async_add_entities([BleAdvLearnedEvent(device)], True)
    else:
        async_add_entities([BleAdvEvent(device)], True)
