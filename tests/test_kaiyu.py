"""Kaiyu LEGO light controller tests."""

# ruff: noqa: S101
import asyncio
from unittest import mock

import pytest
from ble_adv_fan import async_migrate_entry, async_setup_entry, async_unload_entry, entry_platforms
from ble_adv_fan.adapters import BleAdvAdapter
from ble_adv_fan.codecs.models import BleAdvAdvertisement
from ble_adv_fan.config_flow import BleAdvConfigFlow, BleAdvKaiyuProgress
from ble_adv_fan.const import (
    CONF_ADAPTER_IDS,
    CONF_COMPANY,
    CONF_ENTRY_TYPE,
    CONF_INTERVAL,
    CONF_REPEATS,
    CONF_TECHNICAL,
    ENTRY_TYPE_KAIYU,
    KAIYU_PLATFORMS,
)
from ble_adv_fan.coordinator import BleAdvCoordinator
from ble_adv_fan.helpers import is_learned_remote_device
from ble_adv_fan.kaiyu import (
    DEFAULT_COMPANY,
    MODE_ALL,
    MODE_LINES,
    kaiyu_build_adv,
    kaiyu_decode,
    kaiyu_encode,
    kaiyu_parse_adv,
    mk_crypt,
    mk_decrypt,
)
from ble_adv_fan.kaiyu_lights import BleAdvKaiyuController, BleAdvKaiyuLight
from ble_adv_fan.light import async_setup_entry as light_setup_entry
from homeassistant.config_entries import SOURCE_RECONFIGURE
from homeassistant.const import CONF_DEVICE, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MockEspProxy, create_base_entry

# Packets sent by the Kaiyu phone app to a real controller
ALL_ON = "0201021BFF00C26DB643CF7E8F4711B0B71BCFA33A38C408CABF42791A68A5"
ALL_OFF = "0201021BFF00C26DB643CF7E8F4711B0B71BCF5C785B4647C372775B36A48A"
LINE_1 = "0201021BFF00C26DB643CF7E8F4711E51D1BCFD63B17E76B5CAA1702C955B3"
LINES_1_2 = "0201021BFF00C26DB643CF7E8F4711E51D1BCF24BEF45B158A79DE8F800C33"
LINE_12 = "0201021BFF00C26DB643CF7E8F4711E51D1BCFB055EA62B2A45F01815CB869"
DEVICE_ID = bytes([0xE5, 0x77])

KAIYU_CONF = {
    CONF_ENTRY_TYPE: ENTRY_TYPE_KAIYU,
    CONF_COMPANY: "00C2",
    CONF_DEVICE: "E577",
    CONF_TECHNICAL: {CONF_ADAPTER_IDS: ["esp/test"], CONF_REPEATS: 2, CONF_INTERVAL: 20},
}


def _adv(hexraw: str) -> BleAdvAdvertisement:
    return BleAdvAdvertisement.FromRaw(bytes.fromhex(hexraw))


def _on_lines(hexraw: str) -> list[int]:
    parsed = kaiyu_parse_adv(_adv(hexraw).raw)
    assert parsed is not None
    return [i + 1 for i, on in enumerate(parsed[1].lines) if on]


def test_decode_app_packets() -> None:
    """Test the decoding of the packets of the phone app."""
    assert _on_lines(ALL_ON) == list(range(1, 13))
    assert _on_lines(ALL_OFF) == []
    assert _on_lines(LINE_1) == [1]
    assert _on_lines(LINES_1_2) == [1, 2]
    assert _on_lines(LINE_12) == [12]
    company, cmd = kaiyu_parse_adv(_adv(ALL_ON).raw)  # type: ignore[misc]
    assert (company, cmd.mode, cmd.device_id) == (DEFAULT_COMPANY, MODE_ALL, DEVICE_ID)
    assert kaiyu_parse_adv(_adv(LINE_1).raw)[1].mode == MODE_LINES  # type: ignore[index]


@pytest.mark.parametrize("hexraw", [ALL_ON, ALL_OFF, LINE_1, LINES_1_2, LINE_12])
def test_encode_as_app(hexraw: str) -> None:
    """Test the encoding gives exactly the packets of the phone app with the same seed."""
    raw = bytes.fromhex(hexraw)
    payload = mk_decrypt(raw[7:])
    assert payload is not None
    cmd = kaiyu_decode(payload)
    assert cmd is not None
    lines = [bool(on) for on in cmd.lines]
    assert kaiyu_build_adv(DEFAULT_COMPANY, kaiyu_encode(cmd.mode, cmd.device_id, lines, payload[10] or 256)) == raw


