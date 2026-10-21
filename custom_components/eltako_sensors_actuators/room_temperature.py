from __future__ import annotations

"""Shared room-temperature assignment helpers for ELTAKO climate actuators."""

import math
from typing import Any

from .bus.ids import format_address, parse_address
from .const import (
    CONF_EXTERNAL_TEMPERATURE_ENTITY,
    CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY,
    CONF_FKS_SV_ROOM_TEMPERATURE_OVERRIDES,
    CONF_FKS_SV_TEMPERATURE_SOURCE,
    CONF_ROOM_TEMPERATURE_OVERRIDES,
    CONF_ROOM_TEMPERATURE_SOURCE,
    ROOM_TEMPERATURE_SOURCE_EXTERNAL,
    ROOM_TEMPERATURE_SOURCE_NATIVE,
)

MIN_ROOM_TEMPERATURE_C = 0.0
MAX_ROOM_TEMPERATURE_C = 40.0

_TEMP_UNITS_C = {"", "C", "°C", "CELSIUS"}
_TEMP_UNITS_F = {"F", "°F", "FAHRENHEIT"}

ASSIGNABLE_A5_10_06_TYPES = (
    "FHK14",
    "F4HK14",
    "FAE14LPR",
    "FAE14SSR",
)


def normalize_enocean_id(value: Any) -> str | None:
    """Return canonical XX-XX-XX-XX EnOcean ID or None."""
    try:
        return format_address(parse_address(str(value or "").strip())).upper()
    except Exception:
        return None


def _device_option(device: dict[str, Any], key: str, default: Any = None) -> Any:
    if not isinstance(device, dict):
        return default
    if key in device and device.get(key) is not None:
        return device.get(key)
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return raw.get(key, default)


def technical_device_type(device: Any) -> str:
    if not isinstance(device, dict):
        return ""
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return str(device.get("device_type") or raw.get("device_type") or "").strip().upper()


def _legacy_device_text(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("model"),
            device.get("eltako"),
            device.get("device_family"),
            raw.get("name"),
            raw.get("model"),
            raw.get("eltako"),
            raw.get("device_family"),
        )
    ).upper()


def is_fks_sv_device(device: Any) -> bool:
    """Identify a real FKS-SV and exclude room controllers sharing A5-20-01."""
    if not isinstance(device, dict):
        return False
    if str(device.get("eep") or "").strip().upper() != "A5-20-01":
        return False
    if str(device.get("platform") or "").strip().lower() != "climate":
        return False

    explicit_type = technical_device_type(device)
    if explicit_type:
        normalized_type = explicit_type.replace("_", "-").replace(" ", "")
        return "FKS-SV" in explicit_type or "FKSSV" in normalized_type.replace("-", "")

    if str(_device_option(device, "room_controller_mode", "") or "").strip():
        return False
    if str(_device_option(device, "futh55ed_mode", "") or "").strip():
        return False

    legacy_text = _legacy_device_text(device)
    if any(marker in legacy_text for marker in ("FUTH", "FTR55", "FTR65", "FTRF65")):
        return False
    return True


def is_a5_10_06_heating_actuator(device: Any) -> bool:
    """Return True for FHK14/F4HK14/FAE14 climate actuators, never room controllers."""
    if not isinstance(device, dict):
        return False
    if str(device.get("platform") or "").strip().lower() != "climate":
        return False
    if str(device.get("eep") or "").strip().upper() != "A5-10-06":
        return False

    explicit_type = technical_device_type(device)
    if explicit_type:
        if any(marker in explicit_type for marker in ("FUTH", "FTR55", "FTR65", "FTRF65")):
            return False
        return any(marker in explicit_type for marker in ASSIGNABLE_A5_10_06_TYPES)

    legacy = _legacy_device_text(device)
    if any(marker in legacy for marker in ("FUTH", "FTR55", "FTR65", "FTRF65")):
        return False
    return any(marker in legacy for marker in ASSIGNABLE_A5_10_06_TYPES)


def is_room_temperature_assignable_device(device: Any) -> bool:
    return is_fks_sv_device(device) or is_a5_10_06_heating_actuator(device)


def room_temperature_device_kind(device: Any) -> str | None:
    if is_fks_sv_device(device):
        return "fks_sv"
    if is_a5_10_06_heating_actuator(device):
        return "a5_10_06"
    return None


