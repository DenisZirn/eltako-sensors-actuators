from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
try:
    from homeassistant.components.sensor import SensorStateClass
except Exception:  # pragma: no cover
    SensorStateClass = None
from homeassistant.const import UnitOfElectricPotential, UnitOfTemperature
try:
    from homeassistant.const import PERCENTAGE
except Exception:  # pragma: no cover
    PERCENTAGE = "%"
try:
    from homeassistant.const import CONCENTRATION_PARTS_PER_BILLION
except Exception:  # pragma: no cover
    CONCENTRATION_PARTS_PER_BILLION = "ppb"
try:
    from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION
except Exception:  # pragma: no cover
    CONCENTRATION_PARTS_PER_MILLION = "ppm"
try:
    from homeassistant.const import UnitOfEnergy
    KWH_UNIT = UnitOfEnergy.KILO_WATT_HOUR
except Exception:  # pragma: no cover
    KWH_UNIT = "kWh"

try:
    from homeassistant.const import UnitOfPower
    WATT_UNIT = UnitOfPower.WATT
except Exception:  # pragma: no cover
    WATT_UNIT = "W"

try:
    from homeassistant.const import UnitOfSpeed
    KPH_UNIT = UnitOfSpeed.KILOMETERS_PER_HOUR
except Exception:  # pragma: no cover
    KPH_UNIT = "km/h"

try:
    from homeassistant.const import UnitOfIlluminance
    LUX_UNIT = UnitOfIlluminance.LUX
except ImportError:
    try:
        from homeassistant.const import LIGHT_LUX
        LUX_UNIT = LIGHT_LUX
    except ImportError:
        LUX_UNIT = "lx"

from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
try:
    from homeassistant.util import dt as dt_util
except Exception:  # pragma: no cover
    dt_util = None
try:
    from homeassistant.util import slugify
except Exception:  # pragma: no cover
    import re

    def slugify(value):
        return re.sub(r"[^a-z0-9_]+", "_", str(value or "").lower()).strip("_")

from .const import CONF_DEVICES, DOMAIN
from .bus.eep_a5_09_04 import decode_a5_09_04
from .bus.eep_ffg7b import enrich_ffg7b_decoded
from .entity_base import (
    EltakoBaseEntity,
    EltakoGatewayEntity,
    EltakoYamlEntity,
    _is_flgtf_device,
    _is_ffg7b_device,
    _is_frwb_device,
    _is_fts14em_device,
    _f4usm61b_mode,
    _f4usm61b_physical_unique_id,
    _is_f4usm61b_device,
    _is_fae14lpr_device,
    _futh55ed_mode,
    _is_futh55ed_device,
    _flgtf_device_base_id,
    _strip_flgtf_suffix,
    device_key,
    normalize_eep,
    normalize_platform,
)

_LOGGER = logging.getLogger(__name__)

VOC_DEVICE_CLASS = getattr(SensorDeviceClass, "VOLATILE_ORGANIC_COMPOUNDS", None)
CO2_DEVICE_CLASS = getattr(SensorDeviceClass, "CO2", None)

def _is_fbht_device(device: dict[str, Any]) -> bool:
    """Return True for the temperature-capable FBHT variant of A5-08-01.

    FBH55ESB uses DB1 as unused. FBHT55ESB uses the same motion/brightness
    telegram but additionally encodes 0..50 °C in DB1 (0..255). New EEDTOY
    exports set ``fbht_temperature: true``; the name check keeps older YAML
    files compatible.
    """
    if not isinstance(device, dict):
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    explicit = device.get("fbht_temperature")
    if explicit is None:
        explicit = raw.get("fbht_temperature")
    if isinstance(explicit, str):
        explicit = explicit.strip().lower() in {"1", "true", "yes", "on", "ja"}
    if explicit is not None:
        return bool(explicit)
    name_text = " ".join(
        str(value or "")
        for value in (device.get("name"), raw.get("name"))
    ).upper()
    return "FBHT" in name_text