def test_encode_random_seed() -> None:
    """Test any combination can be encoded and decoded back."""
    lines = [i in (0, 4, 11) for i in range(12)]
    for _ in range(50):
        raw = kaiyu_build_adv(DEFAULT_COMPANY, kaiyu_encode(MODE_LINES, DEVICE_ID, lines))
        parsed = kaiyu_parse_adv(BleAdvAdvertisement.FromRaw(raw).raw)
        assert parsed is not None
        assert parsed[1].lines == lines


def test_invalid_packets() -> None:
    """Test invalid packets are not decoded."""
    telegram = bytearray(bytes.fromhex(LINE_1)[7:])
    assert mk_decrypt(bytes(telegram[:10])) is None
    assert mk_decrypt(bytes(10) + bytes(telegram[10:])) is None
    telegram[-1] ^= 0xFF
    assert mk_decrypt(bytes(telegram)) is None  # bad CRC
    payload = bytearray(kaiyu_encode(MODE_LINES, DEVICE_ID, [True] * 12, 5))
    assert kaiyu_decode(bytes(payload[:5])) is None
    payload[9] ^= 1
    assert kaiyu_decode(bytes(payload)) is None  # bad checksum
    assert kaiyu_parse_adv(bytes([0x00, 0xC2]) + mk_crypt(bytes(payload))) is None
    assert kaiyu_parse_adv(bytes(26)) is None
    unknown = bytearray(kaiyu_encode(MODE_LINES, DEVICE_ID, [True] * 12, 5))
    cmd = kaiyu_decode(bytes(unknown))
    assert cmd is not None
    unknown[4] = (unknown[4] + 0x20) & 0xFF  # output 1 value 4: unknown
    unknown[9] = (unknown[9] + 0x20) & 0xFF
    cmd = kaiyu_decode(bytes(unknown))
    assert cmd is not None
    assert cmd.lines[0] is None


def _controller(coord: BleAdvCoordinator) -> BleAdvKaiyuController:
    return BleAdvKaiyuController(coord, "kaiyu##00C2E577", "Lego", ["esp/test"], DEFAULT_COMPANY, DEVICE_ID, 2, 20)


