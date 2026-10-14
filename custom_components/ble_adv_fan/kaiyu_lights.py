"""Kaiyu LEGO compatible light controller: 12 ON / OFF outputs."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.const import STATE_ON
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.restore_state import RestoreEntity

from .codecs.models import BleAdvAdvertisement
from .const import DOMAIN
from .coordinator import BleAdvCoordinator
from .kaiyu import LINES_NB, MODE_ALL, MODE_LINES, kaiyu_build_adv, kaiyu_encode, kaiyu_parse_adv
from .learned_remote import async_send_raw

_LOGGER = logging.getLogger(__name__)

KAIYU_LINE_KEY = "kaiyu_line"
KAIYU_ALL_KEY = "kaiyu_all"


class BleAdvKaiyuController:
    """Kaiyu controller: sends the state of all its outputs at each change, and follows the commands of the phone app."""

    def __init__(
        self,
        coordinator: BleAdvCoordinator,
        unique_id: str,
        name: str,
        adapter_ids: list[str],
        company: bytes,
        device_id: bytes,
        repeat: int,
        interval: int,
    ) -> None:
        self.coordinator: BleAdvCoordinator = coordinator
        self.unique_id: str = unique_id
        self.name: str = name
        self.adapter_ids: list[str] = adapter_ids
        self.company: bytes = company
        self.device_id: bytes = device_id
        self.repeat: int = repeat
        self.interval: int = interval
        self.lines: list[bool] = [False] * LINES_NB
        self._entities: list[BleAdvKaiyuLight] = []

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=self.name,
            hw_version=", ".join(self.adapter_ids),
            model="Kaiyu 12 LED outputs",
            model_id=f"0x{self.company.hex().upper()} / 0x{self.device_id.hex().upper()}",
        )

    @property
    def available(self) -> bool:
        """Return True if one of the adapters is available."""
        return any(adapter_id in self.coordinator.get_adapter_ids() for adapter_id in self.adapter_ids)

    def add_entity(self, ent: BleAdvKaiyuLight) -> None:
        """Add an entity."""
        self._entities.append(ent)

    def _write_states(self) -> None:
        for ent in self._entities:
            if ent.hass is not None:
                ent.async_write_ha_state()

    def update_availability(self) -> None:
        """Update availability of the entities."""
        self._write_states()

    async def async_set_lines(self, changes: dict[int, bool]) -> None:
        """Change the state of some outputs and send the state of all the outputs."""
        for index, state in changes.items():
            self.lines[index] = state
        mode = MODE_ALL if len(set(self.lines)) == 1 else MODE_LINES
        raw = kaiyu_build_adv(self.company, kaiyu_encode(mode, self.device_id, self.lines))
        _LOGGER.info(f"[{self.name}] Sending outputs {self.lines}")
        await async_send_raw(self.coordinator, self.adapter_ids, self.unique_id, raw, self.repeat, self.interval)
        self._write_states()

    def on_raw_adv(self, adapter_id: str, _: str, adv: BleAdvAdvertisement) -> None:
        """Follow the commands sent by the phone app."""
        if adapter_id not in self.adapter_ids or adv.ble_type != 0xFF:
            return
        if (parsed := kaiyu_parse_adv(adv.raw)) is None:
            return
        company, cmd = parsed
        if company != self.company or cmd.device_id != self.device_id:
            return
        new_lines = [cur if new is None else new for cur, new in zip(self.lines, cmd.lines, strict=True)]
        if new_lines != self.lines:
            self.lines = new_lines
            self._write_states()


class BleAdvKaiyuLight(LightEntity, RestoreEntity):
    """One output of the controller, or all the outputs when index is None."""

    _attr_has_entity_name = True
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = frozenset({ColorMode.ONOFF})
    _attr_assumed_state = True

    def __init__(self, controller: BleAdvKaiyuController, index: int | None) -> None:
        self._controller: BleAdvKaiyuController = controller
        self._index: int | None = index
        self._attr_device_info = controller.device_info
        if index is None:
            self._attr_unique_id = f"{controller.unique_id}_all"
            self._attr_translation_key = KAIYU_ALL_KEY
        else:
            self._attr_unique_id = f"{controller.unique_id}_line_{index + 1}"
            self._attr_translation_key = KAIYU_LINE_KEY
            self._attr_translation_placeholders = {"line": str(index + 1)}
        controller.add_entity(self)

    @property
    def available(self) -> bool:
        """Return if available."""
        return self._controller.available

    @property
    def is_on(self) -> bool:
        """Return if on: for all the outputs, if one of them is on."""
        if self._index is None:
            return any(self._controller.lines)
        return self._controller.lines[self._index]

    def _changes(self, state: bool) -> dict[int, bool]:
        return dict.fromkeys(range(LINES_NB), state) if self._index is None else {self._index: state}

    async def async_turn_on(self, **_: Any) -> None:  # noqa: ANN401
        """Turn on."""
        await self._controller.async_set_lines(self._changes(True))

    async def async_turn_off(self, **_: Any) -> None:  # noqa: ANN401
        """Turn off."""
        await self._controller.async_set_lines(self._changes(False))

    async def async_added_to_hass(self) -> None:
        """Restore the state of the output."""
        await super().async_added_to_hass()
        if self._index is not None and (last_state := await self.async_get_last_state()) is not None:
            self._controller.lines[self._index] = last_state.state == STATE_ON
