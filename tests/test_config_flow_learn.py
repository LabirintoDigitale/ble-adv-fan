"""Config flow tests: Universal BLE Remote and Bluetooth devices present."""

# ruff: noqa: S101
import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from unittest import mock

import pytest
from ble_adv_fan.adapters import BleAdvAdapter
from ble_adv_fan.codecs.models import BleAdvAdvertisement
from ble_adv_fan.config_flow import BleAdvConfigFlow, BleAdvLearnProgress
from ble_adv_fan.const import (
    CONF_ADAPTER_IDS,
    CONF_ENTRY_TYPE,
    CONF_INTERVAL,
    CONF_KEY_ID,
    CONF_KEYS,
    CONF_RAW,
    CONF_REPEATS,
    CONF_TECHNICAL,
    ENTRY_TYPE_LEARNED,
)
from ble_adv_fan.coordinator import BleAdvCoordinator
from ble_adv_fan.presence import BleAdvPresenceTracker
from homeassistant.config_entries import SOURCE_RECONFIGURE, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import MockEspProxy, create_base_entry

NOISE = BleAdvAdvertisement(0xFF, b"\xf0\x09noise_beacon", 0x1A)
KEY = BleAdvAdvertisement(0xFF, b"\xf0\x08remote_key1", 0x1A)
OTHER = BleAdvAdvertisement(0xFF, b"\xf0\x08remote_oth1", 0x1A)
THIRD = BleAdvAdvertisement(0xFF, b"\xf0\x08remote_thr1", 0x1A)


async def _wait_done(step: Callable[[], Awaitable[ConfigFlowResult]], max_loops: int = 100) -> ConfigFlowResult:
    for _ in range(max_loops):
        res = await step()
        if res["type"] != FlowResultType.SHOW_PROGRESS:
            return res
        await asyncio.sleep(0.05)
    raise AssertionError("Progress never ended")


async def _drain(coord: BleAdvCoordinator) -> None:
    adapter = coord.bt_managers[1].adapters["esp/test"]
    try:
        await asyncio.wait_for(adapter.drain(), 5)
    except TimeoutError as exc:
        msg = f"Adapter not drained: {coord.bt_managers[1].diagnostic_dump()}"
        raise AssertionError(msg) from exc


def _flow(hass: HomeAssistant, coord: BleAdvCoordinator) -> BleAdvConfigFlow:
    flow = BleAdvConfigFlow()
    flow.hass = hass
    flow.coordinator = coord
    flow.context = {}
    flow.WAIT_TEST_LIGHT = 0.05
    return flow