def _is_fsm60b_mode4(device: dict[str, Any]) -> bool:
    """Return True for an FSM60B operating-mode-4 A5-30-01 row.

    EEDTOY historically exported some FSM60B rows without device_family and
    operating_mode.  Prefer the explicit fields, but keep the confirmed
    A5-30-01 + FSM60B name signature so existing YAML continues to expose the
    battery value transmitted in every data/status telegram.
    """
    if not isinstance(device, dict):
        return False
    if normalize_eep(device.get("eep")) != "A5-30-01":
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    family = str(device.get("device_family") or raw.get("device_family") or "").strip().upper()
    name = str(device.get("name") or raw.get("name") or "").strip().upper()
    mode_value = device.get("operating_mode")
    if mode_value in (None, ""):
        mode_value = raw.get("operating_mode")
    try:
        mode = int(mode_value) if mode_value not in (None, "") else None
    except (TypeError, ValueError):
        mode = None
    if family == "FSM60B":
        return mode in (None, 4)
    return "FSM60B" in name and mode in (None, 4)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = data.get(CONF_DEVICES) or []

    entities: list[SensorEntity] = _gateway_status_entities(gateway)
    f4usm61b_battery_ids: set[str] = set()

    # FLGTF is one physical device that transmits two EEPs from two EnOcean
    # addresses (TVOC on A5-09-0C and temperature/humidity on A5-04-02).
    # Build one shared "Letztes Telegramm" entity per physical FLGTF instead
    # of one timestamp entity for each profile/address.
    flgtf_groups: dict[str, list[dict[str, Any]]] = {}
    for candidate in devices:
        if not isinstance(candidate, dict) or not _is_flgtf_device(candidate):
            continue
        base_id = _flgtf_device_base_id(candidate) or str(candidate.get("id") or "").upper()
        if base_id:
            flgtf_groups.setdefault(base_id, []).append(candidate)

    for device in devices:
        if not isinstance(device, dict):
            continue
        platform = normalize_platform(device.get("platform"))
        eep = normalize_eep(device.get("eep"))

        # Add one passive EnOcean-ID/address sensor to every imported YAML
        # device, independent of its Home Assistant platform. It is purely
        # diagnostic and must not affect telegram RX/TX paths.
        if device.get("id"):
            entities.append(EltakoDeviceAddressSensor(gateway, device))

        # In modes 1, 2, 4, 5 and 7 the F4USM61B battery telegram is sent
        # separately from the physical sender ID using A5-07-01. EEDTOY
        # exports that address as physical_unique_id. Create exactly one battery entity
        # per physical module even though two channel rows may reference it.
        if _is_f4usm61b_device(device) and _f4usm61b_mode(device) in {1, 2, 4, 5, 7}:
            physical_unique_id = _f4usm61b_physical_unique_id(device)
            if physical_unique_id and physical_unique_id not in f4usm61b_battery_ids:
                f4usm61b_battery_ids.add(physical_unique_id)
                entities.append(EltakoF4USM61BBatterySensor(gateway, device, physical_unique_id))

        # FSM60B operating mode 4 transmits its CR2032 battery level in
        # every A5-30-01 data and status telegram.
        if _is_fsm60b_mode4(device):
            entities.append(
                EltakoYamlValueSensor(
                    gateway,
                    device,
                    "battery_percentage",
                    "Batterie",
                    SensorDeviceClass.BATTERY,
                    PERCENTAGE,
                    state_class="measurement",
                )
            )

        if _is_fae14lpr_device(device) and eep == "F6-02-01":
            entities.append(EltakoFAE14LPRModeSensor(gateway, device))
            continue

        if _is_ffg7b_device(device):
            entities.extend(_ffg7b_entities(gateway, device))
            continue

        if _is_futh55ed_device(device):
            mode = _futh55ed_mode(device)
            if mode == "fhk" and eep == "A5-10-06":
                entities.extend(_a5_10_06_entities(gateway, device))
            elif mode == "fks_kp" and eep == "A5-20-01":
                entities.extend(_futh55ed_fks_kp_entities(gateway, device))
            elif mode == "fks_hora" and eep == "A5-20-04":
                entities.extend(_futh55ed_fks_hora_entities(gateway, device))
            elif mode == "two_point" and eep == "A5-38-08":
                entities.append(EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None))
            elif mode == "hygrostat" and eep == "A5-10-12":
                entities.extend(_futh55ed_hygrostat_entities(gateway, device))
            else:
                entities.append(EltakoYamlGenericSensor(gateway, device))
            continue

        if platform == "binary_sensor":
            if _is_frwb_device(device):
                entities.append(
                    EltakoYamlValueSensor(
                        gateway,
                        device,
                        "temperature",
                        "Temperatur",
                        SensorDeviceClass.TEMPERATURE,
                        UnitOfTemperature.CELSIUS,
                        state_class="measurement",
                    )
                )
            if eep in ("F6-02-01",):
                # FTS14EM inputs already have their dedicated E1..En binary
                # entities in binary_sensor.py. Do not recreate the old generic
                # rocker helper sensors (button, position, signal code, last seen).
                if not _is_fts14em_device(device):
                    entities.extend(_rocker_button_entities(gateway, device))
            elif eep == "D5-00-01":
                entities.extend(_d5_00_01_entities(gateway, device))
            elif eep == "A5-08-01":
                # Backward compatibility for older EEDTOY exports that used
                # platform: binary_sensor for FBH/FBHT. The physical device
                # carries voltage, brightness and temperature in the same frame.
                entities.extend(_a5_08_01_entities(gateway, device))
            elif eep == "A5-07-01":
                entities.extend(_a5_07_01_entities(gateway, device))
            continue

        if platform != "sensor":
            if platform == "climate" and eep == "A5-20-01":
                entities.extend(_a5_20_01_entities(gateway, device))
            continue

        if eep == "A5-13-01":
            entities.extend(_weather_entities(gateway, device))
        elif eep == "A5-12-01":
            entities.extend(_meter_entities(gateway, device))
        elif eep == "A5-08-01":
            entities.extend(_a5_08_01_entities(gateway, device))
        elif eep == "A5-10-06":
            entities.extend(_a5_10_06_entities(gateway, device))
        elif eep in ("A5-04-01", "A5-04-02", "A5-04-03"):
            entities.extend(_a5_04_entities(gateway, device))
        elif eep == "A5-09-0C":
            entities.extend(_a5_09_0c_entities(gateway, device))
        elif eep == "A5-09-04":
            entities.extend(_a5_09_04_entities(gateway, device))
        elif eep == "A5-20-01":
            entities.extend(_a5_20_01_entities(gateway, device))
        elif eep == "A5-07-01":
            entities.extend(_a5_07_01_entities(gateway, device))
        else:
            entities.append(EltakoYamlGenericSensor(gateway, device))

    for group_devices in flgtf_groups.values():
        entities.append(EltakoFlgtfLastSeenSensor(gateway, group_devices))

    if not devices and not entities:
        entities.extend(
            [
                EltakoValueSensor(gateway, "debug", "Last Temperature", "temperature"),
                EltakoValueSensor(gateway, "debug", "Last Brightness", "brightness"),
                EltakoValueSensor(gateway, "debug", "Last Voltage", "voltage"),
            ]
        )

    _remove_obsolete_weather_brightness_entities(hass, entry, devices)
    _remove_obsolete_d5_battery_entities(hass, entry, devices)
    _remove_obsolete_fbh_temperature_entities(hass, entry, devices)
    _remove_obsolete_gateway_path_entities(hass, entry)
    _remove_obsolete_flgtf_last_seen_entities(hass, entry, devices)
    _remove_obsolete_a5_04_03_generic_entities(hass, entry, devices)
    _remove_obsolete_fts14em_rocker_entities(hass, entry, devices)
    _migrate_flgtf_entity_ids(hass, entry, devices)

    _LOGGER.info(
        "ELTAKO sensor setup entry=%s imported_devices=%s sensor_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)



_FLGTF_ENTITY_SUFFIXES: dict[str, tuple[tuple[str, str], ...]] = {
    "A5-09-0C": (("TVOC", "tvoc"),),
    "A5-04-02": (
        ("Temperatur", "temperatur"),
        ("Luftfeuchtigkeit", "luftfeuchtigkeit"),
    ),
}


def _yaml_entity_unique_id(entry_id: str, device: dict[str, Any], suffix: str) -> str:
    base = f"{device_key(device)}_{suffix}".lower().replace(" ", "_").replace("/", "_")
    return f"{DOMAIN}_{entry_id}_{base}"


def _is_legacy_duplicated_flgtf_entity_id(entity_id: str) -> bool:
    object_id = str(entity_id or "").partition(".")[2]
    return (
        "flgtf_flgtf" in object_id
        or object_id.endswith("_tvoc_tvoc")
        or object_id.endswith("_temperatur_temperatur")
        or object_id.endswith("_luftfeuchtigkeit_luftfeuchtigkeit")
    )


def _migrate_flgtf_entity_ids(hass, entry, devices) -> None:
    """Rename only legacy auto-generated duplicated FLGTF entity IDs.

    Entity IDs are persistent in Home Assistant's entity registry. Correcting
    the runtime entity name alone therefore does not repair an already-created
    sensor.flgtf_flgtf_tvoc_tvoc. Match the stable unique ID and rename only
    known legacy duplicated IDs; deliberately customized entity IDs are left
    untouched.
    """
    registry = er.async_get(hass)
    for device in devices or []:
        if not isinstance(device, dict) or not _is_flgtf_device(device):
            continue
        eep = normalize_eep(device.get("eep"))
        suffixes = _FLGTF_ENTITY_SUFFIXES.get(eep, ())
        if not suffixes:
            continue
        device_name = _strip_flgtf_suffix(str(device.get("name") or "FLGTF"))
        device_slug = slugify(device_name) or "flgtf"
        for suffix, object_suffix in suffixes:
            unique_id = _yaml_entity_unique_id(entry.entry_id, device, suffix)
            current_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
            if not current_entity_id or not _is_legacy_duplicated_flgtf_entity_id(current_entity_id):
                continue
            desired_entity_id = f"sensor.{device_slug}_{object_suffix}"
            if current_entity_id == desired_entity_id:
                continue
            occupied = registry.async_get(desired_entity_id)
            if occupied is not None and occupied.entity_id != current_entity_id:
                _LOGGER.warning(
                    "Cannot migrate FLGTF entity %s to %s because the target already exists",
                    current_entity_id,
                    desired_entity_id,
                )
                continue
            try:
                registry.async_update_entity(current_entity_id, new_entity_id=desired_entity_id)
                _LOGGER.info("Migrated legacy FLGTF entity ID %s to %s", current_entity_id, desired_entity_id)
            except Exception:
                _LOGGER.exception("Failed to migrate legacy FLGTF entity ID %s", current_entity_id)


class EltakoDeviceAddressSensor(EltakoYamlEntity, SensorEntity):
    """Passive diagnostic sensor showing the configured ELTAKO/EnOcean address.

    This entity must never participate in gateway send/listen logic. It exists
    only to show the actor's configured id on the Home Assistant device page.
    """

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device, suffix="EnOcean-ID")
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_icon = "mdi:identifier"

    @property
    def native_value(self):
        value = self.device_config.get("id")
        return str(value).upper() if value not in (None, "") else None