async def test_controller_send(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the outputs commands sent."""
    proxy = MockEspProxy(hass, "test")
    await proxy.setup()
    ctrl = _controller(coord)
    assert ctrl.available
    assert ctrl.device_info["model_id"] == "0x00C2 / 0xE577"
    lights = [BleAdvKaiyuLight(ctrl, None), *(BleAdvKaiyuLight(ctrl, i) for i in range(12))]
    assert lights[1].unique_id == "kaiyu##00C2E577_line_1"
    assert lights[1].translation_placeholders == {"line": "1"}
    assert lights[0].unique_id == "kaiyu##00C2E577_all"
    assert not lights[0].is_on

    await lights[5].async_turn_on()
    await coord.bt_managers[1].adapters["esp/test"].drain()
    calls = proxy.get_adv_calls()
    assert len(calls) == 1
    parsed = kaiyu_parse_adv(BleAdvAdvertisement.FromRaw(bytes.fromhex(calls[0]["raw"])).raw)
    assert parsed is not None
    assert parsed[1].mode == MODE_LINES
    assert [i + 1 for i, on in enumerate(parsed[1].lines) if on] == [5]
    assert lights[5].is_on
    assert lights[0].is_on
    assert not lights[1].is_on

    await lights[0].async_turn_on()
    await coord.bt_managers[1].adapters["esp/test"].drain()
    parsed = kaiyu_parse_adv(BleAdvAdvertisement.FromRaw(bytes.fromhex(proxy.get_adv_calls()[0]["raw"])).raw)
    assert parsed is not None
    assert (parsed[1].mode, parsed[1].lines) == (MODE_ALL, [True] * 12)
    await lights[0].async_turn_off()
    await lights[2].async_turn_off()
    assert ctrl.values == [1] * 12
    await coord.bt_managers[1].adapters["esp/test"].drain()


async def test_controller_follows_app(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the outputs follow the commands of the phone app."""
    ctrl = _controller(coord)
    light = BleAdvKaiyuLight(ctrl, 0)
    light.hass = hass
    light.entity_id = "light.lego_output_1"
    light.async_write_ha_state = mock.MagicMock()
    coord.add_raw_listener(ctrl)
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", bytes.fromhex(LINE_1))
    assert ctrl.values == [2] + [1] * 11
    light.async_write_ha_state.assert_called_once()
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", bytes.fromhex(LINE_1))  # no change
    light.async_write_ha_state.assert_called_once()
    await coord.handle_raw_adv("esp/other", "11:22:33:44:55:67", bytes.fromhex(ALL_ON))  # other adapter
    other_id = kaiyu_build_adv(DEFAULT_COMPANY, kaiyu_encode(MODE_ALL, bytes([1, 2]), [True] * 12))
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:68", other_id)  # other controller
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:69", bytes.fromhex("020106030201A20C1601A200BFE48D9CD6AE5FF1"))
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:6A", bytes.fromhex("0201021BFF00C2") + bytes(24))
    assert ctrl.values == [2] + [1] * 11
    ctrl.update_availability()
    assert light.async_write_ha_state.call_count == 2
    coord.remove_raw_listener(ctrl)


async def test_light_restore(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the outputs state is restored."""
    ctrl = _controller(coord)
    light = BleAdvKaiyuLight(ctrl, 3)
    light.hass = hass
    last = mock.MagicMock()
    last.state = "on"
    with mock.patch.object(BleAdvKaiyuLight, "async_get_last_state", return_value=last):
        await light.async_added_to_hass()
    assert ctrl.values[3] == 2
    all_light = BleAdvKaiyuLight(ctrl, None)
    all_light.hass = hass
    with mock.patch.object(BleAdvKaiyuLight, "async_get_last_state", return_value=last):
        await all_light.async_added_to_hass()
    assert ctrl.values.count(2) == 1


async def test_kaiyu_entry(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the setup / unload of a Kaiyu entry."""
    entry = await create_base_entry(hass, "kaiyu##00C2E577", KAIYU_CONF)
    assert await async_migrate_entry(hass, entry)
    assert entry_platforms(entry) == KAIYU_PLATFORMS
    with mock.patch.object(hass.config_entries, "async_forward_entry_setups") as fwd:
        assert await async_setup_entry(hass, entry)
        fwd.assert_awaited_once_with(entry, KAIYU_PLATFORMS)
    ctrl = entry.runtime_data
    assert isinstance(ctrl, BleAdvKaiyuController)
    assert (ctrl.company, ctrl.device_id, ctrl.repeat, ctrl.interval) == (DEFAULT_COMPANY, DEVICE_ID, 2, 20)
    add_ents = mock.MagicMock()
    await light_setup_entry(hass, entry, add_ents)
    assert len(add_ents.call_args[0][0]) == 13
    dr_mock = mock.MagicMock()
    dr_mock.async_get.return_value.config_entry_id = entry.entry_id
    with mock.patch("ble_adv_fan.helpers.dr.async_get", return_value=dr_mock):
        assert is_learned_remote_device(hass, "dev_id")
    with mock.patch.object(hass.config_entries, "async_unload_platforms", return_value=True) as unload:
        assert await async_unload_entry(hass, entry)
        unload.assert_awaited_once_with(entry, KAIYU_PLATFORMS)
    assert ctrl not in coord._raw_listeners  # noqa: SLF001


def _flow(hass: HomeAssistant, coord: BleAdvCoordinator) -> BleAdvConfigFlow:
    flow = BleAdvConfigFlow()
    flow.hass = hass
    flow.coordinator = coord
    flow.context = {}
    return flow


async def _wait_done(flow: BleAdvConfigFlow) -> dict:
    for _ in range(100):
        res = await flow.async_step_kaiyu()
        if res["type"] != FlowResultType.SHOW_PROGRESS:
            return res
        await asyncio.sleep(0.05)
    raise AssertionError("Progress never ended")


async def test_kaiyu_flow(hass: HomeAssistant, coord: BleAdvCoordinator, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the Kaiyu config flow: listening, manual input, creation."""
    monkeypatch.setattr(BleAdvAdapter, "MAX_ADV_WAIT", 3.0)
    await MockEspProxy(hass, "test").setup()
    flow = _flow(hass, coord)
    res = await flow.async_step_user()
    assert "kaiyu" in res["menu_options"]

    # Nothing received
    flow._progress = BleAdvKaiyuProgress(flow, "kaiyu", 0.2)  # noqa: SLF001
    res = await _wait_done(flow)
    assert res["step_id"] == "kaiyu_none"
    res = await flow.async_step_kaiyu_none()
    assert res["menu_options"] == ["kaiyu", "kaiyu_manual"]

    # App command received
    flow._progress = BleAdvKaiyuProgress(flow, "kaiyu", 5)  # noqa: SLF001
    res = await flow.async_step_kaiyu()
    assert res["progress_action"] == "kaiyu_wait"
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", bytes.fromhex("020106030201A20C1601A200BFE48D9CD6AE5FF1"))
    await coord.handle_raw_adv("esp/test", "11:22:33:44:55:66", bytes.fromhex(LINE_12))
    res = await _wait_done(flow)
    assert res["step_id"] == "kaiyu_found"
    res = await flow.async_step_kaiyu_found()
    assert res["description_placeholders"] == {"company": "0x00C2", "id": "0xE577"}
    res = await flow.async_step_kaiyu_found({CONF_NAME: "Lego", CONF_ADAPTER_IDS: []})
    assert res["errors"] == {"base": "missing_adapter"}
    res = await flow.async_step_kaiyu_found({CONF_NAME: "Lego", CONF_ADAPTER_IDS: ["esp/test"]})
    assert res["type"] == FlowResultType.CREATE_ENTRY
    assert res["data"] == {
        CONF_ENTRY_TYPE: ENTRY_TYPE_KAIYU,
        CONF_COMPANY: "00C2",
        CONF_DEVICE: "E577",
        CONF_TECHNICAL: {CONF_ADAPTER_IDS: ["esp/test"], CONF_REPEATS: 9, CONF_INTERVAL: 30},
    }
    assert flow.unique_id == "kaiyu##00C2E577"

    # Manual input
    flow = _flow(hass, coord)
    res = await flow.async_step_kaiyu_manual()
    assert res["step_id"] == "kaiyu_manual"
    res = await flow.async_step_kaiyu_manual({CONF_COMPANY: "00C2", CONF_DEVICE: "zz"})
    assert res["errors"] == {"base": "invalid_kaiyu_id"}
    res = await flow.async_step_kaiyu_manual({CONF_COMPANY: "00C2", CONF_DEVICE: "1234"})
    assert res["step_id"] == "kaiyu_found"
    assert res["description_placeholders"] == {"company": "0x00C2", "id": "0x1234"}

    # Flow removed while listening
    flow._progress = None  # noqa: SLF001
    await flow.async_step_kaiyu()
    assert len(coord._raw_captures) == 1  # noqa: SLF001
    flow.async_remove()
    assert len(coord._raw_captures) == 0  # noqa: SLF001


async def test_kaiyu_reconfigure(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the reconfiguration of the transmission parameters."""
    entry = await create_base_entry(hass, "kaiyu##00C2E577", KAIYU_CONF)
    flow = _flow(hass, coord)
    flow.context = {"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    res = await flow.async_step_reconfigure()
    assert res["step_id"] == "kaiyu_technical"
    with mock.patch.object(hass.config_entries, "async_schedule_reload"):
        res = await flow.async_step_kaiyu_technical({CONF_REPEATS: 4, CONF_INTERVAL: 40})
    assert res["type"] == FlowResultType.ABORT
    assert entry.data[CONF_TECHNICAL] == {CONF_ADAPTER_IDS: ["esp/test"], CONF_REPEATS: 4, CONF_INTERVAL: 40}


async def test_blink(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the blink effect (output value 3)."""
    proxy = MockEspProxy(hass, "test")
    await proxy.setup()
    ctrl = _controller(coord)
    all_light = BleAdvKaiyuLight(ctrl, None)
    line_1 = BleAdvKaiyuLight(ctrl, 0)
    line_2 = BleAdvKaiyuLight(ctrl, 1)
    assert line_1.effect_list == ["steady", "blink"]
    assert line_1.effect is None

    await line_1.async_turn_on(effect="blink")
    await coord.bt_managers[1].adapters["esp/test"].drain()
    parsed = kaiyu_parse_adv(BleAdvAdvertisement.FromRaw(bytes.fromhex(proxy.get_adv_calls()[0]["raw"])).raw)
    assert parsed is not None
    assert parsed[1].values == [3] + [1] * 11
    assert parsed[1].lines == [True] + [False] * 11
    assert line_1.is_on
    assert line_1.effect == "blink"
    assert all_light.effect == "blink"

    await line_1.async_turn_on()  # keeps blinking
    assert ctrl.values[0] == 3
    await line_2.async_turn_on()
    assert ctrl.values[:2] == [3, 2]
    assert all_light.effect == "steady"
    await line_1.async_turn_on(effect="steady")
    assert ctrl.values[0] == 2
    await all_light.async_turn_on(effect="blink")
    assert ctrl.values == [3] * 12
    await coord.bt_managers[1].adapters["esp/test"].drain()
    parsed = kaiyu_parse_adv(BleAdvAdvertisement.FromRaw(bytes.fromhex(proxy.get_adv_calls()[-1]["raw"])).raw)
    assert parsed is not None
    assert (parsed[1].mode, parsed[1].values) == (MODE_ALL, [3] * 12)

    # Followed from the phone app
    ctrl.on_raw_adv("esp/test", "", BleAdvAdvertisement.FromRaw(bytes.fromhex(LINE_1)))
    assert ctrl.values == [2] + [1] * 11

    # Restored
    line_3 = BleAdvKaiyuLight(ctrl, 2)
    line_3.hass = hass
    last = mock.MagicMock()
    last.state = "on"
    last.attributes = {"effect": "blink"}
    with mock.patch.object(BleAdvKaiyuLight, "async_get_last_state", return_value=last):
        await line_3.async_added_to_hass()
    assert ctrl.values[2] == 3
    last.state = "off"
    with mock.patch.object(BleAdvKaiyuLight, "async_get_last_state", return_value=last):
        await line_3.async_added_to_hass()
    assert ctrl.values[2] == 1
