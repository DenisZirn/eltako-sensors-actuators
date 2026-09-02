from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import re

import yaml

from .const import (
    CONNECTION_KIND_ENOCEAN_USB,
    CONNECTION_KIND_RS485_BUS,
    GATEWAY_TYPE_FAM14,
    GATEWAY_TYPE_FAM_USB,
    GATEWAY_TYPE_FGW14USB,
)


@dataclass(frozen=True, slots=True)
class ParsedYamlGateway:
    key: str
    label: str
    gateway: dict[str, Any]
    device_count: int


@dataclass(frozen=True, slots=True)
class ParsedYamlConfig:
    devices: list[dict[str, Any]]
    selected_gateway: dict[str, Any] | None
    gateway_count: int
    available_gateways: list[ParsedYamlGateway]


class EltakoYamlError(ValueError):
    """Raised when pasted EEDTOY YAML cannot be parsed."""


def parse_eedtoy_yaml(
    yaml_text: str | None,
    *,
    connection_kind: str | None = None,
    gateway_type: str | None = None,
    selected_gateway_key: str | None = None,
) -> ParsedYamlConfig:
    """Parse an EEDTOY/Home Assistant ELTAKO YAML export.

    A Home Assistant config entry represents one physical gateway. EEDTOY can
    export multiple gateway blocks, so this parser supports explicit gateway
    selection and only falls back to automatic selection when no gateway key was
    provided.
    """
    gateways = list_eedtoy_yaml_gateways(yaml_text)
    if not gateways:
        text = (yaml_text or "").strip()
        if not text:
            return ParsedYamlConfig(devices=[], selected_gateway=None, gateway_count=0, available_gateways=[])
        raise EltakoYamlError("YAML enthaelt keine gueltigen Gateways mit 'devices'.")

    selected = _select_gateway(gateways, connection_kind, gateway_type, selected_gateway_key)
    if selected is None:
        return ParsedYamlConfig(devices=[], selected_gateway=None, gateway_count=len(gateways), available_gateways=gateways)

    devices = _extract_devices(selected.gateway)
    return ParsedYamlConfig(
        devices=devices,
        selected_gateway=_compact_gateway(selected.gateway),
        gateway_count=len(gateways),
        available_gateways=gateways,
    )


def list_eedtoy_yaml_gateways(yaml_text: str | None) -> list[ParsedYamlGateway]:
    """Return all gateway sections in an EEDTOY/Home Assistant ELTAKO YAML export."""
    root = _load_yaml_root(yaml_text)
    gateways_raw = root.get("gateway")
    if not isinstance(gateways_raw, list):
        raise EltakoYamlError("YAML enthaelt keine 'eltako.gateway' Liste.")

    gateways: list[ParsedYamlGateway] = []
    for index, gateway in enumerate(gateways_raw):
        if not isinstance(gateway, dict):
            continue
        device_count = len(_extract_devices(gateway))
        if device_count <= 0:
            continue
        gateways.append(
            ParsedYamlGateway(
                key=_gateway_key(gateway, index),
                label=_gateway_label(gateway, index, device_count),
                gateway=gateway,
                device_count=device_count,
            )
        )
    return gateways


def _load_yaml_root(yaml_text: str | None) -> dict[str, Any]:
    text = (yaml_text or "").strip()
    if not text:
        return {}

    try:
        raw = yaml.safe_load(text)
    except Exception as err:
        raise EltakoYamlError(f"YAML konnte nicht gelesen werden: {err}") from err

    if not isinstance(raw, dict):
        raise EltakoYamlError("YAML muss ein Objekt mit 'eltako:' enthalten.")

    eltako = raw.get("eltako")
    if not isinstance(eltako, dict):
        raise EltakoYamlError("YAML enthaelt keinen gueltigen 'eltako:' Block.")

    return eltako


