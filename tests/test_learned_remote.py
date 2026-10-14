"""Universal BLE Remote tests."""

# ruff: noqa: S101
import asyncio
from datetime import datetime, timedelta
from unittest import mock

from ble_adv_fan import async_migrate_entry, async_setup_entry, async_unload_entry
from ble_adv_fan.button import async_setup_entry as button_setup_entry
from ble_adv_fan.codecs.models import BleAdvAdvertisement
from ble_adv_fan.const import (
    CONF_ADAPTER_IDS,
    CONF_ENTRY_TYPE,
    CONF_INTERVAL,
    CONF_KEY_ID,
    CONF_KEYS,
    CONF_RAW,
    CONF_REPEATS,
    CONF_TECHNICAL,
    DOMAIN,
    ENTRY_TYPE_LEARNED,
    LEARNED_PLATFORMS,
)
from ble_adv_fan.coordinator import BleAdvCoordinator
from ble_adv_fan.device_action import async_get_actions
from ble_adv_fan.device_trigger import async_get_triggers
from ble_adv_fan.event import async_setup_entry as event_setup_entry
from ble_adv_fan.helpers import is_learned_remote_device
from ble_adv_fan.learned_remote import BleAdvLearnedButton, BleAdvLearnedEvent, BleAdvLearnedKey, BleAdvLearnedRemote
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant

from .conftest import MockEspProxy, create_base_entry, get_device_entry_id_from_entry

ADV_ON = BleAdvAdvertisement(0xFF, b"\xf0\x08remote_on", 0x1A)
ADV_OFF = BleAdvAdvertisement(0xFF, b"\xf0\x08remote_off", 0x1A)

LEARNED_CONF = {
    CONF_ENTRY_TYPE: ENTRY_TYPE_LEARNED,
    CONF_TECHNICAL: {CONF_ADAPTER_IDS: ["esp/test"], CONF_REPEATS: 2, CONF_INTERVAL: 20},
    CONF_KEYS: [
        {CONF_KEY_ID: "k1", CONF_NAME: "On", CONF_RAW: ADV_ON.to_raw().hex().upper()},
        {CONF_KEY_ID: "k2", CONF_NAME: "Off", CONF_RAW: ADV_OFF.to_raw().hex().upper()},
    ],
}


def _remote(coord: BleAdvCoordinator) -> BleAdvLearnedRemote:
    keys = [BleAdvLearnedKey.from_conf(key) for key in LEARNED_CONF[CONF_KEYS]]
    return BleAdvLearnedRemote(coord, "learned##id", "My Remote", ["esp/test"], keys, 2, 20)


