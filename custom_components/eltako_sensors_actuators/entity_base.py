from __future__ import annotations

from typing import Any
import re

from homeassistant.helpers.entity import DeviceInfo, Entity

from .const import DOMAIN


def normalize_platform(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def normalize_eep(value: Any) -> str:
    """Return the canonical RORG-FUNC-TYPE part from an EEP value.

    EEDTOY exports may append a device suffix, for example
    ``A5-04-03-FTFSB`` or ``A5-30-01-FSM60B``. Home Assistant routing and
    decoders must still receive the canonical EEP.
    """
    text = str(value or "").strip().upper()
    match = re.search(r"(?:^|[^0-9A-F])([A-F0-9]{2}-[A-F0-9]{2}-[A-F0-9]{2})(?:$|[^0-9A-F])", text)
    return match.group(1) if match else text


def device_key(device: dict[str, Any]) -> str:
    gateway = device.get("gateway") if isinstance(device.get("gateway"), dict) else {}
    gateway_id = gateway.get("id") or gateway.get("device_type") or "gateway"
    return (
        f"{gateway_id}_{normalize_platform(device.get('platform'))}_{device.get('id')}_{device.get('eep')}"
        .lower()
        .replace(" ", "_")
        .replace("/", "_")
    )


def gateway_device_name(gateway) -> str:
    """Return the Home Assistant device name for the configured ELTAKO gateway."""
    info = getattr(gateway, "selected_gateway", None) or {}
    if not isinstance(info, dict):
        info = {}

    gateway_id = info.get("id")
    device_type = str(info.get("device_type") or getattr(gateway, "gateway_type", None) or "gateway").lower()
    base_id = info.get("base_id") or getattr(gateway, "base_id", None)

    label = f"EnOcean Gateway - {device_type}"
    details = []
    if gateway_id is not None and str(gateway_id).strip():
        details.append(f"Id: {gateway_id}")
    if base_id:
        details.append(f"BaseId: {base_id}")
    if details:
        label += f" ({', '.join(details)})"
    return label


def gateway_model(gateway) -> str:
    info = getattr(gateway, "selected_gateway", None) or {}
    if not isinstance(info, dict):
        info = {}
    device_type = str(info.get("device_type") or getattr(gateway, "gateway_type", None) or "Gateway").upper()
    return f"EnOcean Gateway - {device_type}"


def _id_with_offset(device_id: Any, offset: int) -> str | None:
    text = str(device_id or "").strip().upper()
    parts = text.split("-")
    if len(parts) != 4:
        return None
    try:
        value = int("".join(parts), 16) + int(offset)
    except ValueError:
        return None
    if not 0 <= value <= 0xFFFFFFFF:
        return None
    return "-".join(f"{(value >> shift) & 0xFF:02X}" for shift in (24, 16, 8, 0))


def _strip_flgtf_suffix(name: str) -> str:
    import re

    text = str(name or "FLGTF").strip()
    text = re.sub(r"\s+(TVOC|LUFTGÜTE|LUFTGUETE|TEMPERATUR\s*\+?\s*FEUCHTE|TEMPERATUR|FEUCHTE)$", "", text, flags=re.IGNORECASE)
    return text.strip() or "FLGTF"




def _bool_option(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "ja"}
    return bool(value)


def _is_f4usm61b_device(device: dict[str, Any]) -> bool:
    """Return True for EEDTOY F4USM61B channel definitions."""
    if not isinstance(device, dict):
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    explicit = device.get("device_family") or raw.get("device_family")
    if str(explicit or "").strip().upper() == "F4USM61B":
        return True
    text = " ".join(str(value or "") for value in (device.get("name"), raw.get("name"))).upper()
    return "F4USM61B" in text



def _device_family(device: dict[str, Any]) -> str:
    if not isinstance(device, dict):
        return ""
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    explicit = device.get("device_family") or raw.get("device_family")
    if explicit:
        return str(explicit).strip().upper()
    text = " ".join(str(value or "") for value in (device.get("name"), raw.get("name"))).upper()
    for family in ("FTS14EM", "FAE14LPR", "F4USM61B"):
        if family in text:
            return family
    return ""


def _is_fts14em_device(device: dict[str, Any]) -> bool:
    return _device_family(device) == "FTS14EM"


def _fts14em_inverted(device: dict[str, Any]) -> bool:
    return _bool_option(_device_option(device, "inverted", _device_option(device, "invert", False)))


def _is_fae14lpr_device(device: dict[str, Any]) -> bool:
    return _device_family(device) == "FAE14LPR"

def _f4usm61b_mode(device: dict[str, Any]) -> int | None:
    """Return EEDTOY operating_mode 1..8 for F4USM61B."""
    value = _device_option(device, "operating_mode", None)
    try:
        mode = int(value)
    except (TypeError, ValueError):
        return None
    return mode if 1 <= mode <= 8 else None


def _f4usm61b_inverted(device: dict[str, Any]) -> bool:
    """F4USM61B inversion is encoded by operating_mode, never generically."""
    return False


def _f4usm61b_physical_unique_id(device: dict[str, Any]) -> str | None:
    """Return the physical F4USM61B sender ID used for battery telegrams."""
    value = _device_option(device, "physical_unique_id", None)
    text = str(value or "").strip().upper()
    return text or None

def _f4usm61b_base_id(device: dict[str, Any]) -> str | None:
    """Return the common configured Base-ID for all F4USM61B modes."""
    value = _device_option(device, "base_id", None)
    text = str(value or "").strip().upper()
    return text or None

def _is_frwb_device(device: dict[str, Any]) -> bool:
    """Return True only for an FRWB configured with EEP A5-30-03.

    FRWB and FSM60B BA3 share A5-30-03.  They must therefore be separated by
    the configured device designation, never by changing the EEP globally.
    """
    if not isinstance(device, dict) or normalize_eep(device.get("eep")) != "A5-30-03":
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("model"),
            device.get("eltako"),
            raw.get("name"),
            raw.get("device_type"),
            raw.get("model"),
            raw.get("eltako"),
        )
    ).upper()
    return "FRWB" in text