def _select_gateway(
    gateways: list[ParsedYamlGateway],
    connection_kind: str | None,
    gateway_type: str | None,
    selected_gateway_key: str | None,
) -> ParsedYamlGateway | None:
    if not gateways:
        return None

    if selected_gateway_key:
        for gateway in gateways:
            if gateway.key == selected_gateway_key:
                return gateway

    preferred_types: list[str] = []
    if gateway_type == GATEWAY_TYPE_FAM_USB or connection_kind == CONNECTION_KIND_ENOCEAN_USB:
        preferred_types = [GATEWAY_TYPE_FAM_USB]
    elif gateway_type in (GATEWAY_TYPE_FAM14, GATEWAY_TYPE_FGW14USB):
        preferred_types = [gateway_type]
    elif connection_kind == CONNECTION_KIND_RS485_BUS:
        preferred_types = [GATEWAY_TYPE_FAM14, GATEWAY_TYPE_FGW14USB]

    for preferred_type in preferred_types:
        for parsed_gateway in gateways:
            if str(parsed_gateway.gateway.get("device_type", "")).lower() == preferred_type:
                return parsed_gateway

    return gateways[0]


def _gateway_key(gateway: dict[str, Any], index: int) -> str:
    gateway_id = _clean_string(gateway.get("id")) or str(index + 1)
    device_type = (_clean_string(gateway.get("device_type")) or "unknown").lower()
    base_id = (_clean_string(gateway.get("base_id")) or "no-base").upper()
    return f"{index}:{gateway_id}:{device_type}:{base_id}"


def _gateway_label(gateway: dict[str, Any], index: int, device_count: int) -> str:
    gateway_id = _clean_string(gateway.get("id")) or str(index + 1)
    device_type = _clean_string(gateway.get("device_type")) or "unknown"
    base_id = _clean_string(gateway.get("base_id")) or "keine Base-ID"
    suffix = "Geraet" if device_count == 1 else "Geraete"
    return f"Gateway {gateway_id}: {device_type} / {base_id} - {device_count} {suffix}"


def _compact_gateway(gateway: dict[str, Any]) -> dict[str, Any]:
    # Keep optional USB identity fields when EEDTOY/YAML provides them.  They
    # are not required for normal single-gateway installs, but they make setups
    # with multiple FAM-USB/FTDI adapters deterministic across reboots because
    # /dev/ttyUSB* numbering is volatile.
    compact = {
        "id": gateway.get("id"),
        "device_type": gateway.get("device_type"),
        "base_id": gateway.get("base_id"),
    }
    for key in ("serial", "usb_serial", "serial_number", "interface", "usb_interface", "port", "by_id"):
        if gateway.get(key) not in (None, ""):
            compact[key] = gateway.get(key)
    return compact


def _normalize_eep(value: Any) -> str:
    text = str(value or "").strip().upper()
    match = re.search(r"(?:^|[^0-9A-F])([A-F0-9]{2}-[A-F0-9]{2}-[A-F0-9]{2})(?:$|[^0-9A-F])", text)
    return match.group(1) if match else text


