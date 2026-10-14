"""Provides device triggers."""

from dataclasses import MISSING, fields

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode, ObjectSelectorField

from .codecs.models import BleAdvEncCmd
from .const import DOMAIN
from .device import BleAdvDevice
from .kaiyu_lights import BleAdvKaiyuController
from .learned_remote import BleAdvLearnedRemote

BYTE_SELECTOR = NumberSelector(NumberSelectorConfig(min=0, max=255, mode=NumberSelectorMode.BOX))
ENC_CMD_PARAMS = {f.name: (0 if f.default is MISSING else None) for f in fields(BleAdvEncCmd)}
ENC_CMD_SELECTOR = {f.name: ObjectSelectorField(selector=BYTE_SELECTOR, required=f.default is MISSING) for f in fields(BleAdvEncCmd)}


def is_learned_remote_device(hass: HomeAssistant, device_id: str) -> bool:
    """Return True if the device_id is a Learned Remote or a Kaiyu controller: no device triggers / actions, only standard entities."""
    return (
        (device_entry := dr.async_get(hass).async_get(device_id)) is not None
        and (entry := hass.config_entries.async_get_entry(device_entry.config_entry_id)) is not None
        and isinstance(getattr(entry, "runtime_data", None), BleAdvLearnedRemote | BleAdvKaiyuController)
    )


async def get_device_from_id(hass: HomeAssistant, device_id: str) -> BleAdvDevice:
    """Get BleAdvDevice from its device_id."""
    if (
        (device_entry := dr.async_get(hass).async_get(device_id)) is not None
        and (entry := hass.config_entries.async_get_entry(device_entry.config_entry_id)) is not None
        and (device := entry.runtime_data) is not None
    ):
        return device
    msg = f"No '{DOMAIN}' device with ID '{device_id}'"
    raise vol.Invalid(msg)