def _is_flgtf_device(device: dict[str, Any]) -> bool:
    if not isinstance(device, dict):
        return False
    eep = normalize_eep(device.get("eep"))
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    text = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("model"),
            device.get("eltako"),
            raw.get("name"),
            raw.get("device_type"),
            raw.get("model"),
            raw.get("eltako"),
        )
    ).upper()
    return "FLGTF" in text and eep in ("A5-09-0C", "A5-04-02")


def _flgtf_device_base_id(device: dict[str, Any]) -> str:
    device_id = str(device.get("id") or "").upper()
    eep = normalize_eep(device.get("eep"))
    if eep == "A5-04-02":
        return _id_with_offset(device_id, -1) or device_id
    return device_id


def _device_option(device: dict[str, Any], key: str, default: Any = None) -> Any:
    if not isinstance(device, dict):
        return default
    if key in device and device.get(key) is not None:
        return device.get(key)
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return raw.get(key, default)


def _futh55ed_mode(device: dict[str, Any]) -> str:
    """Return the normalized room-controller operating mode.

    ``room_controller_mode`` is the current generic key used for FTR55/65 and
    future room controllers. ``futh55ed_mode`` remains supported for existing
    EEDTOY YAML files. TF61 and the older ``two_point`` spelling are normalized
    to one internal mode so entity routing stays backwards compatible.
    """
    value = _device_option(device, "room_controller_mode", None)
    if value in (None, ""):
        value = _device_option(device, "futh55ed_mode", "")
    mode = str(value or "").strip().lower().replace("-", "_")
    if mode in {"tf61", "tf61r", "two_point", "2_point"}:
        return "two_point"
    return mode


def _is_futh55ed_device(device: dict[str, Any]) -> bool:
    """Return True for configured FUTH/FTR room-controller profiles."""
    if not isinstance(device, dict):
        return False
    if _futh55ed_mode(device):
        return True
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    text = " ".join(str(value or "") for value in (device.get("name"), device.get("model"), device.get("eltako"), raw.get("name"), raw.get("model"), raw.get("eltako"))).upper()
    return any(model in text for model in ("FUTH55ED", "FTR55", "FTR65", "FTRF65"))


def _is_ffg7b_device(device: dict[str, Any]) -> bool:
    """Return True for the three-state ELTAKO FFG7B window handle.

    New EEDTOY exports carry the explicit ``ffg7b_three_state`` flag.  Name
    matching keeps manually written and older YAML files compatible.
    """
    if not isinstance(device, dict):
        return False
    eep = normalize_eep(device.get("eep"))
    if eep not in ("A5-14-09", "F6-10-00"):
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    explicit = device.get("ffg7b_three_state")
    if explicit is None:
        explicit = raw.get("ffg7b_three_state")
    if isinstance(explicit, str):
        explicit = explicit.strip().lower() in {"1", "true", "yes", "on", "ja"}
    if explicit is not None:
        return bool(explicit)
    text = " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            device.get("model"),
            device.get("eltako"),
            raw.get("name"),
            raw.get("device_type"),
            raw.get("model"),
            raw.get("eltako"),
        )
    ).upper()
    return "FFG7B" in text