async def test_learned_remote_send(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the replay of a key."""
    remote = _remote(coord)
    assert not remote.available
    proxy = MockEspProxy(hass, "test")
    await proxy.setup()
    assert remote.available
    assert remote.device_info["name"] == "My Remote"
    await remote.async_send_key(remote.keys[0])
    await coord.bt_managers[1].adapters["esp/test"].drain()
    assert proxy.get_adv_calls() == [{"raw": ADV_ON.to_raw().hex()}]


async def test_learned_remote_recv(coord: BleAdvCoordinator) -> None:
    """Test the event triggered when a key is received from the original remote."""
    remote = _remote(coord)
    event = BleAdvLearnedEvent(remote)
    assert event.event_types == ["On", "Off"]
    event.trigger_key = mock.MagicMock()
    coord.add_raw_listener(remote)

    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())
    event.trigger_key.assert_called_once_with(remote.keys[0], "esp/test")
    event.trigger_key.reset_mock()
    # repeats of the same press
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())
    await coord.handle_raw_adv("esp/other", "11:22:33:44:55:66", ADV_OFF.to_raw())
    event.trigger_key.assert_not_called()
    # new press after the gap
    remote.keys[0].last_rx = datetime.now() - timedelta(seconds=2)
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())
    event.trigger_key.assert_called_once_with(remote.keys[0], "esp/test")
    event.trigger_key.reset_mock()
    # own advertisement heard back: ignored
    coord.advertise = mock.AsyncMock()
    await remote.async_send_key(remote.keys[1])
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_OFF.to_raw())
    event.trigger_key.assert_not_called()

    coord.remove_raw_listener(remote)
    remote.keys[0].last_rx = None
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())
    event.trigger_key.assert_not_called()


async def test_learned_entities(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the button and event entities."""
    remote = _remote(coord)
    button = BleAdvLearnedButton(remote, remote.keys[1])
    assert button.unique_id == "learned##id_key_k2"
    assert button.name == "Off"
    assert not button.available
    remote.async_send_key = mock.AsyncMock()
    await button.async_press()
    remote.async_send_key.assert_awaited_once_with(remote.keys[1])

    event = BleAdvLearnedEvent(remote)
    assert event.unique_id == "learned##id_learned_event"
    assert not event.available
    event.trigger_key(remote.keys[0], "esp/test")  # not added to hass: ignored
    event.hass = hass
    event.entity_id = "event.my_remote_key_received"
    event.async_write_ha_state = mock.MagicMock()
    event.trigger_key(remote.keys[0], "esp/test")
    event.async_write_ha_state.assert_called_once()
    assert event.state_attributes == {"event_type": "On", CONF_KEY_ID: "k1", "adapter_id": "esp/test"}

    button.hass = hass
    button.async_write_ha_state = mock.MagicMock()
    remote.update_availability()
    button.async_write_ha_state.assert_called_once()
    event.async_write_ha_state.assert_called()


async def test_learned_entry(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the setup / unload of a Learned Remote entry and its platforms."""
    entry = await create_base_entry(hass, "learned##id", LEARNED_CONF)
    assert await async_migrate_entry(hass, entry)
    with mock.patch.object(hass.config_entries, "async_forward_entry_setups") as fwd:
        assert await async_setup_entry(hass, entry)
        fwd.assert_awaited_once_with(entry, LEARNED_PLATFORMS)
    remote = entry.runtime_data
    assert isinstance(remote, BleAdvLearnedRemote)
    assert remote.adapter_ids == ["esp/test"]
    assert [key.name for key in remote.keys] == ["On", "Off"]
    assert remote in coord._raw_listeners  # noqa: SLF001

    add_ents = mock.MagicMock()
    await button_setup_entry(hass, entry, add_ents)
    assert [ent.name for ent in add_ents.call_args[0][0]] == ["On", "Off"]
    add_ents = mock.MagicMock()
    await event_setup_entry(hass, entry, add_ents)
    assert isinstance(add_ents.call_args[0][0][0], BleAdvLearnedEvent)

    dr_mock = mock.MagicMock()
    dr_mock.async_get.return_value.config_entry_id = entry.entry_id
    with mock.patch("ble_adv_fan.helpers.dr.async_get", return_value=dr_mock):
        assert is_learned_remote_device(hass, "dev_id")
        assert await async_get_triggers(hass, "dev_id") == []
        assert await async_get_actions(hass, "dev_id") == []

    with mock.patch.object(hass.config_entries, "async_unload_platforms", return_value=True) as unload:
        assert await async_unload_entry(hass, entry)
        unload.assert_awaited_once_with(entry, LEARNED_PLATFORMS)
    assert remote not in coord._raw_listeners  # noqa: SLF001


async def test_not_learned_device(hass: HomeAssistant) -> None:
    """Test a standard device is not a learned remote."""
    entry = await create_base_entry(hass, "dev", {})
    assert not is_learned_remote_device(hass, get_device_entry_id_from_entry(hass, entry))
    assert not is_learned_remote_device(hass, "unknown")


async def test_raw_capture(coord: BleAdvCoordinator) -> None:
    """Test the raw capture and the presence recording of the coordinator."""
    clbk = mock.MagicMock()
    coord.start_raw_capture(clbk, 0.1)
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())  # not de-duplicated
    assert clbk.call_count == 2
    clbk.assert_called_with("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw(), ADV_ON)
    await asyncio.sleep(0.15)
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())  # expired
    assert clbk.call_count == 2
    coord.start_raw_capture(clbk, 10)
    coord.stop_raw_capture(clbk)
    coord.stop_raw_capture(clbk)
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", ADV_ON.to_raw())
    assert clbk.call_count == 2
    assert [dev.address for dev in coord.presence.present_since(timedelta(0))] == ["11:22:33:44:55:66"]


async def test_ha_bluetooth(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test following the HA Bluetooth integration."""
    assert not coord.ensure_ha_bluetooth()
    hass.config.components.add("bluetooth")
    with mock.patch("homeassistant.components.bluetooth.async_register_callback", side_effect=Exception("not ready")):
        assert not coord.ensure_ha_bluetooth()
    cancel = mock.MagicMock()
    with mock.patch("homeassistant.components.bluetooth.async_register_callback", return_value=cancel) as reg:
        assert coord.ensure_ha_bluetooth()
        assert coord.ensure_ha_bluetooth()
        reg.assert_called_once()
        on_adv = reg.call_args[0][1]
    service_info = mock.MagicMock()
    service_info.address = "AA:BB:CC:DD:EE:FF"
    service_info.source = "hci0"
    service_info.name = "Sensor"
    service_info.rssi = -50
    on_adv(service_info, None)
    devs = coord.presence.present_since(timedelta(0))
    assert [(dev.address, dev.name, dev.rssi, dev.sources) for dev in devs] == [("AA:BB:CC:DD:EE:FF", "Sensor", -50, {"hci0"})]
    await coord.async_final()
    cancel.assert_called_once()


async def test_adapter_change_availability(coord: BleAdvCoordinator) -> None:
    """Test the raw listeners are notified of the adapter changes."""
    listener = mock.MagicMock()
    coord.add_raw_listener(listener)
    await coord.on_adapter_change("esp/test", True)
    listener.update_availability.assert_called_once()
    assert DOMAIN == "ble_adv_fan"
