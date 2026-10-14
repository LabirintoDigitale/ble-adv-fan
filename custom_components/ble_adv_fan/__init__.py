"ble_adv_fan package."

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DEVICE, CONF_DEVICE_ID, CONF_NAME, Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig
from homeassistant.helpers.singleton import singleton
from homeassistant.helpers.typing import ConfigType

from .codecs import dyn_codec_params, get_codecs
from .codecs.models import BleAdvCodec, BleAdvConfig, BleAdvEncCmd
from .const import (
    CONF_ADAPTER_ID,
    CONF_ADAPTER_IDS,
    CONF_APPLE_INC_UUIDS,
    CONF_CODEC_ID,
    CONF_CODEC_ID_OLD,
    CONF_COMPANY,
    CONF_COORDINATOR_ID,
    CONF_DEVICE_QUEUE,
    CONF_DURATION,
    CONF_ENTRY_TYPE,
    CONF_FANS,
    CONF_FORCED_ID,
    CONF_GOOGLE_LCC_UUIDS,
    CONF_IGN_ADAPTERS,
    CONF_IGN_CIDS,
    CONF_IGN_DURATION,
    CONF_IGN_MACS,
    CONF_INDEX,
    CONF_INTERVAL,
    CONF_KEEP_RECV,
    CONF_KEYS,
    CONF_LAST_VERSION,
    CONF_LIGHTS,
    CONF_MAINTAINER_MENUS,
    CONF_MAX_ENTITY_NB,
    CONF_PAIRED,
    CONF_PARAMS,
    CONF_RAW,
    CONF_REFRESH_DIR_ON_START,
    CONF_REFRESH_ON_START,
    CONF_REFRESH_OSC_ON_START,
    CONF_REMOTE,
    CONF_REMOTES,
    CONF_REPEAT,
    CONF_REPEATS,
    CONF_TECHNICAL,
    CONF_TRANS_SET,
    CONF_USE_DIR,
    CONF_USE_OSC,
    DOMAIN,
    ENTRY_TYPE_KAIYU,
    ENTRY_TYPE_LEARNED,
    KAIYU_PLATFORMS,
    LEARNED_PLATFORMS,
    PLATFORMS,
)
from .coordinator import BleAdvCoordinator
from .device import BleAdvDevice
from .kaiyu_lights import BleAdvKaiyuController
from .learned_remote import BleAdvLearnedKey, BleAdvLearnedRemote

_LOGGER = logging.getLogger(__name__)

INJECT_RAW_SERVICE_NAME = "inject_raw"
SEND_COMMAND_SERVICE_NAME = "send_command"
_BYTE = vol.All(vol.Coerce(int), vol.Range(min=0, max=255))
SEND_COMMAND_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_DEVICE_ID): cv.string,
        vol.Required("cmd"): _BYTE,
        **{vol.Optional(arg, default=0): _BYTE for arg in ("param", "arg0", "arg1", "arg2", "arg3", "arg4")},
    }
)
INJECT_RAW_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ADAPTER_ID): str,
        vol.Required(CONF_RAW): str,
        vol.Optional(CONF_INTERVAL, default=20): NumberSelector(NumberSelectorConfig(min=10, max=150)),
        vol.Optional(CONF_REPEAT, default=3): NumberSelector(NumberSelectorConfig(min=1, max=20)),
        vol.Optional(CONF_DEVICE_QUEUE, default="device"): str,
        vol.Optional(CONF_DURATION, default=800): NumberSelector(NumberSelectorConfig(min=100, max=2000)),
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional(CONF_IGN_ADAPTERS): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(CONF_IGN_DURATION): vol.All(vol.Coerce(int), vol.Range(min=0, max=60000)),
                vol.Optional(CONF_IGN_CIDS): vol.All(cv.ensure_list, [vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFF))]),
                vol.Optional(CONF_IGN_MACS): vol.All(cv.ensure_list, [cv.string]),
                vol.Optional(CONF_KEEP_RECV): vol.All(vol.Coerce(int), vol.Range(min=0, max=10000)),
                vol.Optional(CONF_MAINTAINER_MENUS): cv.boolean,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