class EltakoGatewayEntity(Entity):
    """Base entity attached directly to the configured ELTAKO gateway device."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_available = True

    def __init__(self, gateway, name: str, unique_suffix: str) -> None:
        self.gateway = gateway
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{gateway.entry_id}_gateway_{unique_suffix}".lower()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.gateway.entry_id)},
            manufacturer="ELTAKO",
            name=gateway_device_name(self.gateway),
            model=gateway_model(self.gateway),
        )


class EltakoBaseEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_available = True

    def __init__(self, gateway, sender_id: str, name: str, device: dict[str, Any] | None = None) -> None:
        self.gateway = gateway
        self.device_config = device or {}
        self.sender_id = str(sender_id).upper()
        self._attr_name = name
        self._attr_unique_id = (
            f"{DOMAIN}_{gateway.entry_id}_{self.sender_id}_{name}".lower().replace(" ", "_").replace("/", "_")
        )

    @property
    def device_info(self) -> DeviceInfo:
        if self.device_config:
            gateway_info = self.device_config.get("gateway") if isinstance(self.device_config.get("gateway"), dict) else {}
            device_id = str(self.device_config.get("id") or self.sender_id).upper()
            name = str(self.device_config.get("name") or f"ELTAKO {device_id}")
            eep = self.device_config.get("eep")
            model = f"EEP {eep}" if eep else "ELTAKO Device"

            # FLGTF sends TVOC and temperature/humidity as two EnOcean IDs
            # (A5-09-0C and A5-04-02, usually ID + 1).  In Home Assistant this
            # must still be one physical device, just like a combined CO2/temp/
            # humidity sensor.  Group both IDs under the TVOC/base ID.
            if _is_flgtf_device(self.device_config):
                base_id = _flgtf_device_base_id(self.device_config)
                if base_id:
                    device_id = f"FLGTF_{base_id}"
                name = _strip_flgtf_suffix(name)
                model = "FLGTF (A5-09-0C + A5-04-02)"

            # EEDTOY exports one YAML row per FTS14EM input.  All rows with the
            # same Base-ID belong to one physical FTS14EM device.  Use the
            # explicit EEDTOY metadata for the Home Assistant device name so
            # installations with several ID ranges remain distinguishable.
            if _is_fts14em_device(self.device_config):
                base_id = str(_device_option(self.device_config, "base_id", "") or "").strip().upper()
                mode = str(_device_option(self.device_config, "operating_mode", "UT") or "UT").strip().upper()
                id_range = str(_device_option(self.device_config, "id_range", "") or "").strip()
                common_id = base_id or id_range or device_id
                device_id = f"FTS14EM_{common_id}"
                name_parts = ["FTS14EM", mode]
                if id_range:
                    name_parts.append(id_range)
                name = " ".join(name_parts)
                model = f"FTS14EM {mode}"

            # All F4USM61B channel IDs and the separate physical battery sender ID
            # belong to one physical module in Home Assistant.
            if _is_f4usm61b_device(self.device_config):
                mode = _f4usm61b_mode(self.device_config)
                common_id = (
                    _f4usm61b_physical_unique_id(self.device_config)
                    if mode in {1, 2, 4, 5, 7}
                    else _f4usm61b_base_id(self.device_config)
                )
                if common_id:
                    device_id = f"F4USM61B_{common_id}"
                name = name.split(" Kanal ")[0].strip() or "F4USM61B"
                model = "F4USM61B"

            return DeviceInfo(
                identifiers={(DOMAIN, self.gateway.entry_id, device_id)},
                manufacturer="ELTAKO",
                name=name,
                model=model,
                via_device=(DOMAIN, self.gateway.entry_id),
            )

        return DeviceInfo(
            identifiers={(DOMAIN, self.sender_id)},
            manufacturer="ELTAKO",
            name=f"ELTAKO {self.sender_id}",
            via_device=(DOMAIN, self.gateway.entry_id),
        )


class EltakoYamlEntity(EltakoBaseEntity):
    """Base class for entities created from pasted/imported EEDTOY YAML."""

    def __init__(self, gateway, device: dict[str, Any], name: str | None = None, suffix: str | None = None) -> None:
        entity_name = name or str(device.get("name") or device.get("id") or "ELTAKO Device")
        if suffix:
            # With has_entity_name=True Home Assistant already prefixes the
            # entity with the physical device name.  FLGTF YAML historically
            # contained names such as "FLGTF TVOC" and the generic code added
            # the suffix once more, producing names/object IDs like
            # "FLGTF TVOC TVOC" / sensor.flgtf_flgtf_tvoc_tvoc.
            # Keep the physical device name in DeviceInfo and use only the
            # functional entity name for the three primary FLGTF values.
            if _is_flgtf_device(device) and suffix.casefold() in {
                "tvoc",
                "temperatur",
                "luftfeuchtigkeit",
            }:
                entity_name = suffix
            else:
                entity_name = f"{entity_name} {suffix}"
        sender_id = str(device.get("id") or device.get("sender_id") or entity_name)
        super().__init__(gateway, sender_id, entity_name, device)
        base = device_key(device)
        if suffix:
            base = f"{base}_{suffix}".lower().replace(" ", "_").replace("/", "_")
        self._attr_unique_id = f"{DOMAIN}_{gateway.entry_id}_{base}"
        self._attr_extra_state_attributes = {
            "eltako_id": device.get("id"),
            "eep": device.get("eep"),
            "sender_id": device.get("sender_id"),
            "sender_eep": device.get("sender_eep"),
            "platform": device.get("platform"),
            "gateway": device.get("gateway"),
        }
        for option in (
            "device_family",
            "unique_id",
            "operating_mode",
            "base_id",
            "id_range",
            "input_number",
            "inverted",
            "id_count",
            "id_offset_start",
            "channel_count",
            "room_controller_mode",
            "hysteresis",
            "min_target_temperature",
            "max_target_temperature",
            "frost_temperature",
            "dimming_speed",
        ):
            value = _device_option(device, option, None)
            if value is not None:
                self._attr_extra_state_attributes[option] = value