def _gateway_status_entities(gateway) -> list[SensorEntity]:
    return [
        EltakoGatewayStatusSensor(gateway, "Id", "id"),
        EltakoGatewayStatusSensor(gateway, "Base Id", "base_id"),
        EltakoGatewayStatusSensor(gateway, "USB Serial", "usb_serial"),
        EltakoGatewayStatusSensor(gateway, "USB Interface", "usb_interface"),
        EltakoGatewayStatusSensor(gateway, "USB Protocol", "usb_protocol"),
        EltakoGatewayStatusSensor(gateway, "Message Delay", "message_delay"),
        EltakoGatewayStatusSensor(gateway, "Last Message Received", "last_message_received", timestamp=True),
    ]


class EltakoGatewayStatusSensor(EltakoGatewayEntity, SensorEntity):
    """Diagnostic/status sensor attached to the physical ELTAKO gateway."""

    def __init__(self, gateway, name: str, key: str, *, timestamp: bool = False) -> None:
        super().__init__(gateway, name, key)
        self.key = key
        self._timestamp = timestamp
        self._remove_listener = gateway.register_listener(self._handle_telegram)
        if timestamp:
            try:
                self._attr_device_class = SensorDeviceClass.TIMESTAMP
            except Exception:
                pass

    @property
    def native_value(self):
        if self.key == "id":
            info = getattr(self.gateway, "selected_gateway", {}) or {}
            if isinstance(info, dict) and info.get("id") is not None:
                return info.get("id")
            # Do not expose Home Assistant's opaque config-entry id as gateway id.
            # If no YAML gateway block is selected yet, the gateway id is unknown.
            return None
        if self.key == "base_id":
            return self.gateway.base_id or None
        if self.key == "serial_path":
            return self.gateway.port
        if self.key == "stable_serial_path":
            return getattr(self.gateway, "stable_serial_path", None) or self.gateway.port
        if self.key == "usb_serial":
            return getattr(self.gateway, "usb_serial", None)
        if self.key == "usb_interface":
            return getattr(self.gateway, "usb_interface", None)
        if self.key == "usb_protocol":
            return getattr(self.gateway, "usb_protocol", "ESP2")
        if self.key == "message_delay":
            return getattr(self.gateway, "message_delay", None)
        if self.key == "last_message_received":
            value = self.gateway.last_message_received
            if not value:
                return None
            try:
                return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except Exception:
                return value
        return None

    def _handle_telegram(self, telegram) -> None:
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()



def _rocker_button_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "button_label_de", "Gedrueckte Taste", None, None),
        EltakoYamlValueSensor(gateway, device, "button_position", "Tastenposition", None, None),
        EltakoYamlValueSensor(gateway, device, "signal_code", "Signalcode", None, None),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]

def _is_fws61_device(device: dict[str, Any]) -> bool:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    haystack = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("comment"),
            raw.get("name") if isinstance(raw, dict) else "",
            raw.get("device_type") if isinstance(raw, dict) else "",
            raw.get("comment") if isinstance(raw, dict) else "",
        )
    ).upper()
    return "FWS61" in haystack