def room_temperature_overrides(options: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """Read generalized overrides and migrate the first FKS-SV-only test key."""
    options = options or {}
    raw = options.get(CONF_ROOM_TEMPERATURE_OVERRIDES)
    if not isinstance(raw, dict):
        raw = options.get(CONF_FKS_SV_ROOM_TEMPERATURE_OVERRIDES, {})
    if not isinstance(raw, dict):
        return {}

    result: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        normalized = normalize_enocean_id(key)
        if normalized is None or not isinstance(value, dict):
            continue
        source = str(
            value.get(CONF_ROOM_TEMPERATURE_SOURCE)
            or value.get("fks_sv_temperature_source")
            or value.get(CONF_FKS_SV_TEMPERATURE_SOURCE)
            or ""
        ).strip().lower()
        if source not in {ROOM_TEMPERATURE_SOURCE_NATIVE, ROOM_TEMPERATURE_SOURCE_EXTERNAL}:
            continue
        item = {CONF_ROOM_TEMPERATURE_SOURCE: source}
        entity_id = str(
            value.get(CONF_EXTERNAL_TEMPERATURE_ENTITY)
            or value.get("fks_sv_external_temperature_entity")
            or value.get(CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY)
            or ""
        ).strip()
        if entity_id:
            item[CONF_EXTERNAL_TEMPERATURE_ENTITY] = entity_id
        result[normalized] = item
    return result


def set_room_temperature_override(
    options: dict[str, Any] | None,
    device_id: Any,
    source: str,
    external_entity_id: str | None = None,
) -> dict[str, Any]:
    """Return a new options dict with one persistent physical-device override."""
    normalized = normalize_enocean_id(device_id)
    if normalized is None:
        raise ValueError("Invalid physical EnOcean ID")
    source = str(source or "").strip().lower()
    if source not in {ROOM_TEMPERATURE_SOURCE_NATIVE, ROOM_TEMPERATURE_SOURCE_EXTERNAL}:
        raise ValueError("Invalid room-temperature source")

    result = dict(options or {})
    mapping = room_temperature_overrides(result)
    item: dict[str, str] = {CONF_ROOM_TEMPERATURE_SOURCE: source}
    entity_id = str(external_entity_id or "").strip()
    if source == ROOM_TEMPERATURE_SOURCE_EXTERNAL:
        if not entity_id:
            raise ValueError("External room-temperature source requires an entity")
        item[CONF_EXTERNAL_TEMPERATURE_ENTITY] = entity_id
    mapping[normalized] = item
    result[CONF_ROOM_TEMPERATURE_OVERRIDES] = mapping
    # Remove the short-lived FKS-SV-only test mapping after successful save.
    result.pop(CONF_FKS_SV_ROOM_TEMPERATURE_OVERRIDES, None)
    return result


def resolve_room_temperature_config(
    device: dict[str, Any],
    options: dict[str, Any] | None,
) -> tuple[str, str | None, str]:
    """Resolve UI override > legacy YAML > native/default source."""
    physical_id = normalize_enocean_id(device.get("id"))
    if physical_id is not None:
        override = room_temperature_overrides(options).get(physical_id)
        if override is not None:
            source = override[CONF_ROOM_TEMPERATURE_SOURCE]
            entity_id = override.get(CONF_EXTERNAL_TEMPERATURE_ENTITY)
            return source, entity_id, "ui"

    yaml_entity = str(_device_option(device, "room_temperature_entity", "") or "").strip()
    if yaml_entity:
        return ROOM_TEMPERATURE_SOURCE_EXTERNAL, yaml_entity, "yaml"
    return ROOM_TEMPERATURE_SOURCE_NATIVE, None, "default"


def temperature_to_celsius(value: Any, unit: Any = None) -> float | None:
    """Convert a Home Assistant state to a valid 0..40 °C protocol value."""
    text = "" if value is None else str(value).strip()
    if not text or text.lower() in {"unknown", "unavailable", "none", "nan"}:
        return None
    try:
        temperature = float(text)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(temperature):
        return None

    normalized_unit = str(unit or "").strip().upper()
    if normalized_unit in _TEMP_UNITS_F:
        temperature = (temperature - 32.0) * 5.0 / 9.0
    elif normalized_unit not in _TEMP_UNITS_C:
        return None

    if not math.isfinite(temperature):
        return None
    if not MIN_ROOM_TEMPERATURE_C <= temperature <= MAX_ROOM_TEMPERATURE_C:
        return None
    return round(temperature, 2)


def select_numeric_room_temperature(
    configured_source: str,
    external_temperature: float | None,
    native_temperature: float | None,
) -> tuple[float | None, str, str | None]:
    """Select an actual numeric temperature when a protocol requires one.

    Used by FKS-SV: invalid external values fall back to the valve's own
    temperature. For A5-10-06 actuators, native control does not require a
    numeric temperature and is handled separately in climate.py.
    """
    external = temperature_to_celsius(external_temperature, "°C")
    native = temperature_to_celsius(native_temperature, "°C")
    if configured_source == ROOM_TEMPERATURE_SOURCE_EXTERNAL:
        if external is not None:
            return external, "normal", ROOM_TEMPERATURE_SOURCE_EXTERNAL
        if native is not None:
            return native, "fallback", ROOM_TEMPERATURE_SOURCE_NATIVE
        return None, "error", None

    if native is not None:
        return native, "normal", ROOM_TEMPERATURE_SOURCE_NATIVE
    return None, "error", None


# Compatibility aliases used by the first FKS-SV-only v0.1.164 test build.
fks_sv_overrides = room_temperature_overrides
set_fks_sv_override = set_room_temperature_override
resolve_fks_sv_temperature_config = resolve_room_temperature_config
select_fks_sv_room_temperature = select_numeric_room_temperature