def _normalize_enocean_id(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    parts = text.split("-")
    if len(parts) != 4:
        return None
    try:
        values = [int(part, 16) for part in parts]
    except ValueError:
        return None
    if any(value < 0 or value > 255 for value in values):
        return None
    return "-".join(f"{value:02X}" for value in values)


def _device_option(device: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in device and device.get(key) is not None:
        return device.get(key)
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return raw.get(key, default)


def _is_futh55ed_config(device: dict[str, Any]) -> bool:
    mode = _device_option(device, "room_controller_mode", None)
    if mode in (None, ""):
        mode = _device_option(device, "futh55ed_mode", "")
    if str(mode or "").strip():
        return True
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    text = " ".join(str(value or "") for value in (device.get("name"), device.get("model"), device.get("eltako"), raw.get("name"), raw.get("model"), raw.get("eltako"))).upper()
    return any(model in text for model in ("FUTH55ED", "FTR55", "FTR65", "FTRF65"))


def _is_fks_sv_config(device: dict[str, Any]) -> bool:
    return _normalize_eep(device.get("eep")) == "A5-20-01" and not _is_futh55ed_config(device)


def _validate_fks_sv_devices(devices: list[dict[str, Any]], gateway: dict[str, Any]) -> None:
    """Validate independent FKS-SV physical/controller ID assignments."""
    physical_seen: set[str] = set()
    sender_seen: dict[str, tuple[str, str | None, bool]] = {}
    effective_seen: dict[str, tuple[str, str | None, bool]] = {}
    gateway_type = str(gateway.get("device_type") or "").strip().lower()
    base_id = _normalize_enocean_id(gateway.get("base_id"))

    # A controller ID reserved for an FKS-SV must not also identify another
    # physical device or another actuator controller. Otherwise TX echoes and
    # radio commands become ambiguous even if the FKS-SV entries themselves are
    # unique.
    reserved_by_other_devices: dict[str, str] = {}
    for other in devices:
        if _is_fks_sv_config(other):
            continue
        other_name = str(other.get("name") or other.get("id") or "ELTAKO Geraet")
        for candidate_value in (other.get("id"), other.get("sender_id")):
            candidate = _normalize_enocean_id(candidate_value)
            if candidate:
                reserved_by_other_devices.setdefault(candidate, other_name)
                if gateway_type == GATEWAY_TYPE_FAM_USB and base_id and candidate_value == other.get("sender_id"):
                    base_parts = base_id.split("-")
                    sender_parts = candidate.split("-")
                    effective_candidate = "-".join((*base_parts[:3], sender_parts[3]))
                    reserved_by_other_devices.setdefault(effective_candidate, other_name)

    all_physical_unique_ids = {
        normalized
        for item in devices
        if (normalized := _normalize_enocean_id(item.get("id"))) is not None
    }

    for device in devices:
        if not _is_fks_sv_config(device):
            continue
        name = str(device.get("name") or device.get("id") or "FKS-SV")
        physical = _normalize_enocean_id(device.get("id"))
        sender = _normalize_enocean_id(device.get("sender_id"))
        if not physical:
            raise EltakoYamlError(f"FKS-SV '{name}' hat keine gueltige physische EnOcean-ID.")
        if not sender:
            raise EltakoYamlError(
                f"FKS-SV '{name}' benoetigt eine feste sender.id fuer Einlernen und Betrieb."
            )
        if physical in physical_seen:
            raise EltakoYamlError(f"FKS-SV Geraete-ID doppelt vergeben: {physical}.")
        physical_seen.add(physical)
        if sender in all_physical_unique_ids:
            raise EltakoYamlError(
                f"FKS-SV sender.id {sender} kollidiert mit einer physischen Geraete-ID."
            )
        other_owner = reserved_by_other_devices.get(sender)
        if other_owner:
            raise EltakoYamlError(
                f"FKS-SV sender.id {sender} wird bereits von '{other_owner}' verwendet."
            )

        group_value = _device_option(device, "controller_group")
        group = str(group_value).strip() if group_value not in (None, "") else None
        allow_shared = bool(_device_option(device, "allow_shared_sender", False))
        previous = sender_seen.get(sender)
        if previous is not None:
            previous_physical, previous_group, previous_shared = previous
            same_explicit_group = (
                allow_shared
                and previous_shared
                and group is not None
                and group == previous_group
            )
            if not same_explicit_group:
                raise EltakoYamlError(
                    f"FKS-SV sender.id {sender} ist fuer {previous_physical} und {physical} vergeben. "
                    "Jeder unabhaengige Raum benoetigt eine eigene sender.id."
                )
        else:
            sender_seen[sender] = (physical, group, allow_shared)

        # A FAM-USB can transmit only from its base-ID range. Detect collisions
        # after the low-byte sender offset is mapped into that range as well.
        effective = sender
        if gateway_type == GATEWAY_TYPE_FAM_USB and base_id:
            base_parts = base_id.split("-")
            sender_parts = sender.split("-")
            effective = "-".join((*base_parts[:3], sender_parts[3]))
        effective_other_owner = reserved_by_other_devices.get(effective)
        if effective_other_owner:
            raise EltakoYamlError(
                f"FKS-SV Controller-ID {effective} wird bereits von '{effective_other_owner}' verwendet."
            )
        previous_effective = effective_seen.get(effective)
        if previous_effective and previous_effective[0] != physical:
            previous_physical, previous_group, previous_shared = previous_effective
            same_explicit_group = (
                allow_shared
                and previous_shared
                and group is not None
                and group == previous_group
            )
            if not same_explicit_group:
                raise EltakoYamlError(
                    f"FKS-SV Controller-ID-Kollision im Gateway-Bereich: {effective} "
                    f"fuer {previous_physical} und {physical}."
                )
        else:
            effective_seen[effective] = (physical, group, allow_shared)


def _is_frgbw_device(device: dict[str, Any]) -> bool:
    name = str(device.get("name") or "").upper()
    eep = _normalize_eep(device.get("eep"))
    sender_eep = _normalize_eep(device.get("sender_eep"))
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    raw_text = " ".join(str(raw.get(k) or "") for k in ("name", "device_type", "comment", "model")).upper()
    return (
        eep in {"07-3F-7F"}
        or sender_eep in {"07-3F-7F"}
        or "FRGBW14" in name
        or "FRGBW71" in name
        or "FRGBW14" in raw_text
        or "FRGBW71" in raw_text
    )


def _strip_channel_suffix(name: str) -> str:
    import re

    text = str(name or "").strip()
    text = re.sub(r"\s*\((?:\d+)\s*/\s*(?:\d+)\)\s*$", "", text)
    text = re.sub(r"\s+Kanal\s*\d+\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+Channel\s*\d+\s*$", "", text, flags=re.IGNORECASE)
    return text.strip() or str(name or "FRGBW14")


def _channel_suffix(name: str) -> tuple[int | None, int | None]:
    import re

    match = re.search(r"\((\d+)\s*/\s*(\d+)\)\s*$", str(name or ""))
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _id_minus_channel_offset(device_id: Any, channel: int | None) -> str | None:
    if channel is None:
        return None
    text = str(device_id or "").strip().upper()
    parts = text.split("-")
    if len(parts) != 4:
        return None
    try:
        value = int("".join(parts), 16) - max(channel - 1, 0)
    except ValueError:
        return None
    if value < 0:
        return None
    return "-".join(f"{(value >> shift) & 0xFF:02X}" for shift in (24, 16, 8, 0))


def _address_plus_offset(address: Any, offset: int = 1) -> str | None:
    text = str(address or "").strip().upper()
    parts = text.split("-")
    if len(parts) != 4:
        return None
    try:
        value = int("".join(parts), 16) + int(offset)
    except (TypeError, ValueError):
        return None
    if not 0 <= value <= 0xFFFFFFFF:
        return None
    return "-".join(f"{(value >> shift) & 0xFF:02X}" for shift in (24, 16, 8, 0))


def _default_ha_sender_id_for_gateway(gateway: dict[str, Any]) -> str | None:
    # EEDTOY/older YAML may not contain a sender block for FRGBW14.
    # For Series-14 bus devices the Home Assistant sender must be an address
    # from the selected gateway base-id range. Use base_id + 1 as deterministic
    # default; explicit sender.id from YAML always wins.
    base_id = gateway.get("base_id") if isinstance(gateway, dict) else None
    return _address_plus_offset(base_id, 1)


def _ensure_frgbw_sender(device: dict[str, Any]) -> dict[str, Any]:
    if not _is_frgbw_device(device):
        return device
    if device.get("sender_id"):
        return device
    gateway = device.get("gateway") if isinstance(device.get("gateway"), dict) else {}
    sender_id = _default_ha_sender_id_for_gateway(gateway)
    if not sender_id:
        return device
    normalized = dict(device)
    normalized["sender_id"] = sender_id
    normalized["sender_eep"] = "07-3F-7F"
    raw = normalized.get("raw") if isinstance(normalized.get("raw"), dict) else {}
    raw = dict(raw)
    sender = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
    sender = dict(sender)
    sender.setdefault("id", sender_id)
    sender["eep"] = "07-3F-7F"
    raw["sender"] = sender
    raw["ha_sender_autogenerated"] = True
    normalized["raw"] = raw
    return normalized



def _frgbw_group_key(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    gateway = device.get("gateway") if isinstance(device.get("gateway"), dict) else {}
    gateway_key = f"{gateway.get('id') or ''}:{gateway.get('base_id') or ''}"

    for key in ("base_address", "pct14_address", "address", "entry_address"):
        value = raw.get(key)
        if value not in (None, ""):
            return f"{gateway_key}:frgbw:{value}"

    channel, total = _channel_suffix(str(device.get("name") or ""))
    base_id = _id_minus_channel_offset(device.get("id"), channel)
    if base_id:
        return f"{gateway_key}:frgbw:{base_id}"

    name = _strip_channel_suffix(str(device.get("name") or "")).upper()
    sender_id = str(device.get("sender_id") or "").upper()
    return f"{gateway_key}:frgbw:{name or sender_id or str(device.get('id') or '').upper()}"


def _normalize_frgbw_device(device: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(device)
    normalized["platform"] = "light"
    channel, total = _channel_suffix(str(normalized.get("name") or ""))
    base_id = _id_minus_channel_offset(normalized.get("id"), channel)
    base_name = _strip_channel_suffix(str(normalized.get("name") or "FRGBW14"))
    if base_id and "FRGBW" in base_name.upper():
        base_name = f"FRGBW14 {base_id}"
    normalized["name"] = base_name
    if base_id:
        normalized["id"] = base_id
    normalized["eep"] = "07-3F-7F"
    normalized["sender_eep"] = "07-3F-7F"
    raw = normalized.get("raw") if isinstance(normalized.get("raw"), dict) else {}
    raw = dict(raw)
    raw["logical_channels"] = 1
    raw["ha_color_control"] = "rgbw"
    raw["collapsed_frgbw_channels"] = True
    if "FRGBW14" in base_name.upper() and "FRGBW71" not in base_name.upper():
        # Old EEDTOY exports attached a radio learn payload to the bus actor.
        # The controller relation is configured in PCT14/YAML instead.
        raw.pop("teach_in_telegram", None)
    normalized["raw"] = raw
    return _ensure_frgbw_sender(normalized)


def _deduplicate_exact_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the last logical row for duplicate physical devices.

    Most devices are unique by physical ID plus EEP. FBH55ESB/FBHT55ESB and
    FUTH/FTR room controllers are special cases because their operating modes
    use different EEPs on the same physical transmitter. Keeping multiple modes
    makes the gateway lookup ambiguous, so the last selected mode wins.
    """
    result: list[dict[str, Any]] = []
    index_by_key: dict[tuple[str, str], int] = {}
    fbh_index_by_physical: dict[str, int] = {}
    room_controller_index_by_physical: dict[str, int] = {}
    for device in devices:
        physical = _normalize_enocean_id(device.get("id"))
        eep = _normalize_eep(device.get("eep"))
        if not physical or not eep:
            result.append(device)
            continue

        if eep in {"A5-07-01", "A5-08-01"}:
            previous_index = fbh_index_by_physical.get(physical)
            if previous_index is not None:
                result[previous_index] = device
                continue
            fbh_index_by_physical[physical] = len(result)

        if _is_futh55ed_config(device):
            previous_index = room_controller_index_by_physical.get(physical)
            if previous_index is not None:
                result[previous_index] = device
                continue
            room_controller_index_by_physical[physical] = len(result)

        key = (physical, eep)
        if key in index_by_key:
            result[index_by_key[key]] = device
        else:
            index_by_key[key] = len(result)
            result.append(device)
    return result


def _collapse_logical_devices(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse multi-channel FRGBW YAML exports to one logical HA light.

    Older older generated-style exports may list FRGBW14/71 as several light
    channels. The physical actuator is one RGBW device, so Home Assistant must
    create exactly one light entity and exactly one teach-in button.
    """
    result: list[dict[str, Any]] = []
    seen_frgbw: set[str] = set()

    for device in devices:
        if _is_frgbw_device(device):
            key = _frgbw_group_key(device)
            if key in seen_frgbw:
                continue
            seen_frgbw.add(key)
            result.append(_normalize_frgbw_device(device))
        else:
            result.append(device)

    return result




def _extract_devices(gateway: dict[str, Any]) -> list[dict[str, Any]]:
    device_root = gateway.get("devices")
    if not isinstance(device_root, dict):
        return []

    result: list[dict[str, Any]] = []
    gateway_info = _compact_gateway(gateway)

    for platform, items in device_root.items():
        platform_name = _clean_string(platform)
        if not platform_name or not isinstance(items, list):
            continue

        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue

            sender = item.get("sender") if isinstance(item.get("sender"), dict) else {}
            device = {
                "platform": platform_name,
                "id": _clean_string(item.get("id")),
                "eep": _clean_string(item.get("eep")),
                "name": _clean_string(item.get("name")) or f"ELTAKO {platform_name} {index + 1}",
                "device_class": _clean_string(item.get("device_class")),
                "sender_id": _clean_string(sender.get("id")),
                "sender_eep": _clean_string(sender.get("eep")),
                "meter_tariffs": _clean_int_list(item.get("meter_tariffs")),
                "room_temperature_entity": _clean_string(item.get("room_temperature_entity")),
                "min_target_temperature": item.get("min_target_temperature"),
                "max_target_temperature": item.get("max_target_temperature"),
                "initial_target_temperature": item.get("initial_target_temperature"),
                "auto_teach_in": item.get("auto_teach_in"),
                "fbht_temperature": item.get("fbht_temperature"),
                "ffg7b_three_state": item.get("ffg7b_three_state"),
                "device_family": _clean_string(item.get("device_family")),
                "base_id": _clean_string(item.get("base_id")),
                "physical_unique_id": _clean_string(item.get("physical_unique_id")),
                "operating_mode": item.get("operating_mode"),
                "id_range": _clean_string(item.get("id_range")),
                "input_number": item.get("input_number"),
                "id_count": item.get("id_count"),
                "id_offset_start": item.get("id_offset_start"),
                "channel_count": item.get("channel_count"),
                "room_controller_mode": _clean_string(item.get("room_controller_mode")),
                "futh55ed_mode": _clean_string(item.get("futh55ed_mode")),
                "teach_in_telegram": _clean_string(item.get("teach_in_telegram")),
                "hysteresis": item.get("hysteresis"),
                "frost_temperature": item.get("frost_temperature"),
                "dimming_speed": item.get("dimming_speed"),
                "bidirectional": item.get("bidirectional"),
                "summer_mode": item.get("summer_mode"),
                "controller_group": _clean_string(item.get("controller_group")),
                "allow_shared_sender": item.get("allow_shared_sender"),
                "gateway": gateway_info,
                "raw": _json_safe(item),
            }
            if device["id"] and device["eep"]:
                if _is_frgbw_device(device):
                    device = _ensure_frgbw_sender(device)
                result.append(device)

    deduplicated = _deduplicate_exact_devices(result)
    collapsed = _collapse_logical_devices(deduplicated)
    _validate_fks_sv_devices(collapsed, gateway)
    return collapsed


def _clean_int_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = [value]

    result: list[int] = []
    for item in raw_values:
        try:
            result.append(int(item))
        except (TypeError, ValueError):
            continue
    return result


def _clean_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