def _weather_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    # A5-13-01 transmits separate telegram families:
    # - Identifier 0x01: dawn/twilight, temperature, wind, rain
    # - Identifier 0x02: sun/brightness west, south, east
    #
    # Do not create the legacy generic "Helligkeit" entity. For FWS61 it
    # duplicates the dawn value on identifier 0x01 and later gets overwritten
    # by the south value on identifier 0x02. Expose the clear ELTAKO values
    # instead: Daemmerung plus the three directional sun values.
    return [
        EltakoYamlValueSensor(gateway, device, "dawn_sensor", "Daemmerung", SensorDeviceClass.ILLUMINANCE, LUX_UNIT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "sun_west", "Helligkeit West", SensorDeviceClass.ILLUMINANCE, LUX_UNIT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "sun_south", "Helligkeit Sued", SensorDeviceClass.ILLUMINANCE, LUX_UNIT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "sun_east", "Helligkeit Ost", SensorDeviceClass.ILLUMINANCE, LUX_UNIT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "temperature", "Temperatur", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "wind_speed", "Windgeschwindigkeit", SensorDeviceClass.WIND_SPEED, KPH_UNIT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]



def _remove_obsolete_fts14em_rocker_entities(hass, entry, devices: list[dict[str, Any]]) -> None:
    """Remove legacy generic FTS14EM rocker helper sensors.

    FTS14EM has dedicated E1..En binary entities. Older builds also created
    four generic F6-02-01 helper sensors per input (button label, position,
    signal code and last telegram). They are redundant and must not remain in
    the Home Assistant entity registry after upgrading.
    """
    try:
        registry = er.async_get(hass)
    except Exception:
        return

    suffixes = (
        "Gedrueckte Taste",
        "Gedrückte Taste",
        "Tastenposition",
        "Signalcode",
        "Letztes Telegramm",
    )
    obsolete_unique_ids: set[str] = set()
    for device in devices or []:
        if not isinstance(device, dict) or not _is_fts14em_device(device):
            continue
        if normalize_eep(device.get("eep")) != "F6-02-01":
            continue
        for suffix in suffixes:
            obsolete_unique_ids.add(_yaml_entity_unique_id(entry.entry_id, device, suffix))

    for unique_id in obsolete_unique_ids:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if not entity_id:
            continue
        try:
            registry.async_remove(entity_id)
            _LOGGER.info("Removed obsolete FTS14EM helper entity %s", entity_id)
        except Exception:
            _LOGGER.exception("Failed to remove obsolete FTS14EM helper entity %s", entity_id)


def _remove_obsolete_gateway_path_entities(hass, entry) -> None:
    """Remove legacy gateway path sensors from the entity registry.

    v0.1.125/0.1.126 exposed the raw serial path and the normalized stable
    serial path as two separate diagnostic sensors. They are too long for the
    device page and duplicate internal resolver details. The resolver still
    uses stable /dev/serial/by-id paths internally.
    """
    try:
        registry = er.async_get(hass)
    except Exception:
        return

    obsolete_unique_ids = {
        f"{DOMAIN}_{entry.entry_id}_gateway_serial_path".lower(),
        f"{DOMAIN}_{entry.entry_id}_gateway_stable_serial_path".lower(),
    }

    for entity_entry in list(registry.entities.values()):
        unique_id = str(getattr(entity_entry, "unique_id", "") or "").lower()
        if unique_id in obsolete_unique_ids:
            _LOGGER.info("Removing obsolete gateway path diagnostic entity %s", entity_entry.entity_id)
            try:
                registry.async_remove(entity_entry.entity_id)
            except Exception:
                _LOGGER.exception("Failed to remove obsolete gateway path entity %s", entity_entry.entity_id)

def _remove_obsolete_d5_battery_entities(hass, entry, devices: list[dict[str, Any]]) -> None:
    """Remove battery voltage entities from D5 contact devices without battery."""
    try:
        registry = er.async_get(hass)
    except Exception:
        return

    obsolete_unique_ids: set[str] = set()
    for device in devices or []:
        if not isinstance(device, dict):
            continue
        eep = normalize_eep(device.get("eep"))
        # Remove old FTKE battery entities even after EEDTOY has been corrected
        # from D5-00-01 to F6-10-00.  FTKE does not send battery voltage.
        if eep not in ("D5-00-01", "F6-10-00"):
            continue
        if eep == "D5-00-01" and _d5_00_01_has_battery_voltage(device):
            continue
        obsolete_unique_ids.add(f"{DOMAIN}_{entry.entry_id}_{device_key(device)}_batteriespannung")
        # The previous wrong FTKE export used the same device address/name but
        # D5-00-01 in the unique_id.  Add that legacy key explicitly.
        if eep == "F6-10-00":
            legacy = dict(device)
            legacy["eep"] = "D5-00-01"
            obsolete_unique_ids.add(f"{DOMAIN}_{entry.entry_id}_{device_key(legacy)}_batteriespannung")

    for entity_entry in list(registry.entities.values()):
        unique_id = str(getattr(entity_entry, "unique_id", "") or "")
        if unique_id in obsolete_unique_ids:
            _LOGGER.info("Removing obsolete D5-00-01 battery voltage entity %s", entity_entry.entity_id)
            try:
                registry.async_remove(entity_entry.entity_id)
            except Exception:
                _LOGGER.exception("Failed to remove obsolete entity %s", entity_entry.entity_id)


def _remove_obsolete_weather_brightness_entities(hass, entry, devices: list[dict[str, Any]]) -> None:
    """Remove the legacy A5-13-01 generic brightness entity from registry.

    Older builds created a duplicate entity named "Helligkeit" for A5-13-01.
    It represented dawn in one telegram and south brightness in another, so it
    was ambiguous. Remove exactly this obsolete unique_id while keeping
    Helligkeit Ost/Sued/West.
    """
    try:
        registry = er.async_get(hass)
    except Exception:
        return

    obsolete_unique_ids: set[str] = set()
    for device in devices or []:
        if not isinstance(device, dict):
            continue
        if normalize_eep(device.get("eep")) != "A5-13-01":
            continue
        if normalize_platform(device.get("platform")) != "sensor":
            continue
        obsolete_unique_ids.add(f"{DOMAIN}_{entry.entry_id}_{device_key(device)}_helligkeit")

    if not obsolete_unique_ids:
        return

    for entity_entry in list(registry.entities.values()):
        unique_id = str(getattr(entity_entry, "unique_id", "") or "")
        if unique_id in obsolete_unique_ids:
            _LOGGER.info("Removing obsolete A5-13-01 generic brightness entity %s", entity_entry.entity_id)
            try:
                registry.async_remove(entity_entry.entity_id)
            except Exception:
                _LOGGER.exception("Failed to remove obsolete entity %s", entity_entry.entity_id)


def _remove_obsolete_fbh_temperature_entities(hass, entry, devices: list[dict[str, Any]]) -> None:
    """Remove legacy temperature only from non-temperature FBH devices.

    FBH55ESB leaves DB1 unused, while FBHT55ESB deliberately carries
    temperature in DB1. The previous cleanup treated both product variants as
    identical and therefore removed the valid FBHT temperature entity.
    """
    registry = er.async_get(hass)
    for device in devices or []:
        if not isinstance(device, dict) or normalize_eep(device.get("eep")) != "A5-08-01":
            continue
        if _is_fbht_device(device):
            continue
        unique_id = _yaml_entity_unique_id(entry.entry_id, device, "Temperatur")
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if not entity_id:
            continue
        try:
            registry.async_remove(entity_id)
            _LOGGER.info("Removed obsolete FBH A5-08-01 temperature entity %s", entity_id)
        except Exception:
            _LOGGER.exception("Failed to remove obsolete FBH temperature entity %s", entity_id)



def _remove_obsolete_a5_04_03_generic_entities(hass, entry, devices: list[dict[str, Any]]) -> None:
    """Remove the legacy raw-value FTFSB entity created before A5-04-03 support.

    Temperature, humidity and last-seen entities use stable suffixed unique IDs.
    The old unsuffixed generic entity only exposed the four raw data bytes and
    would otherwise remain as an unavailable duplicate after the upgrade.
    """
    try:
        registry = er.async_get(hass)
    except Exception:
        return

    obsolete_unique_ids = {
        f"{DOMAIN}_{entry.entry_id}_{device_key(device)}"
        for device in devices or []
        if isinstance(device, dict)
        and normalize_platform(device.get("platform")) == "sensor"
        and normalize_eep(device.get("eep")) == "A5-04-03"
    }
    for entity_entry in list(registry.entities.values()):
        unique_id = str(getattr(entity_entry, "unique_id", "") or "")
        if unique_id not in obsolete_unique_ids:
            continue
        try:
            registry.async_remove(entity_entry.entity_id)
            _LOGGER.info("Removed obsolete A5-04-03 raw-value entity %s", entity_entry.entity_id)
        except Exception:
            _LOGGER.exception("Failed to remove obsolete A5-04-03 entity %s", entity_entry.entity_id)


def _meter_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "energy_total", "Zaehlerstand", SensorDeviceClass.ENERGY, KWH_UNIT, state_class="total_increasing"),
        EltakoYamlValueSensor(gateway, device, "current_power", "Aktuelle Leistung", SensorDeviceClass.POWER, WATT_UNIT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]


def _a5_08_01_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    entities: list[SensorEntity] = [
        EltakoYamlValueSensor(gateway, device, "brightness", "Helligkeit", SensorDeviceClass.ILLUMINANCE, LUX_UNIT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "voltage", "Spannung", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, state_class="measurement"),
    ]
    if _is_fbht_device(device):
        entities.append(
            EltakoYamlValueSensor(
                gateway,
                device,
                "temperature",
                "Temperatur",
                SensorDeviceClass.TEMPERATURE,
                UnitOfTemperature.CELSIUS,
                state_class="measurement",
            )
        )
    entities.append(EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None))
    return entities


def _a5_07_01_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "movement_detection_mode", "Bewegungserkennung", None, None),
        EltakoYamlValueSensor(gateway, device, "battery_voltage", "Batteriespannung", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]


def _a5_10_06_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    """Room controller / temperature sensor values.

    Used by FTR55ESB/FTR55EHB/FTR65... style room controllers in FHK mode.
    The ELTAKO telegram table defines DB2 as setpoint temperature 0..40 C
    and DB1 as actual room temperature 0..40 C.
    """
    return [
        EltakoYamlValueSensor(gateway, device, "temperature", "Temperatur", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "target_temperature", "Solltemperatur", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "hvac_mode", "Betriebsart", None, None),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]



