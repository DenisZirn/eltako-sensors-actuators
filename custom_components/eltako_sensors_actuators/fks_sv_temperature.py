from __future__ import annotations

"""Shared FKS-SV room-temperature configuration and validation helpers."""

import math
from typing import Any

from .bus.ids import format_address, parse_address
from .const import (
    CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY,
    CONF_FKS_SV_ROOM_TEMPERATURE_OVERRIDES,
    CONF_FKS_SV_TEMPERATURE_SOURCE,
    FKS_SV_TEMPERATURE_SOURCE_EXTERNAL,
    FKS_SV_TEMPERATURE_SOURCE_INTERNAL,
)

FKS_SV_MIN_ROOM_TEMPERATURE_C = 0.0
FKS_SV_MAX_ROOM_TEMPERATURE_C = 40.0

_TEMP_UNITS_C = {"", "C", "°C", "CELSIUS"}
_TEMP_UNITS_F = {"F", "°F", "FAHRENHEIT"}


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


def is_fks_sv_device(device: Any) -> bool:
    """Identify a real FKS-SV and exclude room controllers sharing A5-20-01."""
    if not isinstance(device, dict):
        return False
    if str(device.get("eep") or "").strip().upper() != "A5-20-01":
        return False
    if str(device.get("platform") or "").strip().lower() != "climate":
        return False

    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    explicit_type = str(
        device.get("device_type")
        or raw.get("device_type")
        or ""
    ).strip().upper()
    if explicit_type:
        normalized_type = explicit_type.replace("_", "-").replace(" ", "")
        return "FKS-SV" in explicit_type or "FKSSV" in normalized_type.replace("-", "")

    # Legacy EEDTOY YAML did not always export device_type. Any explicit room
    # controller mode means this A5-20-01 entry is not the FKS-SV actuator.
    if str(_device_option(device, "room_controller_mode", "") or "").strip():
        return False
    if str(_device_option(device, "futh55ed_mode", "") or "").strip():
        return False

    legacy_text = " ".join(
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
    if any(marker in legacy_text for marker in ("FUTH", "FTR55", "FTR65", "FTRF65")):
        return False
    return True


def fks_sv_overrides(options: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    raw = (options or {}).get(CONF_FKS_SV_ROOM_TEMPERATURE_OVERRIDES, {})
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        normalized = normalize_enocean_id(key)
        if normalized is None or not isinstance(value, dict):
            continue
        source = str(value.get(CONF_FKS_SV_TEMPERATURE_SOURCE) or "").strip().lower()
        if source not in {
            FKS_SV_TEMPERATURE_SOURCE_INTERNAL,
            FKS_SV_TEMPERATURE_SOURCE_EXTERNAL,
        }:
            continue
        item = {CONF_FKS_SV_TEMPERATURE_SOURCE: source}
        entity_id = str(value.get(CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY) or "").strip()
        if entity_id:
            item[CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY] = entity_id
        result[normalized] = item
    return result


def set_fks_sv_override(
    options: dict[str, Any] | None,
    device_id: Any,
    source: str,
    external_entity_id: str | None = None,
) -> dict[str, Any]:
    """Return a new options dict with one persistent physical-device override."""
    normalized = normalize_enocean_id(device_id)
    if normalized is None:
        raise ValueError("Invalid FKS-SV physical EnOcean ID")
    source = str(source or "").strip().lower()
    if source not in {
        FKS_SV_TEMPERATURE_SOURCE_INTERNAL,
        FKS_SV_TEMPERATURE_SOURCE_EXTERNAL,
    }:
        raise ValueError("Invalid FKS-SV temperature source")

    result = dict(options or {})
    mapping = fks_sv_overrides(result)
    item: dict[str, str] = {CONF_FKS_SV_TEMPERATURE_SOURCE: source}
    entity_id = str(external_entity_id or "").strip()
    if source == FKS_SV_TEMPERATURE_SOURCE_EXTERNAL:
        if not entity_id:
            raise ValueError("External FKS-SV temperature source requires an entity")
        item[CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY] = entity_id
    mapping[normalized] = item
    result[CONF_FKS_SV_ROOM_TEMPERATURE_OVERRIDES] = mapping
    return result


def resolve_fks_sv_temperature_config(
    device: dict[str, Any],
    options: dict[str, Any] | None,
) -> tuple[str, str | None, str]:
    """Resolve UI override > legacy YAML > internal default.

    Returns (source, external_entity_id, origin), where origin is one of
    "ui", "yaml" or "default".
    """
    physical_id = normalize_enocean_id(device.get("id"))
    if physical_id is not None:
        override = fks_sv_overrides(options).get(physical_id)
        if override is not None:
            source = override[CONF_FKS_SV_TEMPERATURE_SOURCE]
            entity_id = override.get(CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY)
            return source, entity_id, "ui"

    yaml_entity = str(_device_option(device, "room_temperature_entity", "") or "").strip()
    if yaml_entity:
        return FKS_SV_TEMPERATURE_SOURCE_EXTERNAL, yaml_entity, "yaml"
    return FKS_SV_TEMPERATURE_SOURCE_INTERNAL, None, "default"


def temperature_to_celsius(value: Any, unit: Any = None) -> float | None:
    """Convert a Home Assistant sensor value to valid A5-20-01 Celsius.

    Missing/unknown/non-finite values and values outside 0..40 °C are invalid;
    they are never clamped because clamping could silently transmit a false
    controller room temperature.
    """
    text = str(value or "").strip()
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
    if not FKS_SV_MIN_ROOM_TEMPERATURE_C <= temperature <= FKS_SV_MAX_ROOM_TEMPERATURE_C:
        return None
    return round(temperature, 2)


def select_fks_sv_room_temperature(
    configured_source: str,
    external_temperature: float | None,
    internal_temperature: float | None,
) -> tuple[float | None, str, str | None]:
    """Choose room temperature and report (value, status, actual_source)."""
    external = temperature_to_celsius(external_temperature, "°C")
    internal = temperature_to_celsius(internal_temperature, "°C")
    if configured_source == FKS_SV_TEMPERATURE_SOURCE_EXTERNAL:
        if external is not None:
            return external, "normal", FKS_SV_TEMPERATURE_SOURCE_EXTERNAL
        if internal is not None:
            return internal, "fallback", FKS_SV_TEMPERATURE_SOURCE_INTERNAL
        return None, "error", None

    if internal is not None:
        return internal, "normal", FKS_SV_TEMPERATURE_SOURCE_INTERNAL
    return None, "error", None