type BleAdvConfigEntry = ConfigEntry[BleAdvDevice | BleAdvLearnedRemote | BleAdvKaiyuController]


def is_learned_remote(entry: ConfigEntry) -> bool:
    """Return True if the entry is a Learned Remote."""
    return entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_LEARNED


def entry_platforms(entry: ConfigEntry) -> list[Platform]:
    """Return the platforms of the entry, depending on its type."""
    return {ENTRY_TYPE_LEARNED: LEARNED_PLATFORMS, ENTRY_TYPE_KAIYU: KAIYU_PLATFORMS}.get(entry.data.get(CONF_ENTRY_TYPE, ""), PLATFORMS)


@singleton(f"{DOMAIN}/{CONF_COORDINATOR_ID}")
async def get_coordinator(hass: HomeAssistant) -> BleAdvCoordinator:
    """Get and initiate a coordinator."""
    conf = hass.data.get(DOMAIN, {}).pop(CONF_COORDINATOR_ID, {})
    coordinator = BleAdvCoordinator(
        hass,
        get_codecs(),
        conf.get(CONF_IGN_ADAPTERS, []),
        conf.get(CONF_IGN_DURATION, 60000),
        conf.get(CONF_IGN_CIDS, [*CONF_GOOGLE_LCC_UUIDS, *CONF_APPLE_INC_UUIDS]),
        conf.get(CONF_IGN_MACS, []),
        conf.get(CONF_KEEP_RECV, 100),
        conf.get(CONF_MAINTAINER_MENUS, False),
    )
    await coordinator.async_init()
    return coordinator