def _a5_04_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    entities: list[SensorEntity] = [
        EltakoYamlValueSensor(gateway, device, "temperature", "Temperatur", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "humidity", "Luftfeuchtigkeit", SensorDeviceClass.HUMIDITY, PERCENTAGE),
    ]
    if not _is_flgtf_device(device):
        entities.append(EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None))
    return entities


def _a5_09_0c_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    entities: list[SensorEntity] = [
        EltakoYamlValueSensor(gateway, device, "tvoc", "TVOC", VOC_DEVICE_CLASS, CONCENTRATION_PARTS_PER_BILLION, state_class="measurement"),
    ]
    if not _is_flgtf_device(device):
        entities.append(EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None))
    return entities


def _a5_09_04_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "carbon_dioxide", "CO2", CO2_DEVICE_CLASS, CONCENTRATION_PARTS_PER_MILLION, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "temperature", "Temperatur", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "humidity", "Luftfeuchtigkeit", SensorDeviceClass.HUMIDITY, PERCENTAGE, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]


def _futh55ed_fks_kp_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "target_temperature_command", "Solltemperaturvorgabe", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "valve_position_command", "Ventilvorgabe", None, PERCENTAGE, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "room_temperature_command", "Raumtemperaturvorgabe", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]


def _futh55ed_fks_hora_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "valve_position_command", "Ventilvorgabe", None, PERCENTAGE, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "target_temperature_command", "Solltemperaturvorgabe", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "control_raw", "Steuerdaten Rohwert", None, None),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]


def _futh55ed_hygrostat_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "temperature", "Temperatur", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "humidity", "Luftfeuchtigkeit", SensorDeviceClass.HUMIDITY, PERCENTAGE, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]


def _a5_20_01_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    return [
        EltakoYamlValueSensor(gateway, device, "temperature", "Temperatur", SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS),
        EltakoYamlValueSensor(gateway, device, "valve_position", "Ventilstellung", None, PERCENTAGE, state_class="measurement"),
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]

def _ffg7b_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    """Create the three-state FFG7B window sensor and diagnostics."""
    eep = normalize_eep(device.get("eep"))
    entities: list[SensorEntity] = [
        EltakoYamlEnumSensor(
            gateway,
            device,
            "window_state",
            "Fensterzustand",
            ("geschlossen", "gekippt", "offen"),
        ),
    ]
    if eep == "A5-14-09":
        entities.append(
            EltakoYamlValueSensor(
                gateway,
                device,
                "battery_voltage",
                "Batteriespannung",
                SensorDeviceClass.VOLTAGE,
                UnitOfElectricPotential.VOLT,
                state_class="measurement",
            )
        )
    entities.append(EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None))
    return entities


def _d5_00_01_has_battery_voltage(device: dict[str, Any]) -> bool:
    """Return true only for D5 devices that actually send battery voltage.

    FTKB sends an additional 4BS voltage telegram with the same ID.  FTKE does
    not have a battery voltage value, so creating a battery entity there is
    misleading and remains permanently unknown.
    """
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    haystack = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("comment"),
            raw.get("name") if isinstance(raw, dict) else "",
            raw.get("device_type") if isinstance(raw, dict) else "",
            raw.get("model") if isinstance(raw, dict) else "",
            raw.get("comment") if isinstance(raw, dict) else "",
        )
    ).upper()
    return "FTKB" in haystack and "FTKE" not in haystack


def _d5_00_01_entities(gateway, device: dict[str, Any]) -> list[SensorEntity]:
    entities: list[SensorEntity] = [
        EltakoYamlValueSensor(gateway, device, "last_seen", "Letztes Telegramm", None, None),
    ]
    if _d5_00_01_has_battery_voltage(device):
        entities.insert(
            0,
            EltakoYamlValueSensor(gateway, device, "battery_voltage", "Batteriespannung", SensorDeviceClass.VOLTAGE, UnitOfElectricPotential.VOLT),
        )
    return entities

def _configured_meter_tariffs(device: dict[str, Any]) -> set[int]:
    tariffs = device.get("meter_tariffs")
    if not tariffs:
        raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
        tariffs = raw.get("meter_tariffs") if isinstance(raw, dict) else None
    if not tariffs:
        return set()
    if not isinstance(tariffs, (list, tuple, set)):
        tariffs = [tariffs]
    result: set[int] = set()
    for tariff in tariffs:
        try:
            result.add(int(tariff))
        except (TypeError, ValueError):
            continue
    return result


A5_12_01_DB0_TYPED_METER_MODELS = {
    "FWZ14",
    "FWZ12",
    "F3Z14D",
    "DSZ14",
}


def _is_db0_typed_a5_12_01_meter(device: dict[str, Any]) -> bool:
    """Return true for ELTAKO A5-12-01 meters where DB0 is a telegram type.

    These devices use DB3..DB1 as 24-bit value and DB0 as fixed telegram type:
    0x09/0x19 = energy in 0.1 kWh, 0x0C/0x1C = momentary power in W.
    The tariff/channel information is already encoded by DB0, so the normal
    generic A5-12-01 bit-field filter must not block these telegrams.
    """
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    haystack = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("comment"),
            raw.get("name") if isinstance(raw, dict) else "",
            raw.get("device_type") if isinstance(raw, dict) else "",
            raw.get("comment") if isinstance(raw, dict) else "",
        )
    ).upper()
    return any(model in haystack for model in A5_12_01_DB0_TYPED_METER_MODELS)


# Backwards-compatible name used by older logic in this file.
def _is_f3z14d_device(device: dict[str, Any]) -> bool:
    return _is_db0_typed_a5_12_01_meter(device)



def _db0_typed_meter_telegram_type(decoded: dict[str, Any]) -> int | None:
    """Return A5-12-01 DB0 telegram type from decoded data_hex if available."""
    data_hex = decoded.get("data_hex") or decoded.get("value")
    if not data_hex:
        return None
    try:
        parts = str(data_hex).replace(":", "-").split("-")
        if len(parts) < 4:
            return None
        return int(parts[3], 16)
    except (TypeError, ValueError):
        return None


