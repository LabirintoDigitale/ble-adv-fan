"""send_command service tests."""

# ruff: noqa: S101
from unittest import mock

import pytest
import voluptuous as vol
from ble_adv_fan import async_setup_entry
from ble_adv_fan.codecs.models import BleAdvEncCmd
from ble_adv_fan.const import DOMAIN
from ble_adv_fan.coordinator import BleAdvCoordinator
from homeassistant.core import HomeAssistant

from .conftest import create_base_entry, get_device_entry_id_from_entry
from .test_init import BASE_CONF
from .test_learned_remote import LEARNED_CONF


@pytest.mark.usefixtures("coord")
async def test_send_command(hass: HomeAssistant) -> None:
    """Test sending a raw command to a device."""
    entry = await create_base_entry(hass, "dev_id", BASE_CONF)
    with mock.patch.object(hass.config_entries, "async_forward_entry_setups"):
        assert await async_setup_entry(hass, entry)
    device = entry.runtime_data
    device.apply_cmd = mock.AsyncMock()
    device_id = get_device_entry_id_from_entry(hass, entry)
    await hass.services.async_call(DOMAIN, "send_command", {"device_id": device_id, "cmd": 34, "arg0": "3"}, blocking=True)
    device.apply_cmd.assert_awaited_once_with(BleAdvEncCmd(34, 0, 3, 0, 0, 0, 0))
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "send_command", {"device_id": device_id, "cmd": 300}, blocking=True)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "send_command", {"device_id": "unknown", "cmd": 1}, blocking=True)


async def test_send_command_learned(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the service refuses the devices without codec."""
    entry = await create_base_entry(hass, "learned##id", LEARNED_CONF)
    with mock.patch.object(hass.config_entries, "async_forward_entry_setups"):
        assert await async_setup_entry(hass, entry)
    device_id = get_device_entry_id_from_entry(hass, entry)
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(DOMAIN, "send_command", {"device_id": device_id, "cmd": 1}, blocking=True)
    coord.remove_raw_listener(entry.runtime_data)
