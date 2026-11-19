"""Per-actuator A5-10-06 controller priority; independent of climate presets.

Only the user selection is persisted. Neither a successful serial write nor a
restored selection is evidence that a physical actuator applied the setting.
"""
from __future__ import annotations

from typing import Any

from .room_temperature import (
    normalize_enocean_id,
    resolve_room_temperature_config,
)
from .const import ROOM_TEMPERATURE_SOURCE_EXTERNAL

PRIORITY_OPTIONS = {
    "central": "Zentral (C)",
    "auto": "Automatisch (A)",
    "manual": "Manuell (M)",
    "limit": "Begrenzt ±3 K (L)",
}
PRIORITY_BYTES = {"central": 0x08, "auto": 0x0E, "limit": 0x0A}
CONF_HEATING_PRIORITY_OVERRIDES = "heating_priority_overrides"
SIGNAL_HEATING_PRIORITY_TX = "eltako_sensors_actuators_heating_priority_tx"

_HEATING_MODELS = ("FHK14", "F4HK14", "FAE14LPR", "FAE14SSR")


def _device_option(device: dict[str, Any], key: str, default: Any = None) -> Any:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return device.get(key) if device.get(key) is not None else raw.get(key, default)


def supports_heating_priority(device: dict[str, Any]) -> bool:
    """Priorities C/A/M/L are verified for Series-14 controller assignments."""
    if str(device.get("platform") or "").lower() != "climate":
        return False
    if str(device.get("eep") or "").upper() != "A5-10-06":
        return False
    model = str(_device_option(device, "device_type", "") or "").upper()
    if not model:
        model = str(device.get("name") or "").upper()
    return any(model.startswith(prefix) for prefix in _HEATING_MODELS)


def heating_control_mode(device: dict[str, Any], options: dict[str, Any]) -> str:
    """Use an explicit EEDTOY mode; legacy configurations use the source."""
    explicit = str(_device_option(device, "heating_control_mode", "") or "").lower()
    if explicit in ("ha_external", "learned_sensor"):
        return explicit
    source, _sensor, _origin = resolve_room_temperature_config(device, options)
    return "ha_external" if source == ROOM_TEMPERATURE_SOURCE_EXTERNAL else "learned_sensor"


def priority_mode(device: dict[str, Any], options: dict[str, Any]) -> str:
    if heating_control_mode(device, options) == "ha_external":
        # Never change the verified F4HK14 Function-64 controller path.
        # For legacy YAML with explicit priority, retain its old behavior.
        if _device_option(device, "heating_control_mode") == "ha_external":
            return "auto"
        legacy = str(_device_option(device, "priority", "") or "").lower()
        return {"ha": "central", "home_automation": "central", "limit": "limit"}.get(legacy, "auto")

    physical_id = normalize_enocean_id(device.get("id"))
    overrides = options.get(CONF_HEATING_PRIORITY_OVERRIDES)
    if physical_id and isinstance(overrides, dict):
        stored = overrides.get(physical_id)
        if stored in PRIORITY_OPTIONS:
            return stored
    legacy = str(_device_option(device, "priority", "auto") or "auto").lower()
    return {
        "ha": "central", "home_automation": "central", "home_assistant": "central",
        "software": "central", "0x08": "central", "8": "central",
        "limit": "limit", "limited": "limit", "0x0a": "limit", "10": "limit",
        "manual": "manual",
    }.get(legacy, "auto")


def set_priority_mode(hass: Any, entry_id: str, device: dict[str, Any], mode: str) -> None:
    if mode not in PRIORITY_OPTIONS:
        raise ValueError("Unsupported heating priority")
    physical_id = normalize_enocean_id(device.get("id"))
    if not physical_id:
        raise ValueError("Missing physical actuator ID")
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        raise ValueError("Integration entry not found")
    options = dict(entry.options)
    previous = options.get(CONF_HEATING_PRIORITY_OVERRIDES)
    overrides = dict(previous) if isinstance(previous, dict) else {}
    if overrides.get(physical_id) == mode:
        return
    overrides[physical_id] = mode
    options[CONF_HEATING_PRIORITY_OVERRIDES] = overrides
    hass.config_entries.async_update_entry(entry, options=options)