def _decode_db0_typed_a5_12_01_meter(device: dict[str, Any], decoded: dict[str, Any]) -> dict[str, Any]:
    """Decode ELTAKO-specific A5-12-01 DB0 telegram types.

    DB3..DB1 is a 24-bit value. DB0 selects the semantic value:
    0x09/0x19 = energy in 0.1 kWh, 0x0C/0x1C = momentary power in W.
    """
    if not _is_db0_typed_a5_12_01_meter(device):
        return {}

    db0 = _db0_typed_meter_telegram_type(decoded)
    if db0 is None:
        return {}

    try:
        raw_value = int(decoded.get("meter_raw_counter"))
    except (TypeError, ValueError):
        data_hex = decoded.get("data_hex") or decoded.get("value")
        try:
            db3, db2, db1, _ = [int(part, 16) for part in str(data_hex).replace(":", "-").split("-")[:4]]
            raw_value = (db3 << 16) | (db2 << 8) | db1
        except Exception:
            return {}

    if db0 == 0x09:
        return {
            "is_meter_reading": True,
            "energy_total": round(raw_value / 10.0, 1),
            "counter": raw_value,
            "tariff": "normal",
            "telegram_type": "energy_normal",
            "telegram_type_code": "0x09",
        }
    if db0 == 0x0C:
        return {
            "is_power_reading": True,
            "current_power": raw_value,
            "tariff": "normal",
            "telegram_type": "power_normal",
            "telegram_type_code": "0x0C",
        }
    if db0 == 0x19:
        return {
            "is_meter_reading": True,
            "energy_total": round(raw_value / 10.0, 1),
            "counter": raw_value,
            "tariff": "night",
            "telegram_type": "energy_night",
            "telegram_type_code": "0x19",
        }
    if db0 == 0x1C:
        return {
            "is_power_reading": True,
            "current_power": raw_value,
            "tariff": "night",
            "telegram_type": "power_night",
            "telegram_type_code": "0x1C",
        }
    return {"telegram_type": f"unknown_0x{db0:02X}", "telegram_type_code": f"0x{db0:02X}"}

def _meter_telegram_matches_config(device: dict[str, Any], decoded: dict[str, Any]) -> bool:
    # ELTAKO DB0-typed A5-12-01 meters encode tariff/value type directly in DB0.
    # For these devices meter_tariffs is a UI/YAML hint and must not reject valid
    # energy or power telegrams. Matching by physical sender/address happened in gateway.py.
    if _is_db0_typed_a5_12_01_meter(device):
        return True

    configured = _configured_meter_tariffs(device)
    if not configured:
        return True
    channel = decoded.get("measurement_channel")
    try:
        channel_int = int(channel)
    except (TypeError, ValueError):
        return False

    # Some Series-14 A5-12-01 meters report the default tariff/channel as 0
    # even when the older generated YAML contains meter_tariffs: [1]. Treat 0
    # as the default tariff for single-tariff meter devices.
    if channel_int == 0 and configured == {1}:
        return True

    return channel_int in configured


class EltakoYamlGenericSensor(EltakoYamlEntity, SensorEntity):
    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._value = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def native_value(self):
        return self._value

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return
        self._value = telegram.decoded.get("value") or telegram.decoded.get("raw")
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()



def _format_timestamp_seconds(value: Any) -> Any:
    """Return a clean local-time timestamp string without microseconds.

    Telegram timestamps are produced internally as timezone-aware UTC values.
    Home Assistant displays entity history in the user's local timezone. Convert
    the displayed diagnostic value to local time as well so the left value and
    the activity timestamp do not differ by the UTC offset.
    """
    if value in (None, ""):
        return value
    try:
        if isinstance(value, datetime):
            parsed = value
        else:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        if parsed.tzinfo is not None and dt_util is not None:
            parsed = dt_util.as_local(parsed)

        return parsed.replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        text = str(value)
        # Fast fallback for malformed ISO-like strings.
        if "T" in text:
            text = text.split("+", 1)[0].split("Z", 1)[0]
            if "." in text:
                text = text.split(".", 1)[0]
            return text.replace("T", " ")
        return value

def _decode_fco2tf65_from_telegram(telegram) -> dict[str, Any] | None:
    """Return a verified A5-09-04 payload from the original four data bytes."""
    decoded = getattr(telegram, "decoded", None)
    if not isinstance(decoded, dict):
        return None

    data: bytes | None = None
    data_hex = decoded.get("data_hex") or decoded.get("value")
    if isinstance(data_hex, str):
        try:
            candidate = bytes.fromhex(data_hex.replace("-", " ").replace(":", " "))
            if len(candidate) == 4:
                data = candidate
        except ValueError:
            data = None

    if data is None:
        raw = decoded.get("raw")
        if isinstance(raw, (list, tuple)) and len(raw) >= 4:
            try:
                data = bytes(int(value) & 0xFF for value in raw[:4])
            except (TypeError, ValueError):
                data = None

    if data is None:
        return None

    try:
        return decode_a5_09_04(data)
    except (TypeError, ValueError):
        return None


class EltakoFlgtfLastSeenSensor(EltakoYamlEntity, SensorEntity):
    """One combined last-seen timestamp for both FLGTF telegram profiles."""

    def __init__(self, gateway, devices: list[dict[str, Any]]) -> None:
        if not devices:
            raise ValueError("FLGTF last-seen sensor requires at least one device")
        primary = next(
            (device for device in devices if normalize_eep(device.get("eep")) == "A5-09-0C"),
            devices[0],
        )
        super().__init__(gateway, primary, name="Letztes Telegramm")
        self._attr_name = "Letztes Telegramm"
        base_id = _flgtf_device_base_id(primary) or str(primary.get("id") or "FLGTF").upper()
        safe_base_id = str(base_id).lower().replace("-", "_").replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_{gateway.entry_id}_flgtf_{safe_base_id}_last_seen"
        self._sender_ids = {
            str(device.get("id") or "").upper()
            for device in devices
            if str(device.get("id") or "").strip()
        }
        self._value = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)
        self._attr_extra_state_attributes["enocean_ids"] = sorted(self._sender_ids)
        self._attr_extra_state_attributes["profiles"] = sorted(
            {normalize_eep(device.get("eep")) for device in devices if device.get("eep")}
        )

    @property
    def native_value(self):
        return self._value

    def _handle_telegram(self, telegram) -> None:
        if str(getattr(telegram, "sender_id", "")).upper() not in self._sender_ids:
            return
        decoded = getattr(telegram, "decoded", None)
        if not isinstance(decoded, dict) or "last_seen" not in decoded:
            return
        self._value = _format_timestamp_seconds(decoded.get("last_seen"))
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()


def _remove_obsolete_flgtf_last_seen_entities(hass, entry, devices) -> None:
    """Remove the two former per-profile FLGTF last-seen entities.

    v0.1.145 and earlier created one timestamp for A5-09-0C and another for
    A5-04-02. Both are attached to the same physical FLGTF device, so Home
    Assistant displayed two identical rows. The new shared entity has a new
    stable unique ID and listens to both EnOcean addresses.
    """
    registry = er.async_get(hass)
    obsolete_unique_ids: set[str] = set()
    for device in devices or []:
        if not isinstance(device, dict) or not _is_flgtf_device(device):
            continue
        obsolete_unique_ids.add(_yaml_entity_unique_id(entry.entry_id, device, "Letztes Telegramm"))

    for unique_id in obsolete_unique_ids:
        entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
        if not entity_id:
            continue
        try:
            registry.async_remove(entity_id)
            _LOGGER.info("Removed obsolete per-profile FLGTF last-seen entity %s", entity_id)
        except Exception:
            _LOGGER.exception("Failed to remove obsolete FLGTF last-seen entity %s", entity_id)