async def test_learn_progress(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the capture: noise is excluded, the key is ranked first, early stop once released."""
    flow = _flow(hass, coord)
    progress = BleAdvLearnProgress(flow, "learn_capture", "On", 0.1, 5)
    res = progress.next()
    assert res is not None
    assert res["progress_action"] == "learn_quiet"
    assert res["description_placeholders"] == {"key": "On", "seconds": "0"}
    await coord.handle_raw_adv("esp/test", "AA:AA:AA:AA:AA:01", NOISE.to_raw())
    await coord.handle_raw_adv("esp/test", "AA:AA:AA:AA:AA:02", OTHER.to_raw())
    await asyncio.sleep(0.15)
    for _ in range(3):
        await coord.handle_raw_adv("esp/test", "BB:BB:BB:BB:BB:01", KEY.to_raw())
    await coord.handle_raw_adv("esp/test", "AA:AA:AA:AA:AA:01", OTHER.to_raw())  # MAC seen as noise
    await coord.handle_raw_adv("esp/test", "BB:BB:BB:BB:BB:02", NOISE.to_raw())  # ADV seen as noise
    await coord.handle_raw_adv("esp/test", "BB:BB:BB:BB:BB:03", OTHER.to_raw())  # ADV seen as noise
    await coord.handle_raw_adv("esp/test", "BB:BB:BB:BB:BB:03", THIRD.to_raw())
    with mock.patch("ble_adv_fan.config_flow.LEARN_END_SILENCE", timedelta(seconds=0.1)):
        start = datetime.now()
        res = progress.next()
        assert res is not None
        assert res["progress_action"] == "learn_press"
        while progress.next() is not None:
            await asyncio.sleep(0.05)
    assert (datetime.now() - start) < timedelta(seconds=2)
    progress.stop()
    cands = progress.candidates()
    assert [(cand.raw, cand.count) for cand in cands] == [(KEY.to_raw(), 3), (THIRD.to_raw(), 1)]


async def test_learn_flow(hass: HomeAssistant, coord: BleAdvCoordinator, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the full Universal BLE Remote flow."""
    # A learned key is advertised in one single session, longer than the max wait set by other tests
    monkeypatch.setattr(BleAdvAdapter, "MAX_ADV_WAIT", 3.0)
    proxy = MockEspProxy(hass, "test")
    await proxy.setup()
    flow = _flow(hass, coord)
    res = await flow.async_step_user()
    assert "learn_remote" in res["menu_options"]

    res = await flow.async_step_learn_remote()
    assert res["step_id"] == "learn_remote"
    res = await flow.async_step_learn_remote({CONF_NAME: "Remote", CONF_ADAPTER_IDS: []})
    assert res["errors"] == {"base": "missing_adapter"}
    res = await flow.async_step_learn_remote({CONF_NAME: "Remote", CONF_ADAPTER_IDS: ["esp/test"]})
    assert res["step_id"] == "learn_key"
    res = await flow.async_step_learn_key({CONF_NAME: "  "})
    assert res["errors"] == {CONF_NAME: "invalid_key_name"}

    # Nothing received
    with mock.patch("ble_adv_fan.config_flow.LEARN_QUIET_SECONDS", 0.05), mock.patch("ble_adv_fan.config_flow.LEARN_PRESS_SECONDS", 0.1):
        res = await flow.async_step_learn_key({CONF_NAME: "On"})
        assert res["type"] == FlowResultType.SHOW_PROGRESS
        res = await _wait_done(flow.async_step_learn_capture)
    assert res["step_id"] == "learn_none"
    res = await flow.async_step_learn_none()
    assert res["menu_options"] == ["learn_capture_again", "learn_menu"]

    # Key received
    flow._progress = BleAdvLearnProgress(flow, "learn_capture", "On", 0.05, 0.3)  # noqa: SLF001
    await asyncio.sleep(0.1)
    await coord.handle_raw_adv("esp/test", "BB:BB:BB:BB:BB:01", KEY.to_raw())
    res = await _wait_done(flow.async_step_learn_capture)
    assert res["step_id"] == "learn_choose"
    res = await flow.async_step_learn_choose()
    assert next(iter(res["data_schema"].schema.values())).config["options"][0]["value"] == KEY.to_raw().hex().upper()

    res = await flow.async_step_learn_choose({CONF_RAW: KEY.to_raw().hex().upper()})
    assert res["type"] == FlowResultType.SHOW_PROGRESS
    res = await _wait_done(flow.async_step_learn_test)
    assert res["step_id"] == "learn_test_res"
    await _drain(coord)
    assert {call["raw"] for call in proxy.get_adv_calls()} == {KEY.to_raw().hex()}
    res = await flow.async_step_learn_test_res()
    assert res["menu_options"][0] == "learn_save"

    # Change the transmission parameters and replay: one single transmission
    res = await flow.async_step_learn_technical_test()
    assert res["step_id"] == "learn_technical_test"
    res = await flow.async_step_learn_technical_test({CONF_REPEATS: 3.0, CONF_INTERVAL: 20.0})
    assert res["type"] == FlowResultType.SHOW_PROGRESS
    res = await _wait_done(flow.async_step_learn_test)
    assert res["step_id"] == "learn_test_res"
    await _drain(coord)
    assert len(proxy.get_adv_calls()) == 1
    res = await flow.async_step_learn_technical()
    assert res["step_id"] == "learn_technical"
    res = await flow.async_step_learn_technical({CONF_REPEATS: 4, CONF_INTERVAL: 30})
    assert res["step_id"] == "learn_menu"

    res = await flow.async_step_learn_save()
    assert res["step_id"] == "learn_menu"
    assert res["menu_options"] == ["learn_key", "learn_delete", "learn_technical", "learn_finish"]
    assert res["description_placeholders"] == {"keys": "- On"}
    res = await flow.async_step_learn_key({CONF_NAME: "On"})
    assert res["errors"] == {CONF_NAME: "duplicate_key_name"}

    res = await flow.async_step_learn_finish()
    assert res["type"] == FlowResultType.CREATE_ENTRY
    assert res["title"] == "Remote"
    data = res["data"]
    assert data[CONF_ENTRY_TYPE] == ENTRY_TYPE_LEARNED
    assert data[CONF_TECHNICAL] == {CONF_ADAPTER_IDS: ["esp/test"], CONF_REPEATS: 4, CONF_INTERVAL: 30}
    assert [(key[CONF_NAME], key[CONF_RAW]) for key in data[CONF_KEYS]] == [("On", KEY.to_raw().hex().upper())]
    assert flow.unique_id is not None
    assert flow.unique_id.startswith("learned##")


async def test_learn_flow_delete_abort(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the delete of keys, the abort and the flow removal."""
    flow = _flow(hass, coord)
    flow._learn = {CONF_KEYS: [{CONF_KEY_ID: "k1", CONF_NAME: "On", CONF_RAW: "00"}]}  # noqa: SLF001
    res = await flow.async_step_learn_delete()
    assert res["step_id"] == "learn_delete"
    res = await flow.async_step_learn_delete({CONF_KEYS: ["k1"]})
    assert res["menu_options"] == ["learn_key", "learn_technical", "learn_abort"]
    assert res["description_placeholders"] == {"keys": "-"}
    res = await flow.async_step_learn_abort()
    assert res["reason"] == "no_keys"

    flow._learn_key_name = "On"  # noqa: SLF001
    res = await flow.async_step_learn_capture_again()
    assert res["type"] == FlowResultType.SHOW_PROGRESS
    assert len(coord._raw_captures) == 1  # noqa: SLF001
    flow.async_remove()
    assert len(coord._raw_captures) == 0  # noqa: SLF001
    flow._progress = None  # noqa: SLF001
    flow.async_remove()


async def test_learn_reconfigure(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the reconfiguration of a Learned Remote."""
    data = {
        CONF_ENTRY_TYPE: ENTRY_TYPE_LEARNED,
        CONF_TECHNICAL: {CONF_ADAPTER_IDS: ["esp/test"]},
        CONF_KEYS: [{CONF_KEY_ID: "k1", CONF_NAME: "On", CONF_RAW: "00"}, {CONF_KEY_ID: "k2", CONF_NAME: "Off", CONF_RAW: "01"}],
    }
    entry = await create_base_entry(hass, "learned##id", data)
    flow = _flow(hass, coord)
    flow.context = {"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    res = await flow.async_step_reconfigure()
    assert res["step_id"] == "learn_menu"
    assert res["description_placeholders"] == {"keys": "- On\n- Off"}
    await flow.async_step_learn_delete({CONF_KEYS: ["k1"]})
    with mock.patch.object(hass.config_entries, "async_schedule_reload"):
        res = await flow.async_step_learn_finish()
    assert res["type"] == FlowResultType.ABORT
    assert [key[CONF_KEY_ID] for key in entry.data[CONF_KEYS]] == ["k2"]


async def test_bt_devices(hass: HomeAssistant, coord: BleAdvCoordinator) -> None:
    """Test the list of Bluetooth devices present for at least one hour."""
    flow = _flow(hass, coord)
    res = await flow.async_step_tools()
    assert "bt_devices" in res["menu_options"]
    res = await flow.async_step_bt_devices()
    assert res["description_placeholders"]["count"] == "0"
    assert res["description_placeholders"]["rows"] == ""
    assert res["description_placeholders"]["ha_bt"] == "❌"

    now = datetime.now()
    coord.presence = BleAdvPresenceTracker(timedelta(days=3), 500)
    coord.presence.started = now - timedelta(days=2)
    coord.presence.record("AA:BB:CC:DD:EE:01", "hci/1", "Lamp", -60, now - timedelta(hours=26, minutes=5))
    coord.presence.record("AA:BB:CC:DD:EE:01", "esp/proxy", None, None, now)
    coord.presence.record("AA:BB:CC:DD:EE:02", "hci/1", None, None, now - timedelta(minutes=30))
    for i in range(120):
        coord.presence.record(f"AA:BB:CC:DD:FF:{i:02X}", "hci/1", None, -80, now - timedelta(hours=2))
        coord.presence.record(f"AA:BB:CC:DD:FF:{i:02X}", "hci/1", None, -80, now - timedelta(hours=1))
    res = await flow.async_step_bt_devices()
    ph = res["description_placeholders"]
    assert res["menu_options"] == ["bt_devices", "tools"]
    assert ph["count"] == "121"
    assert ph["tracked"] == "122"
    assert ph["monitoring"].startswith("2d 0h")
    assert ph["gap"] == "4320"
    lines = ph["rows"].split("\n")
    assert lines[0] == "| `AA:BB:CC:DD:EE:01` | Lamp | -60 | 1d 2h 05m | 0h 00m | 2 | esp/proxy, hci/1 |"
    assert lines[1] == "| `AA:BB:CC:DD:FF:00` | - | -80 | 2h 00m | 1h 00m | 2 | hci/1 |"
    assert lines[-1] == "| ... +21 | | | | | | |"