async def async_setup(hass: HomeAssistant, conf: ConfigType) -> bool:
    """Initialize the integration."""
    ble_adv_conf = conf.get(DOMAIN, {})
    _LOGGER.debug(f"BLE ADV: Setting component with conf {ble_adv_conf}")
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][CONF_COORDINATOR_ID] = ble_adv_conf
    coord = await get_coordinator(hass)

    async def inject_raw(call: ServiceCall) -> None:
        if errors := await coord.inject_raw(call.data):
            msg = "/".join([f"Invalid {field} - {reason}" for field, reason in errors.items()])
            raise vol.Invalid(msg)

    hass.services.async_register(DOMAIN, INJECT_RAW_SERVICE_NAME, inject_raw, INJECT_RAW_SCHEMA)

    async def send_command(call: ServiceCall) -> None:
        """Send a raw command (cmd / param / args) to a device, with its codec and config: to test unknown commands."""
        from .helpers import get_device_from_id  # noqa: PLC0415

        device = await get_device_from_id(hass, call.data[CONF_DEVICE_ID])
        if not isinstance(device, BleAdvDevice):
            msg = "Only for the devices using a codec"
            raise vol.Invalid(msg)
        await device.apply_cmd(BleAdvEncCmd(**{key: value for key, value in call.data.items() if key != CONF_DEVICE_ID}))

    hass.services.async_register(DOMAIN, SEND_COMMAND_SERVICE_NAME, send_command, SEND_COMMAND_SCHEMA)
    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: BleAdvConfigEntry) -> bool:
    """Migrate old entry."""
    if CONF_ENTRY_TYPE in config_entry.data:
        return True

    new_data = {**config_entry.data}
    update_needed: bool = False
    if CONF_ADAPTER_ID in new_data[CONF_DEVICE]:
        new_data[CONF_TECHNICAL][CONF_ADAPTER_ID] = new_data[CONF_DEVICE].pop(CONF_ADAPTER_ID)
        update_needed = True
    if CONF_NAME in new_data[CONF_DEVICE]:
        new_data[CONF_DEVICE].pop(CONF_NAME)
        update_needed = True
    if CONF_ADAPTER_ID in new_data.get(CONF_REMOTE, []):
        new_data[CONF_REMOTE].pop(CONF_ADAPTER_ID)
        update_needed = True
    if len(new_data[CONF_FANS]) < CONF_MAX_ENTITY_NB:
        new_data[CONF_FANS] += [{}] * (CONF_MAX_ENTITY_NB - len(new_data[CONF_FANS]))
        update_needed = True
    if len(new_data[CONF_LIGHTS]) < CONF_MAX_ENTITY_NB:
        new_data[CONF_LIGHTS] += [{}] * (CONF_MAX_ENTITY_NB - len(new_data[CONF_LIGHTS]))
        update_needed = True
    for fan in new_data[CONF_FANS]:
        if CONF_REFRESH_ON_START in fan:
            refresh_on_start = fan.pop(CONF_REFRESH_ON_START)
            fan[CONF_REFRESH_DIR_ON_START] = refresh_on_start and fan.get(CONF_USE_DIR, False)
            fan[CONF_REFRESH_OSC_ON_START] = refresh_on_start and fan.get(CONF_USE_OSC, False)
            update_needed = True
    if CONF_ADAPTER_ID in new_data[CONF_TECHNICAL]:
        new_data[CONF_TECHNICAL][CONF_ADAPTER_IDS] = [new_data[CONF_TECHNICAL].pop(CONF_ADAPTER_ID)]
        update_needed = True
    if CONF_REPEATS not in new_data[CONF_TECHNICAL] and CONF_REPEAT in new_data[CONF_TECHNICAL]:
        new_data[CONF_TECHNICAL][CONF_REPEATS] = 3 * new_data[CONF_TECHNICAL][CONF_REPEAT]
        update_needed = True
    if CONF_CODEC_ID_OLD in new_data[CONF_DEVICE]:
        new_id, params = dyn_codec_params(new_data[CONF_DEVICE][CONF_CODEC_ID_OLD])
        if new_id != new_data[CONF_DEVICE].get(CONF_CODEC_ID) or params != new_data[CONF_DEVICE].get(CONF_PARAMS):
            new_data[CONF_DEVICE][CONF_CODEC_ID] = new_id
            new_data[CONF_DEVICE][CONF_PARAMS] = params
            update_needed = True
    if CONF_REMOTE in new_data and CONF_CODEC_ID_OLD in new_data[CONF_REMOTE]:
        new_id, params = dyn_codec_params(new_data[CONF_REMOTE][CONF_CODEC_ID_OLD])
        if new_id != new_data[CONF_REMOTE].get(CONF_CODEC_ID) or params != new_data[CONF_REMOTE].get(CONF_PARAMS):
            new_data[CONF_REMOTE][CONF_CODEC_ID] = new_id
            new_data[CONF_REMOTE][CONF_PARAMS] = params
            update_needed = True
    if new_data[CONF_DEVICE][CONF_CODEC_ID] == "zhijia_v2_fl":
        new_data[CONF_DEVICE][CONF_CODEC_ID] = "zhijia_v2"
        new_data[CONF_TECHNICAL][CONF_TRANS_SET] = "fl"
        update_needed = True
    if CONF_REMOTES not in new_data:
        new_data[CONF_REMOTES] = []
        if exist_rem := new_data.get(CONF_REMOTE):
            if CONF_NAME not in exist_rem:
                exist_rem[CONF_NAME] = f"{exist_rem.get(CONF_CODEC_ID)}##0x{exist_rem.get(CONF_FORCED_ID):X}##{exist_rem.get(CONF_INDEX):d}"
            if CONF_PAIRED not in exist_rem:
                exist_rem[CONF_PAIRED] = True
            if CONF_TRANS_SET not in exist_rem:
                exist_rem[CONF_TRANS_SET] = BleAdvCodec.DEF_TRANS_NAME
            new_data[CONF_REMOTES] = [exist_rem]
        update_needed = True

    if config_entry.version < 2:
        coordinator = await get_coordinator(hass)
        adapt_ids = coordinator.get_adapter_ids()
        if new_data[CONF_TECHNICAL][CONF_ADAPTER_IDS][0] not in adapt_ids:
            _LOGGER.debug(f"Migrating {config_entry.unique_id} configuration from version {config_entry.version}")
            if len(adapt_ids) == 0:
                _LOGGER.error(f"No adapters detected while migrating entry: adapter {new_data[CONF_TECHNICAL][CONF_ADAPTER_IDS][0]} kept.")
            else:
                new_data[CONF_TECHNICAL][CONF_ADAPTER_IDS] = adapt_ids.copy()
            update_needed = True

    if update_needed:
        hass.config_entries.async_update_entry(config_entry, data=new_data, version=CONF_LAST_VERSION)
        _LOGGER.info(f"Migration of entry {config_entry.unique_id} to configuration version {config_entry.version} successful")

    return True