class EltakoYamlEnumSensor(EltakoYamlEntity, SensorEntity):
    """Text sensor with a fixed set of valid states."""

    def __init__(
        self,
        gateway,
        device: dict[str, Any],
        key: str,
        suffix: str,
        options: tuple[str, ...],
    ) -> None:
        super().__init__(gateway, device, suffix=suffix)
        self.key = key
        self._value = None
        self._attr_device_class = getattr(SensorDeviceClass, "ENUM", None)
        self._attr_options = list(options)
        self._attr_icon = "mdi:window-open-variant"
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def native_value(self):
        return self._value

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return
        if _is_ffg7b_device(self.device_config):
            enrich_ffg7b_decoded(telegram.decoded)
        value = telegram.decoded.get(self.key)
        if value not in self._attr_options:
            return
        self._value = value
        self._attr_extra_state_attributes["tilted"] = bool(telegram.decoded.get("tilted"))
        self._attr_extra_state_attributes["open"] = bool(telegram.decoded.get("open"))
        for attr_key in (
            "data_hex",
            "configured_eep",
            "detected_eep",
            "data_layout",
            "window_state_raw",
            "window_state_normalized",
            "window_state_byte_index",
            "window_state_encoding",
        ):
            if attr_key in telegram.decoded:
                self._attr_extra_state_attributes[attr_key] = telegram.decoded[attr_key]
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()


class EltakoF4USM61BBatterySensor(EltakoYamlEntity, SensorEntity):
    """Battery voltage received from the F4USM61B physical sender ID."""

    def __init__(self, gateway, device: dict[str, Any], physical_unique_id: str) -> None:
        battery_device = dict(device)
        battery_device["id"] = physical_unique_id
        battery_device["eep"] = "A5-07-01"
        battery_device["platform"] = "sensor"
        battery_device["name"] = str(device.get("name") or "F4USM61B").split(" Kanal ")[0]
        super().__init__(gateway, battery_device, suffix="Batteriespannung")
        self._physical_unique_id = physical_unique_id.upper()
        self._value = None
        self._attr_device_class = SensorDeviceClass.VOLTAGE
        self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        if SensorStateClass is not None:
            self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_extra_state_attributes["battery_sender_id"] = self._physical_unique_id
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def native_value(self):
        return self._value

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != self._physical_unique_id:
            return

        # Always expose reception diagnostics, including the jumper/E2 learn
        # telegram.  The learn telegram confirms the physical sender ID but is
        # not a battery measurement and therefore must not be converted into a
        # voltage value.
        self._attr_extra_state_attributes["battery_sender_id"] = self._physical_unique_id
        self._attr_extra_state_attributes["learn_telegram"] = bool(
            telegram.decoded.get("learn_telegram")
        )
        for key in (
            "battery_raw",
            "data_hex",
            "telegram_type",
            "last_seen",
            "configured_eep",
            "detected_eep",
        ):
            if key in telegram.decoded:
                self._attr_extra_state_attributes[key] = telegram.decoded[key]

        value = telegram.decoded.get("battery_voltage", telegram.decoded.get("voltage"))
        if value is not None and not telegram.decoded.get("learn_telegram"):
            self._value = value
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()



class EltakoFAE14LPRModeSensor(EltakoYamlEntity, SensorEntity):
    """Bidirectional operating-mode feedback for one FAE14LPR channel."""

    _attr_icon = "mdi:radiator"

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device, suffix="Betriebsart")
        self._value = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def native_value(self):
        return self._value

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return
        mode = telegram.decoded.get("heating_mode")
        if mode is None:
            return
        self._value = telegram.decoded.get("heating_mode_label", mode)
        for key in (
            "heating_mode",
            "button_action",
            "signal_code",
            "temperature_reduction",
            "frost_protection",
            "last_seen",
        ):
            if key in telegram.decoded:
                self._attr_extra_state_attributes[key] = telegram.decoded[key]
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()

