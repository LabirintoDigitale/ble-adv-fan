"""Button Handling: keys of the Learned Remotes."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .learned_remote import BleAdvLearnedButton, BleAdvLearnedRemote


async def async_setup_entry(_: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Entry setup."""
    remote: BleAdvLearnedRemote = entry.runtime_data
    async_add_entities([BleAdvLearnedButton(remote, key) for key in remote.keys], True)