async def async_setup_entry(hass: HomeAssistant, entry: BleAdvConfigEntry) -> bool:
    """Set up BLE ADV from a config entry."""
    _LOGGER.debug(f"BLE ADV: Setting up entry {entry.unique_id} / {entry.data}")

    if entry.unique_id is None:
        _LOGGER.warning("entry ignored as unique_id is None.")
        return False

    tech_conf = entry.data[CONF_TECHNICAL]
    coordinator = await get_coordinator(hass)

    # Lazy migration to prefixed adapter names for legacy "esp" adapters, allowing seemless fallback
    prefixes = tuple(f"{bt_manager.name}/" for bt_manager in coordinator.bt_managers)
    adapter_ids = [a if a.startswith(prefixes) else f"esp/{a}" for a in tech_conf[CONF_ADAPTER_IDS]]

    if is_learned_remote(entry):
        remote = BleAdvLearnedRemote(
            coordinator,
            entry.unique_id,
            entry.title,
            adapter_ids,
            [BleAdvLearnedKey.from_conf(key) for key in entry.data[CONF_KEYS]],
            int(tech_conf[CONF_REPEATS]),
            int(tech_conf[CONF_INTERVAL]),
        )
        entry.runtime_data = remote
        coordinator.add_raw_listener(remote)
        await hass.config_entries.async_forward_entry_setups(entry, LEARNED_PLATFORMS)
        return True

    if entry.data.get(CONF_ENTRY_TYPE) == ENTRY_TYPE_KAIYU:
        controller = BleAdvKaiyuController(
            coordinator,
            entry.unique_id,
            entry.title,
            adapter_ids,
            bytes.fromhex(entry.data[CONF_COMPANY]),
            bytes.fromhex(entry.data[CONF_DEVICE]),
            int(tech_conf[CONF_REPEATS]),
            int(tech_conf[CONF_INTERVAL]),
        )
        entry.runtime_data = controller
        coordinator.add_raw_listener(controller)
        await hass.config_entries.async_forward_entry_setups(entry, KAIYU_PLATFORMS)
        return True

    device_conf = entry.data[CONF_DEVICE]

    entry.runtime_data = BleAdvDevice(
        hass,
        entry.unique_id,
        entry.title,
        device_conf[CONF_CODEC_ID],
        adapter_ids,
        tech_conf[CONF_REPEATS],
        tech_conf[CONF_INTERVAL],
        tech_conf[CONF_DURATION],
        BleAdvConfig(device_conf[CONF_FORCED_ID], device_conf[CONF_INDEX], device_conf.get(CONF_PARAMS), tech_conf.get(CONF_TRANS_SET)),
        coordinator,
    )
    for rconf in entry.data[CONF_REMOTES]:
        entry.runtime_data.add_listener(
            rconf[CONF_CODEC_ID],
            BleAdvConfig(rconf[CONF_FORCED_ID], rconf[CONF_INDEX], rconf.get(CONF_PARAMS), rconf.get(CONF_TRANS_SET)),
            rconf.get(CONF_PAIRED, True),
        )

    coordinator.add_device(entry.runtime_data)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug(f"Unloading entry {entry.unique_id}")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, entry_platforms(entry))
    if unload_ok:
        coordinator = await get_coordinator(hass)
        if CONF_ENTRY_TYPE in entry.data:
            coordinator.remove_raw_listener(entry.runtime_data)
        else:
            coordinator.remove_device(entry.runtime_data)
    return unload_ok