class EltakoYamlValueSensor(EltakoYamlEntity, SensorEntity):
    def __init__(
        self,
        gateway,
        device: dict[str, Any],
        key: str,
        suffix: str,
        device_class: SensorDeviceClass | None,
        unit: str | None,
        state_class: str | None = None,
    ) -> None:
        super().__init__(gateway, device, suffix=suffix)
        self.key = key
        self._value = None
        self._last_valid_numeric_value = None
        self._last_energy_sample_for_power = None
        self._last_energy_sample_ts = None
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = unit

        # Home Assistant can convert temperature sensors to the configured
        # unit system for display, for example to Fahrenheit. ELTAKO telegrams
        # and the integration semantics are Celsius-based, therefore we set a
        # suggested unit for every temperature value so entities stay displayed
        # as °C even on installations whose global unit system prefers °F.
        if device_class == SensorDeviceClass.TEMPERATURE or key in {"temperature", "target_temperature"}:
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_suggested_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif device_class == SensorDeviceClass.WIND_SPEED or key == "wind_speed":
            self._attr_native_unit_of_measurement = KPH_UNIT
            self._attr_suggested_unit_of_measurement = KPH_UNIT

        if state_class and SensorStateClass is not None:
            try:
                self._attr_state_class = getattr(SensorStateClass, state_class.upper())
            except Exception:
                self._attr_state_class = state_class
        elif state_class:
            self._attr_state_class = state_class
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def native_value(self):
        return self._value

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return

        configured_eep = normalize_eep(self.device_config.get("eep"))

        if _is_ffg7b_device(self.device_config):
            enrich_ffg7b_decoded(telegram.decoded)

        if configured_eep in {"A5-04-01", "A5-04-02", "A5-04-03"}:
            for attr_key in (
                "configured_eep",
                "detected_eep",
                "data_layout",
                "data_hex",
                "telegram_type",
                "event_triggered",
                "heartbeat",
                "temperature_raw_8bit",
                "temperature_raw_10bit",
                "humidity_raw_8bit",
            ):
                if attr_key in telegram.decoded:
                    self._attr_extra_state_attributes[attr_key] = telegram.decoded[attr_key]
            if self.key != "last_seen" and telegram.decoded.get("learn_telegram"):
                return

        if configured_eep == "A5-09-04" and self.key != "last_seen":
            verified = _decode_fco2tf65_from_telegram(telegram)
            if verified is not None:
                for attr_key in (
                    "data_hex",
                    "db3_humidity_raw",
                    "db2_co2_raw",
                    "db1_temperature_raw",
                    "db0_status_raw",
                    "telegram_type",
                ):
                    if attr_key in verified:
                        self._attr_extra_state_attributes[attr_key] = verified[attr_key]

                # A teach-in telegram has the same four-byte envelope as a data
                # telegram but carries no measurement. It must not reset any
                # FCO2TF65 entity.
                if verified.get("learn_telegram"):
                    return

                verified_key = "carbon_dioxide" if self.key in {"carbon_dioxide", "co2"} else self.key
                if verified_key not in verified:
                    return
                new_value = verified[verified_key]

                if verified_key == "carbon_dioxide":
                    try:
                        numeric_value = float(new_value)
                    except (TypeError, ValueError):
                        return
                    # A real indoor CO2 value cannot be 0 ppm. Some devices can
                    # briefly emit DB2=0 while starting up. Preserve the last
                    # valid reading instead of regressing the entity to zero.
                    if numeric_value <= 0:
                        _LOGGER.debug(
                            "Ignored empty FCO2TF65 CO2 frame for %s: decoded=%s",
                            self.device_config.get("name"),
                            verified,
                        )
                        return
                    self._last_valid_numeric_value = numeric_value

                self._value = new_value
                self.schedule_update_ha_state()
                return

            # Compatibility fallback for transports that do not expose data_hex.
            if self.key == "carbon_dioxide" and "carbon_dioxide" not in telegram.decoded and "co2" in telegram.decoded:
                telegram.decoded["carbon_dioxide"] = telegram.decoded["co2"]

        if configured_eep == "A5-12-01":
            if _is_db0_typed_a5_12_01_meter(self.device_config):
                db0_meter_decoded = _decode_db0_typed_a5_12_01_meter(self.device_config, telegram.decoded)
                if db0_meter_decoded:
                    telegram.decoded.update(db0_meter_decoded)

            # Match established behavior for meter devices: only the configured tariff/channel
            # is allowed to update numeric meter entities. A5-12-01 can transmit
            # cumulative energy and current power as separate telegram types.
            if self.key in {"energy_total", "counter"}:
                if not telegram.decoded.get("is_meter_reading", False):
                    _LOGGER.debug(
                        "Ignored A5-12-01 non-energy telegram for %s key=%s decoded=%s",
                        self.device_config.get("name"),
                        self.key,
                        telegram.decoded,
                    )
                    return
                if not _meter_telegram_matches_config(self.device_config, telegram.decoded):
                    _LOGGER.debug(
                        "Ignored A5-12-01 telegram because tariff/channel does not match for %s key=%s configured=%s decoded=%s",
                        self.device_config.get("name"),
                        self.key,
                        _configured_meter_tariffs(self.device_config),
                        telegram.decoded,
                    )
                    return
            elif self.key == "current_power":
                if not _meter_telegram_matches_config(self.device_config, telegram.decoded):
                    _LOGGER.debug(
                        "Ignored A5-12-01 power/derived-power telegram because tariff/channel does not match for %s configured=%s decoded=%s",
                        self.device_config.get("name"),
                        _configured_meter_tariffs(self.device_config),
                        telegram.decoded,
                    )
                    return

                # Prefer a real power telegram when present. Some meters, especially
                # S0 based F3Z14D channels, do not always deliver a separate power
                # value. For those devices we derive an average power from two
                # consecutive valid energy readings. This matches the practical
                # expectation in HA: the entity exists and updates as soon as the
                # counter advances, without corrupting the cumulative kWh value.
                if telegram.decoded.get("is_power_reading", False) and "current_power" in telegram.decoded:
                    new_value = telegram.decoded["current_power"]
                elif "energy_total" in telegram.decoded:
                    derived_power = self._derive_power_from_energy_sample(telegram.decoded)
                    if derived_power is None:
                        return
                    new_value = derived_power
                else:
                    return

                self._value = new_value
                self.schedule_update_ha_state()
                return

        if self.key not in telegram.decoded:
            return

        new_value = telegram.decoded[self.key]

        if self.key == "last_seen":
            new_value = _format_timestamp_seconds(new_value)

        if self.key == "hvac_mode":
            mode_map = {
                "heat": "Heizbetrieb",
                "heating": "Heizbetrieb",
                "off": "Aus",
                "cool": "Kuehlbetrieb",
                "cooling": "Kuehlbetrieb",
            }
            new_value = mode_map.get(str(new_value).lower(), new_value)

        if normalize_eep(self.device_config.get("eep")) == "A5-12-01" and self.key in {"energy_total", "counter"}:
            try:
                numeric_value = float(new_value)
            except (TypeError, ValueError):
                return

            # A5-12-01 meter channels are total-increasing. DSZ14DRS can emit
            # auxiliary/empty frames for the same EEP. Those frames must not
            # overwrite either the kWh value or the raw counter with 0.
            # Keep energy_total and Rohzaehler consistent: both only update on
            # valid, plausible meter telegrams for the configured tariff/channel.
            if self._last_valid_numeric_value is not None:
                if numeric_value == 0 and self._last_valid_numeric_value > 0:
                    _LOGGER.debug(
                        "Ignored zero A5-12-01 %s telegram for %s: last_valid=%s decoded=%s",
                        self.key,
                        self.device_config.get("name"),
                        self._last_valid_numeric_value,
                        telegram.decoded,
                    )
                    return
                if numeric_value < self._last_valid_numeric_value:
                    _LOGGER.debug(
                        "Ignored falling A5-12-01 %s telegram for %s: last_valid=%s new=%s decoded=%s",
                        self.key,
                        self.device_config.get("name"),
                        self._last_valid_numeric_value,
                        numeric_value,
                        telegram.decoded,
                    )
                    return

            self._last_valid_numeric_value = numeric_value

        self._value = new_value
        self.schedule_update_ha_state()


    def _derive_power_from_energy_sample(self, decoded: dict[str, Any]) -> float | None:
        """Derive average power in W from consecutive kWh readings.

        This is primarily useful for F3Z14D/S0 style channels. We only derive a
        value from positive counter deltas. Stable/repeated counter telegrams do
        not force power to 0 because absence of a pulse in one short interval is
        not a reliable zero-power measurement.
        """
        try:
            energy_kwh = float(decoded.get("energy_total"))
        except (TypeError, ValueError):
            return None

        raw_ts = decoded.get("last_seen")
        try:
            if raw_ts is None:
                ts = datetime.now().timestamp()
            else:
                ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00")).timestamp()
        except Exception:
            ts = datetime.now().timestamp()

        previous_energy = self._last_energy_sample_for_power
        previous_ts = self._last_energy_sample_ts
        self._last_energy_sample_for_power = energy_kwh
        self._last_energy_sample_ts = ts

        if previous_energy is None or previous_ts is None:
            return None

        delta_kwh = energy_kwh - previous_energy
        delta_seconds = ts - previous_ts

        if delta_kwh <= 0 or delta_seconds <= 0:
            return None

        watts = delta_kwh * 3_600_000.0 / delta_seconds

        # Reject impossible spikes caused by parser/clock glitches. 1 MW is far
        # above realistic S0 channel loads in this integration context.
        if watts <= 0 or watts > 1_000_000:
            _LOGGER.debug(
                "Ignored implausible derived A5-12-01 power for %s: watts=%s delta_kwh=%s delta_seconds=%s decoded=%s",
                self.device_config.get("name"),
                watts,
                delta_kwh,
                delta_seconds,
                decoded,
            )
            return None

        return round(watts, 1)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()


class EltakoValueSensor(EltakoBaseEntity, SensorEntity):
    def __init__(self, gateway, sender_id: str, name: str, key: str) -> None:
        super().__init__(gateway, sender_id, name)
        self.key = key
        self._value = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

        if key == "temperature":
            self._attr_device_class = SensorDeviceClass.TEMPERATURE
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            self._attr_suggested_unit_of_measurement = UnitOfTemperature.CELSIUS
        elif key == "voltage":
            self._attr_device_class = SensorDeviceClass.VOLTAGE
            self._attr_native_unit_of_measurement = UnitOfElectricPotential.VOLT
        elif key == "brightness":
            self._attr_device_class = SensorDeviceClass.ILLUMINANCE
            self._attr_native_unit_of_measurement = LUX_UNIT

    @property
    def native_value(self):
        return self._value

    def _handle_telegram(self, telegram) -> None:
        if self.key not in telegram.decoded:
            return
        self._value = telegram.decoded[self.key]
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
