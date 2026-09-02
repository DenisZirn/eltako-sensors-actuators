from __future__ import annotations

import asyncio
import logging
import colorsys
from datetime import datetime, timezone
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from pathlib import Path

from .bus.decoder import decode_esp2_message
from .bus.eep_07_3f_7f import build_07_3f_7f_off_messages, build_07_3f_7f_rgbw_messages
from .bus.eep_a5_10_06 import build_a5_10_06_room_control, build_fhk_mode_command
from .bus.eep_series14 import build_series14_switch_command
from .bus.eep_a5_20_01 import (
    build_a5_20_01_teach_in_response,
    build_a5_20_01_temperature_setpoint,
    build_a5_20_01_valve_position,
)
from .bus.eep_a5_38_08 import build_a5_38_08_dimming, build_a5_38_08_switch
from .bus.eep_f6_02 import build_f6_02_01_rocker
from .bus.eep_h5_3f_7f import build_h5_3f_7f_cover
from .bus.esp2 import ESP2Message, ORG_4BS, ORG_RPS, build_regular_4bs
from .bus.exceptions import UnsupportedCommandError
from .bus.ids import format_address, parse_address
from .bus.transport import SerialTransport
from .diagnostics import diagnostic_event
from .entity_base import normalize_eep
from .entity_base import _f4usm61b_mode, _f4usm61b_physical_unique_id, _is_f4usm61b_device
from .const import (
    GATEWAY_TYPE_AUTO,
    GATEWAY_TYPE_FAM14,
    GATEWAY_TYPE_FAM_USB,
    GATEWAY_TYPE_FGW14USB,
)

_LOGGER = logging.getLogger(__name__)


def _resolve_fam_usb_if01_port(port: str, preferred_usb_serial: str | None = None) -> str:
    """Return the usable if01 interface for a FAM-USB / EnOcean Programmer.

    The EnOcean Programmer V3.2 can expose two Linux device nodes. if00 is not
    the ESP2 radio interface used for transmitting teach-in telegrams. if01 is
    the correct interface. If the stored config entry still points to ttyUSB0 or
    an if00 by-id path, resolve it to the matching if01 /dev/serial/by-id path
    whenever pyserial exposes enough descriptor information.
    """
    normalized = str(port or "").lower()
    if not normalized:
        return port
    configured_usb_serial = _extract_usb_serial_from_text(str(port or ""))
    wanted_usb_serial = (preferred_usb_serial or configured_usb_serial or "").strip() or None

    def _prefer_by_id_for_real_path(candidate_port: str) -> str | None:
        try:
            by_id_dir = Path("/dev/serial/by-id")
            if not by_id_dir.exists():
                return None
            target = Path(candidate_port).resolve()
            matches = []
            for link in by_id_dir.iterdir():
                try:
                    text = str(link).lower()
                    if "if01" not in text:
                        continue
                    if not _serial_matches_preference(text, wanted_usb_serial):
                        continue
                    if link.resolve() == target:
                        matches.append(str(link))
                except Exception:
                    continue
            if matches:
                matches.sort()
                return matches[0]
        except Exception:
            return None
        return None

    if "if01" in normalized:
        stable = _prefer_by_id_for_real_path(port)
        if stable and stable != port:
            _LOGGER.info("ELTAKO FAM-USB port normalized to stable if01 by-id path: old=%s new=%s", port, stable)
            return stable
        return port

    # Fast deterministic path for Home Assistant OS / containers: stable
    # symlink names usually contain ...-if00-port0 or ...-if01-port0.  After
    # Core/OS updates /dev/ttyUSB* numbering may change, while by-id remains
    # stable.  The usable FAM-USB ESP2 radio interface is if01.
    try:
        by_id_dir = Path("/dev/serial/by-id")
        if by_id_dir.exists():
            links = sorted(by_id_dir.iterdir(), key=lambda x: str(x))
            # If the saved entry is an if00 symlink, first try the direct if01
            # sibling. This is the most reliable fix for entries selected before
            # the if01/if00 distinction was enforced.
            if "if00" in normalized:
                sibling = Path(str(port).replace("if00", "if01"))
                if sibling.exists():
                    _LOGGER.info("ELTAKO FAM-USB port corrected from if00 to if01 sibling: old=%s new=%s", port, sibling)
                    return str(sibling)
            # If the stored /dev/ttyUSB* is no longer the EnOcean if01 device,
            # prefer the unique EnOcean if01 by-id path.
            eno_if01 = []
            for link in links:
                text = str(link).lower()
                if "if01" not in text:
                    continue
                if not _serial_matches_preference(text, wanted_usb_serial):
                    continue
                if "enocean" in text or "programmer" in text:
                    eno_if01.append(str(link))
            if len(eno_if01) == 1 and eno_if01[0] != port:
                reason = "matching EnOcean if01 by-id path" if wanted_usb_serial else "unique EnOcean if01 by-id path"
                _LOGGER.info("ELTAKO FAM-USB port corrected to %s: old=%s new=%s serial=%s", reason, port, eno_if01[0], wanted_usb_serial)
                return eno_if01[0]
            if len(eno_if01) > 1:
                _LOGGER.warning(
                    "ELTAKO FAM-USB port could not be auto-corrected uniquely; multiple EnOcean if01 candidates found: configured=%s serial=%s candidates=%s",
                    port,
                    wanted_usb_serial,
                    eno_if01,
                )
    except Exception as err:
        _LOGGER.debug("ELTAKO FAM-USB deterministic if01 resolver failed: %s", err)

    try:
        from serial.tools import list_ports
    except Exception as err:  # pragma: no cover - depends on HA runtime
        _LOGGER.debug("ELTAKO FAM-USB if01 resolver unavailable: %s", err)
        return port

    ports = list(list_ports.comports(include_links=True))
    current = None
    for candidate in ports:
        dev = str(getattr(candidate, "device", "") or "")
        if dev == port:
            current = candidate
            break
        try:
            if Path(dev).resolve() == Path(port).resolve():
                current = candidate
                break
        except Exception:
            pass

    def _text(candidate: Any) -> str:
        return " ".join([
            str(getattr(candidate, "device", "") or ""),
            str(getattr(candidate, "name", "") or ""),
            str(getattr(candidate, "description", "") or ""),
            str(getattr(candidate, "hwid", "") or ""),
            str(getattr(candidate, "interface", "") or ""),
            str(getattr(candidate, "location", "") or ""),
            str(getattr(candidate, "serial_number", "") or ""),
        ]).lower()

    def _is_enocean(candidate: Any) -> bool:
        text = _text(candidate)
        return "enocean_gmbh_enocean_programmer" in text or "enocean programmer" in text or "enocean" in text

    def _group_key(candidate: Any) -> tuple[Any, Any, Any]:
        return (
            getattr(candidate, "vid", None),
            getattr(candidate, "pid", None),
            getattr(candidate, "serial_number", None),
        )

    key = _group_key(current) if current is not None else (None, None, None)
    current_is_enocean = _is_enocean(current) if current is not None else False
    candidates: list[Any] = []
    for candidate in ports:
        text = _text(candidate)
        if "if01" not in text:
            continue
        if not _is_enocean(candidate):
            continue
        if not _serial_matches_preference(text, wanted_usb_serial):
            continue
        # Only bind to the current VID/PID/serial group when the current port is
        # actually an EnOcean interface. If /dev/ttyUSB* was reassigned to a
        # different adapter after reboot/update, this filter would otherwise
        # reject the real FAM-USB.
        if current_is_enocean and key != (None, None, None) and _group_key(candidate) != key:
            continue
        candidates.append(candidate)

    if not candidates:
        stable = _prefer_by_id_for_real_path(port)
        return stable or port

    if len(candidates) > 1 and not wanted_usb_serial and current is None:
        _LOGGER.warning(
            "ELTAKO FAM-USB port could not be resolved safely; multiple EnOcean if01 candidates and no USB serial preference: configured=%s candidates=%s",
            port,
            [str(getattr(c, "device", "")) for c in candidates],
        )
        return port

    candidates.sort(key=lambda c: (0 if "/dev/serial/by-id/" in str(getattr(c, "device", "")).lower() else 1, str(getattr(c, "device", ""))))
    resolved = str(getattr(candidates[0], "device", ""))
    stable = _prefer_by_id_for_real_path(resolved) or resolved
    if stable and stable != port:
        _LOGGER.info("ELTAKO FAM-USB port corrected to if01: old=%s new=%s", port, stable)
        return stable
    return port



def _path_resolves_equal(a: str, b: str) -> bool:
    try:
        return Path(a).resolve() == Path(b).resolve()
    except Exception:
        return str(a) == str(b)


def _serial_candidates() -> list[dict[str, str]]:
    """Return serial candidates from /dev/serial/by-id and pyserial metadata.

    The matching intentionally avoids fixed serial numbers. It uses stable
    descriptors such as manufacturer/product/interface (EnOcean Programmer
    if01 for FAM-USB, FTDI/FT232R for FGW14-USB/RS485). This makes the resolver
    portable across installations with different USB serial numbers.
    """
    result: list[dict[str, str]] = []

    try:
        by_id_dir = Path("/dev/serial/by-id")
        if by_id_dir.exists():
            for link in sorted(by_id_dir.iterdir(), key=lambda x: str(x)):
                try:
                    result.append({
                        "device": str(link),
                        "text": f"{link} {link.resolve()}".lower(),
                    })
                except Exception:
                    result.append({"device": str(link), "text": str(link).lower()})
    except Exception:
        pass

    try:
        from serial.tools import list_ports
        for portinfo in list_ports.comports(include_links=True):
            parts = [
                str(getattr(portinfo, "device", "") or ""),
                str(getattr(portinfo, "name", "") or ""),
                str(getattr(portinfo, "description", "") or ""),
                str(getattr(portinfo, "hwid", "") or ""),
                str(getattr(portinfo, "interface", "") or ""),
                str(getattr(portinfo, "location", "") or ""),
                str(getattr(portinfo, "manufacturer", "") or ""),
                str(getattr(portinfo, "product", "") or ""),
                str(getattr(portinfo, "serial_number", "") or ""),
            ]
            result.append({"device": str(getattr(portinfo, "device", "") or ""), "text": " ".join(parts).lower()})
    except Exception:
        pass

    # de-duplicate while preserving order
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for c in result:
        dev = c.get("device") or ""
        if not dev or dev in seen:
            continue
        seen.add(dev)
        unique.append(c)
    return unique


def _extract_usb_serial_from_text(text: str) -> str | None:
    """Best-effort USB serial extraction from by-id names or pyserial HWIDs."""
    import re

    raw = str(text or "")
    # Linux by-id examples:
    # usb-EnOcean_GmbH_EnOcean_Programmer_V3.2_FTAMHS20-if01-port0
    # usb-FTDI_FT232R_USB_UART_A50285BI-if00-port0
    for pattern in (
        r"EnOcean_Programmer_V3\.2_([^-\s/]+)-if\d+",
        r"FT232R_USB_UART_([^-\s/]+)-if\d+",
        r"USB_UART_([^-\s/]+)-if\d+",
        r"SER=([^\s]+)",
        r"SERIAL_SHORT=([^\s]+)",
    ):
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip()
            if value:
                return value
    return None


def _extract_usb_interface_from_text(text: str) -> str | None:
    """Return if00/if01 when it can be inferred from a path or descriptor."""
    import re

    raw = str(text or "")
    match = re.search(r"if(\d{2})", raw, flags=re.IGNORECASE)
    if match:
        return f"if{match.group(1)}"
    match = re.search(r"interface\s*0*(\d+)", raw, flags=re.IGNORECASE)
    if match:
        return f"if{int(match.group(1)):02d}"
    return None


def _gateway_preferred_usb_serial(selected_gateway: dict[str, Any] | None) -> str | None:
    if not isinstance(selected_gateway, dict):
        return None
    for key in ("usb_serial", "serial", "serial_number", "id_serial_short", "ID_SERIAL_SHORT"):
        value = selected_gateway.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return None


def _serial_matches_preference(text: str, preferred_usb_serial: str | None) -> bool:
    if not preferred_usb_serial:
        return True
    return str(preferred_usb_serial).lower() in str(text or "").lower()


def _describe_serial_port_sync(port: str) -> dict[str, str | None]:
    """Return stable diagnostic metadata for the currently resolved serial port."""
    info: dict[str, str | None] = {
        "path": str(port or "") or None,
        "stable_path": None,
        "current_devname": None,
        "usb_serial": None,
        "usb_interface": None,
        "descriptor": None,
    }
    if not port:
        return info

    texts: list[str] = [str(port)]
    try:
        path = Path(str(port))
        if str(path).startswith("/dev/"):
            info["current_devname"] = str(path.resolve()) if path.exists() else None
            stable = _prefer_by_id_for_candidate(str(port))
            if stable != str(port):
                info["stable_path"] = stable
                texts.append(stable)
            if path.exists():
                texts.append(str(path.resolve()))
    except Exception:
        pass

    try:
        from serial.tools import list_ports
        for portinfo in list_ports.comports(include_links=True):
            dev = str(getattr(portinfo, "device", "") or "")
            if not dev:
                continue
            same = dev == port
            if not same:
                try:
                    same = Path(dev).resolve() == Path(port).resolve()
                except Exception:
                    same = False
            if not same:
                continue
            parts = [
                dev,
                str(getattr(portinfo, "name", "") or ""),
                str(getattr(portinfo, "description", "") or ""),
                str(getattr(portinfo, "hwid", "") or ""),
                str(getattr(portinfo, "interface", "") or ""),
                str(getattr(portinfo, "location", "") or ""),
                str(getattr(portinfo, "manufacturer", "") or ""),
                str(getattr(portinfo, "product", "") or ""),
                str(getattr(portinfo, "serial_number", "") or ""),
            ]
            text = " ".join(parts)
            texts.append(text)
            if getattr(portinfo, "serial_number", None):
                info["usb_serial"] = str(getattr(portinfo, "serial_number"))
            if getattr(portinfo, "interface", None):
                info["usb_interface"] = str(getattr(portinfo, "interface"))
    except Exception:
        pass

    combined = " ".join(texts)
    info["descriptor"] = combined or None
    if not info["usb_serial"]:
        info["usb_serial"] = _extract_usb_serial_from_text(combined)
    if not info["usb_interface"]:
        info["usb_interface"] = _extract_usb_interface_from_text(combined)
    if not info["stable_path"]:
        stable = _prefer_by_id_for_candidate(str(port))
        info["stable_path"] = stable if stable else str(port)
    return info


def _is_enocean_programmer_text(text: str) -> bool:
    text = text.lower()
    return "enocean" in text and ("programmer" in text or "ftamh" in text or "fam" in text)


def _is_ftdi_rs485_text(text: str) -> bool:
    text = text.lower()
    return "ftdi" in text or "ft232" in text or "usb-rs485" in text or "rs485" in text


def _prefer_by_id_for_candidate(device: str) -> str:
    """Return a stable by-id symlink for a /dev/ttyUSB* candidate when available."""
    try:
        by_id_dir = Path("/dev/serial/by-id")
        if not by_id_dir.exists():
            return device
        matches: list[str] = []
        for link in by_id_dir.iterdir():
            try:
                if Path(link).resolve() == Path(device).resolve():
                    matches.append(str(link))
            except Exception:
                continue
        if matches:
            matches.sort()
            return matches[0]
    except Exception:
        pass
    return device


def _resolve_rs485_gateway_port(port: str, gateway_type: str, preferred_usb_serial: str | None = None) -> str:
    """Resolve FGW14-USB/FAM14 RS485 ports away from FAM-USB if00/if01.

    A wrong EnOcean Programmer interface can be opened successfully by pyserial;
    that produces a misleading HA "connected" state but no real bus traffic.
    For Series-14 RS485 gateways prefer FTDI/FT232R/RS485 adapters, especially
    stable /dev/serial/by-id links. Do not bind to fixed serial numbers.
    """
    original = str(port or "")
    normalized = original.lower()
    candidates = _serial_candidates()

    if normalized:
        # If the configured path already resolves to a suitable RS485 adapter,
        # only normalize it to a stable by-id name.
        for c in candidates:
            dev = c.get("device") or ""
            if dev and (dev == original or _path_resolves_equal(dev, original)):
                text = c.get("text", "")
                if _is_ftdi_rs485_text(text) and not _is_enocean_programmer_text(text):
                    stable = _prefer_by_id_for_candidate(dev)
                    if stable != original:
                        _LOGGER.info("ELTAKO %s port normalized to stable RS485 by-id path: old=%s new=%s", gateway_type, original, stable)
                    return stable

    # If the selected port is an EnOcean/FAM-USB interface, it is definitely the
    # wrong physical class for FGW14-USB/FAM14 direct RS485. Select the unique
    # FTDI/RS485 adapter if one is present.
    ftdi: list[str] = []
    for c in candidates:
        dev = c.get("device") or ""
        text = c.get("text", "")
        if not dev:
            continue
        if _is_ftdi_rs485_text(text) and not _is_enocean_programmer_text(text):
            if not _serial_matches_preference(text, preferred_usb_serial):
                continue
            # Prefer stable by-id paths over volatile ttyUSB names.
            ftdi.append(_prefer_by_id_for_candidate(dev))
    ftdi = sorted(dict.fromkeys(ftdi), key=lambda x: (0 if "/dev/serial/by-id/" in x.lower() else 1, x))
    if len(ftdi) == 1:
        if ftdi[0] != original:
            _LOGGER.info("ELTAKO %s port corrected to unique RS485/FTDI adapter: old=%s new=%s", gateway_type, original, ftdi[0])
        return ftdi[0]
    if len(ftdi) > 1:
        _LOGGER.warning(
            "ELTAKO %s port could not be auto-corrected uniquely; multiple RS485/FTDI candidates found: configured=%s candidates=%s",
            gateway_type,
            original,
            ftdi,
        )
        return original

    return original


def _resolve_gateway_serial_port(port: str, gateway_type: str, selected_gateway: dict[str, Any] | None = None) -> str:
    """Resolve the serial path according to configured ELTAKO gateway type."""
    gw_type = str(gateway_type or "").strip().lower()
    preferred_usb_serial = _gateway_preferred_usb_serial(selected_gateway)
    if gw_type == GATEWAY_TYPE_FAM_USB:
        return _resolve_fam_usb_if01_port(port, preferred_usb_serial)
    if gw_type in (GATEWAY_TYPE_FAM14, GATEWAY_TYPE_FGW14USB):
        return _resolve_rs485_gateway_port(port, gw_type, preferred_usb_serial)
    return port


def _port_descriptor_mismatches_gateway(port: str, gateway_type: str) -> str | None:
    """Return a human-readable mismatch reason for clearly wrong USB classes."""
    gw_type = str(gateway_type or "").strip().lower()
    normalized = str(port or "").lower()
    texts = [normalized]
    for c in _serial_candidates():
        dev = c.get("device") or ""
        if dev and (dev == port or _path_resolves_equal(dev, port)):
            texts.append(c.get("text", ""))
    text = " ".join(texts).lower()
    if gw_type == GATEWAY_TYPE_FAM_USB:
        if _is_ftdi_rs485_text(text) and not _is_enocean_programmer_text(text):
            return "FAM-USB gateway is configured on an FTDI/RS485 adapter"
        if _is_enocean_programmer_text(text) and "if00" in text and "if01" not in text:
            return "FAM-USB gateway is configured on EnOcean Programmer if00 instead of if01"
    if gw_type in (GATEWAY_TYPE_FAM14, GATEWAY_TYPE_FGW14USB):
        if _is_enocean_programmer_text(text):
            return f"{gw_type} gateway is configured on an EnOcean Programmer/FAM-USB interface instead of an RS485/FTDI adapter"
    return None


def _device_raw_option(device: dict[str, Any], key: str, default: Any = None) -> Any:
    if key in device and device.get(key) is not None:
        return device.get(key)
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return raw.get(key, default)


def _futh55ed_mode(device: Any) -> str:
    if not isinstance(device, dict):
        return ""
    value = _device_raw_option(device, "room_controller_mode", None)
    if value in (None, ""):
        value = _device_raw_option(device, "futh55ed_mode", "")
    mode = str(value or "").strip().lower().replace("-", "_")
    if mode in {"tf61", "tf61r", "two_point", "2_point"}:
        return "two_point"
    return mode


def _is_futh55ed_device(device: Any) -> bool:
    if not isinstance(device, dict):
        return False
    if _futh55ed_mode(device):
        return True
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    text = " ".join(str(value or "") for value in (device.get("name"), device.get("model"), device.get("eltako"), raw.get("name"), raw.get("model"), raw.get("eltako"))).upper()
    return any(model in text for model in ("FUTH55ED", "FTR55", "FTR65", "FTRF65"))


def _is_ffg7b_device(device: Any) -> bool:
    if not isinstance(device, dict):
        return False
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    explicit = _device_raw_option(device, "ffg7b_three_state")
    if isinstance(explicit, str):
        explicit = explicit.strip().lower() in {"1", "true", "yes", "on", "ja"}
    if explicit is not None:
        return bool(explicit)
    text = " ".join(
        str(value or "")
        for value in (device.get("name"), device.get("model"), device.get("eltako"), raw.get("name"), raw.get("model"), raw.get("eltako"))
    ).upper()
    return "FFG7B" in text


def _is_fks_sv_device(device: Any) -> bool:
    return (
        isinstance(device, dict)
        and str(device.get("eep") or "").strip().upper() == "A5-20-01"
        and not _is_futh55ed_device(device)
    )


def _normalized_address_or_none(value: Any) -> str | None:
    try:
        return format_address(parse_address(str(value or "").strip()))
    except Exception:
        return None


def _validate_fks_sv_sender_allocations(devices: list[dict[str, Any]]) -> None:
    """Require one persistent controller sender ID per independent FKS-SV."""
    physical_seen: set[str] = set()
    sender_seen: dict[str, tuple[str, str | None, bool]] = {}
    for device in devices:
        if not _is_fks_sv_device(device):
            continue
        physical = _normalized_address_or_none(device.get("id"))
        sender = _normalized_address_or_none(_get_sender_id(device))
        name = str(device.get("name") or device.get("id") or "FKS-SV")
        if not physical:
            raise ValueError(f"FKS-SV {name} hat keine gueltige physische EnOcean-ID")
        if not sender:
            raise ValueError(f"FKS-SV {name} hat keine gueltige sender.id")
        if physical in physical_seen:
            raise ValueError(f"FKS-SV Geraete-ID doppelt vergeben: {physical}")
        physical_seen.add(physical)

        group_value = _device_raw_option(device, "controller_group")
        group = str(group_value).strip() if group_value not in (None, "") else None
        allow_shared = bool(_device_raw_option(device, "allow_shared_sender", False))
        previous = sender_seen.get(sender)
        if previous is not None:
            previous_device, previous_group, previous_shared = previous
            shared_group_ok = allow_shared and previous_shared and group is not None and group == previous_group
            if not shared_group_ok:
                raise ValueError(
                    f"FKS-SV sender.id {sender} ist fuer {previous_device} und {physical} vergeben. "
                    "Jeder unabhaengige Raum benoetigt eine eigene sender.id."
                )
        else:
            sender_seen[sender] = (physical, group, allow_shared)


def _serial_port_path_available(port: str) -> bool:
    """Return whether a Linux serial path still exists.

    USB hot-plug can leave a pyserial object looking open although the device
    node disappeared. For /dev/ttyUSB* and /dev/serial/by-id/* we must treat a
    missing path as disconnected so the gateway closes and reopens the port.
    """
    try:
        if not port:
            return False
        path = Path(str(port))
        if str(path).startswith("/dev/"):
            return path.exists()
    except Exception:
        return True
    return True


@dataclass(slots=True)
class EltakoTelegram:
    sender_id: str
    eep: str | None
    raw: bytes
    decoded: dict[str, Any]


@dataclass(slots=True)
class GatewayProbeResult:
    detected_gateway_type: str
    base_id: str | None
    transport: str
    ok: bool
    message: str


def _effective_gateway_type(
    configured_gateway_type: str,
    selected_gateway: dict[str, Any] | None,
) -> str:
    """Resolve ``auto`` from the EEDTOY gateway block selected by the user.

    A config entry can remain set to automatic while the imported YAML already
    identifies its physical gateway as FAM14, FGW14-USB or FAM-USB. Ignoring
    that information prevents the stable serial-port resolver from running and
    can make successful OS writes go to an unrelated USB adapter.
    """
    configured = str(configured_gateway_type or "").strip().lower()
    if configured != GATEWAY_TYPE_AUTO:
        return configured

    selected = selected_gateway if isinstance(selected_gateway, dict) else {}
    selected_type = str(selected.get("device_type") or "").strip().lower()
    if selected_type in {
        GATEWAY_TYPE_FAM14,
        GATEWAY_TYPE_FGW14USB,
        GATEWAY_TYPE_FAM_USB,
    }:
        return selected_type
    return GATEWAY_TYPE_AUTO


def _is_fbht_device_config(device: dict[str, Any] | None) -> bool:
    """Identify FBHT55ESB without confusing it with the FBH55ESB variant."""
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
    name_text = " ".join(str(value or "") for value in (device.get("name"), raw.get("name"))).upper()
    return "FBHT" in name_text


class EltakoGateway:
    """Runtime gateway wrapper for ELTAKO Sensors & Actuators."""

    def __init__(self, hass, entry_id: str, port: str, gateway_type: str, base_id: str | None = None, devices: list[dict[str, Any]] | None = None, selected_gateway: dict[str, Any] | None = None) -> None:
        self.hass = hass
        self.entry_id = entry_id
        self.port = port
        self.configured_gateway_type = gateway_type
        selected_gateway_data = dict(selected_gateway or {})
        self.gateway_type = _effective_gateway_type(gateway_type, selected_gateway_data)
        self.base_id = base_id or selected_gateway_data.get("base_id")
        self.probe_result: GatewayProbeResult | None = None
        self._listeners: list[Callable[[EltakoTelegram], None]] = []
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()
        self._last_telegram: EltakoTelegram | None = None
        self._transport: SerialTransport | None = None
        self._rx_mode: str = "internal"
        self._last_send_error: str | None = None
        self._devices: list[dict[str, Any]] = list(devices or [])
        self.selected_gateway: dict[str, Any] = selected_gateway_data
        self.auto_connect_enabled = True
        self.message_delay = 0.10 if self.gateway_type == GATEWAY_TYPE_FAM_USB else (0.001 if self.gateway_type == GATEWAY_TYPE_FAM14 else 0.01)
        self.baudrate = 9600 if self.gateway_type == GATEWAY_TYPE_FAM_USB else 57600
        self.usb_protocol = "ESP2"
        self._last_message_received: str | None = None
        self._device_lookup: dict[str, dict[str, Any]] = {}
        self._fks_sv_physical_lookup: dict[str, dict[str, Any]] = {}
        self._fks_sv_controller_lookup: dict[str, dict[str, Any]] = {}
        self._fks_sv_reply_locks: dict[str, asyncio.Lock] = {}
        self._send_lock = asyncio.Lock()
        self._status_sequence = 0
        self.port_descriptor: dict[str, str | None] = {}
        self.usb_serial: str | None = None
        self.usb_interface: str | None = None
        self.stable_serial_path: str | None = None
        self.current_devname: str | None = None
        self.set_devices(self._devices)

    async def async_start(self) -> None:
        _LOGGER.info("Starting ELTAKO gateway on %s", self.port)
        diagnostic_event(self.hass, "gateway_start", entry_id=self.entry_id, gateway_type=self.gateway_type, gateway=self.gateway_type, port=self.port, base_id=self.base_id)
        await self.async_probe()
        # Open the serial transport before HA creates the status entities.
        # Otherwise the gateway device can appear as disconnected until a first
        # telegram arrives, and FAM-USB teach-in tests are misleading.
        try:
            await self._async_ensure_transport()
        except Exception:
            _LOGGER.exception("ELTAKO gateway initial serial open failed: port=%s gateway_type=%s", self.port, self.gateway_type)
        self._notify_gateway_status("start")
        self._stopped.clear()
        self._task = self.hass.loop.create_task(self._reader_loop())

    async def async_stop(self) -> None:
        _LOGGER.info("Stopping ELTAKO gateway on %s", self.port)
        diagnostic_event(self.hass, "gateway_stop", entry_id=self.entry_id, gateway_type=self.gateway_type, gateway=self.gateway_type, port=self.port)
        self._stopped.set()

        if self._transport is not None:
            await self.hass.async_add_executor_job(self._transport.close)
            self._transport = None


        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def async_probe(self) -> GatewayProbeResult:
        """Detect gateway class from path/descriptor without external bus dependencies."""
        effective_gateway_type = _effective_gateway_type(
            self.configured_gateway_type,
            self.selected_gateway,
        )
        resolved_port = await self.hass.async_add_executor_job(
            _resolve_gateway_serial_port,
            self.port,
            effective_gateway_type,
            self.selected_gateway,
        )
        if resolved_port != self.port:
            _LOGGER.info(
                "ELTAKO gateway serial port auto-resolved: gateway_type=%s old=%s new=%s",
                effective_gateway_type,
                self.port,
                resolved_port,
            )
            self.port = resolved_port

        await self._async_refresh_port_descriptor()

        result = await self.hass.async_add_executor_job(
            _probe_gateway_sync,
            self.port,
            effective_gateway_type,
        )
        self.probe_result = result

        if result.ok:
            self.gateway_type = result.detected_gateway_type
            if result.base_id:
                self.base_id = result.base_id
            elif self.selected_gateway.get("base_id"):
                self.base_id = str(self.selected_gateway.get("base_id"))
            self.set_devices(self._devices)
            _LOGGER.info(
                "Detected ELTAKO gateway: type=%s base_id=%s port=%s transport=%s",
                self.gateway_type,
                self.base_id,
                self.port,
                result.transport,
            )
        else:
            _LOGGER.warning("ELTAKO gateway probe failed on %s: %s", self.port, result.message)

        diagnostic_event(
            self.hass,
            "gateway_probe",
            entry_id=self.entry_id,
            configured_gateway_type=self.configured_gateway_type,
            selected_gateway_type=(self.selected_gateway or {}).get("device_type"),
            effective_gateway_type=effective_gateway_type,
            detected_gateway_type=result.detected_gateway_type,
            gateway=self.gateway_type,
            port=self.port,
            stable_serial_path=self.stable_serial_path,
            current_devname=self.current_devname,
            usb_serial=self.usb_serial,
            usb_interface=self.usb_interface,
            baudrate=9600 if self.gateway_type == GATEWAY_TYPE_FAM_USB else 57600,
            transport=result.transport,
            ok=result.ok,
            message=result.message,
            base_id=self.base_id,
        )

        return result


    def set_devices(self, devices: list[dict[str, Any]] | None) -> None:
        """Install device lookup tables and validate FKS-SV sender allocation."""
        self._devices = list(devices or [])
        _validate_fks_sv_sender_allocations(self._devices)

        lookup: dict[str, dict[str, Any]] = {}
        fks_physical: dict[str, dict[str, Any]] = {}
        fks_controller: dict[str, dict[str, Any]] = {}
        effective_allocations: dict[str, tuple[str, str | None, bool]] = {}
        effective_base_id = self.base_id or self.selected_gateway.get("base_id")
        reserved_by_other_devices: dict[str, str] = {}

        for other in self._devices:
            if not isinstance(other, dict) or _is_fks_sv_device(other):
                continue
            owner = str(other.get("name") or other.get("id") or "ELTAKO Geraet")
            for candidate in (other.get("id"), _get_sender_id(other)):
                normalized = _normalized_address_or_none(candidate)
                if normalized:
                    reserved_by_other_devices.setdefault(normalized, owner)
            configured_other_sender = _normalized_address_or_none(_get_sender_id(other))
            if configured_other_sender:
                try:
                    effective_other_sender = _effective_sender_id_for_gateway(
                        configured_other_sender,
                        self.gateway_type,
                        effective_base_id,
                        device=other,
                    )
                except Exception:
                    effective_other_sender = configured_other_sender
                reserved_by_other_devices.setdefault(str(effective_other_sender).upper(), owner)

        for device in self._devices:
            if not isinstance(device, dict):
                continue
            for address in _candidate_addresses_for_device(device):
                lookup[address.upper()] = device

            # F4USM61B modes 1, 2, 4, 5 and 7 transmit the approximately
            # daily battery status from the physical Unique-ID using A5-07-01,
            # while their normal channel telegrams use Base-ID+1/+2. Register
            # a synthetic routing definition so that this separate sender is
            # decoded as A5-07-01 without altering either channel definition.
            if _is_f4usm61b_device(device) and _f4usm61b_mode(device) in {1, 2, 4, 5, 7}:
                physical_unique_id = _f4usm61b_physical_unique_id(device)
                if physical_unique_id:
                    battery_device = dict(device)
                    battery_device["id"] = physical_unique_id
                    battery_device["eep"] = "A5-07-01"
                    battery_device["platform"] = "sensor"
                    battery_device["f4usm61b_battery_sender"] = True
                    lookup.setdefault(physical_unique_id.upper(), battery_device)

            if not _is_fks_sv_device(device):
                continue

            physical_unique_id = _normalized_address_or_none(device.get("id"))
            configured_sender = _normalized_address_or_none(_get_sender_id(device))
            if physical_unique_id:
                fks_physical[physical_unique_id] = device
            if configured_sender:
                other_owner = reserved_by_other_devices.get(configured_sender)
                if other_owner:
                    raise ValueError(
                        f"FKS-SV sender.id {configured_sender} wird bereits von {other_owner} verwendet"
                    )
                fks_controller[configured_sender] = device
                try:
                    effective_sender = _effective_sender_id_for_gateway(
                        configured_sender,
                        self.gateway_type,
                        effective_base_id,
                        device=device,
                    )
                except Exception:
                    effective_sender = configured_sender
                effective_sender = str(effective_sender).upper()
                effective_other_owner = reserved_by_other_devices.get(effective_sender)
                if effective_other_owner:
                    raise ValueError(
                        f"FKS-SV Controller-ID {effective_sender} wird bereits von {effective_other_owner} verwendet"
                    )
                group_value = _device_raw_option(device, "controller_group")
                group = str(group_value).strip() if group_value not in (None, "") else None
                allow_shared = bool(_device_raw_option(device, "allow_shared_sender", False))
                previous = effective_allocations.get(effective_sender)
                if previous is not None and previous[0] != physical_unique_id:
                    previous_physical, previous_group, previous_shared = previous
                    shared_group_ok = (
                        allow_shared
                        and previous_shared
                        and group is not None
                        and group == previous_group
                    )
                    if not shared_group_ok:
                        raise ValueError(
                            f"FKS-SV Controller-ID-Kollision im Gateway-Bereich: {effective_sender} "
                            f"fuer {previous_physical} und {physical_unique_id}"
                        )
                else:
                    effective_allocations[effective_sender] = (physical_unique_id or "", group, allow_shared)
                fks_controller[effective_sender] = device

        self._device_lookup = lookup
        self._fks_sv_physical_lookup = fks_physical
        self._fks_sv_controller_lookup = fks_controller
        _LOGGER.info(
            "ELTAKO gateway device lookup prepared: devices=%s addresses=%s fks_sv=%s fks_controller_ids=%s",
            len(self._devices),
            len(self._device_lookup),
            len(self._fks_sv_physical_lookup),
            len(self._fks_sv_controller_lookup),
        )

    async def _async_refresh_port_descriptor(self) -> None:
        descriptor = await self.hass.async_add_executor_job(_describe_serial_port_sync, self.port)
        self.port_descriptor = descriptor
        self.usb_serial = descriptor.get("usb_serial")
        self.usb_interface = descriptor.get("usb_interface")
        self.stable_serial_path = descriptor.get("stable_path")
        self.current_devname = descriptor.get("current_devname")

    def _handle_received_frame(self, frame: bytes) -> None:
        msg = ESP2Message.parse(frame)
        physical_sender_id, preliminary = decode_esp2_message(msg, None)
        physical_key = physical_sender_id.upper()

        # Always initialize all routing variables before the device-specific
        # branches below. A transmitted telegram can be received immediately
        # as an echo while a Home Assistant service call is still waiting for
        # the serial send operation. The receive callback must never fail with
        # an unbound local variable and thereby turn a successful TX into a
        # failed light/cover service call.
        decoded: dict[str, Any] = dict(preliminary or {})
        logical_sender_id = physical_sender_id
        eep: str | None = None
        device: dict[str, Any] | None = None

        # A5-20-01 uses different DB2 meanings in each direction. Detect a
        # mirrored controller telegram before the generic lookup maps it back
        # onto the physical valve. The logical sender remains the controller ID
        # so valve entities cannot consume their own TX echo as status.
        controller_device = self._fks_sv_controller_lookup.get(physical_key)
        if controller_device is not None:
            _, decoded = decode_esp2_message(msg, "A5-20-01", direction="controller")
            logical_sender_id = physical_sender_id
            eep = "A5-20-01"
            device = controller_device
        else:
            device = self._device_lookup.get(physical_key)
            logical_sender_id = physical_sender_id
            eep = None
            if device is not None:
                # F4USM61B channel telegrams must stay bound to the physical
                # sender address (Base-ID+1 / Base-ID+2).  ``physical_unique_id`` is
                # only the common physical module ID for device grouping and
                # the separate battery telegram; it must never collapse both
                # channels onto one logical sender.
                if _is_f4usm61b_device(device):
                    logical_sender_id = physical_sender_id
                else:
                    logical_sender_id = str(device.get("id") or physical_sender_id).upper()
                eep = normalize_eep(device.get("eep")) or None

            mode = _futh55ed_mode(device) if device is not None else ""
            if eep == "A5-20-01":
                direction = "controller" if mode == "fks_kp" else "actuator"
            elif eep == "A5-20-04" and mode == "fks_hora":
                direction = "controller"
            else:
                direction = None

            # FFG7B exists in both A5-14-09 and F6-10-00 variants. Decode the
            # physical telegram family from ORG as a safety net even when the
            # wrong profile was selected in an older YAML. This fixes the case
            # where Last Seen updated but all FFG7B state entities stayed
            # unknown because the configured EEP and transmitted ORG differed.
            decoder_eep = eep
            if _is_ffg7b_device(device):
                if msg.org == ORG_RPS:
                    decoder_eep = "F6-10-00"
                elif msg.org == ORG_4BS:
                    decoder_eep = "A5-14-09"
            _, decoded = decode_esp2_message(msg, decoder_eep, direction=direction)
            if _is_ffg7b_device(device):
                decoded.setdefault("configured_eep", eep)
                decoded.setdefault("detected_eep", decoder_eep)

            # The FUTH55ED learning frames are device-specific 4BS payloads.
            # Suppress measurement keys for those frames so they cannot reset
            # Home Assistant entities to fictitious values.
            data_bytes = bytes(msg.body[2:6]) if len(msg.body) >= 6 else b""
            learn_payloads = {
                ("fhk", "A5-10-06"): bytes((0x40, 0x30, 0x0D, 0x87)),
                ("two_point", "A5-38-08"): bytes((0xE0, 0x40, 0x0D, 0x80)),
                ("hygrostat", "A5-10-12"): bytes((0x40, 0x90, 0x0D, 0x80)),
            }
            if mode and data_bytes == learn_payloads.get((mode, eep)):
                decoded = {
                    key: value
                    for key, value in decoded.items()
                    if key in {"raw", "data_hex", "org", "physical_sender_id", "last_seen"}
                }
                decoded.update(
                    {
                        "value": data_bytes.hex("-"),
                        "learn": True,
                        "learn_telegram": True,
                        "data_telegram": False,
                        "telegram_type": f"room_controller_{mode}_teach_in",
                        "room_controller_mode": mode,
                        "futh55ed_mode": mode,
                    }
                )
            elif mode:
                decoded.setdefault("room_controller_mode", mode)
                decoded.setdefault("futh55ed_mode", mode)

        # FBHT55ESB is the temperature-capable variant of the FBH A5-08-01
        # telegram. FBH55ESB leaves DB1 unused, therefore temperature must be
        # enabled by the configured model/explicit EEDTOY flag instead of for
        # every A5-08-01 device.
        if (
            device is not None
            and eep == "A5-08-01"
            and _is_fbht_device_config(device)
            and not decoded.get("learn")
            and len(msg.body) >= 6
        ):
            db1 = int(msg.body[4])
            decoded["temperature"] = round((db1 / 255.0) * 50.0, 1)
            decoded["temperature_raw"] = db1
            decoded["telegram_type"] = "fbht_motion_brightness_temperature"

        decoded.setdefault("physical_sender_id", physical_sender_id)
        decoded.setdefault("logical_sender_id", logical_sender_id)
        if device is not None:
            decoded.setdefault("device_name", device.get("name"))
            _normalize_device_specific_decoded(device, decoded)

        self._last_message_received = decoded.get("last_seen") or datetime.now(timezone.utc).isoformat()
        telegram = EltakoTelegram(
            sender_id=logical_sender_id,
            eep=eep,
            raw=frame,
            decoded=decoded,
        )
        _LOGGER.debug(
            "ELTAKO telegram received: sender=%s physical=%s eep=%s direction=%s decoded=%s",
            logical_sender_id,
            physical_sender_id,
            eep,
            decoded.get("direction"),
            decoded,
        )
        self._dispatch(telegram)

    def register_listener(self, callback: Callable[[EltakoTelegram], None]) -> Callable[[], None]:
        self._listeners.append(callback)

        def remove_listener() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return remove_listener

    async def _reader_loop(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._async_ensure_transport()
                frame = await self.hass.async_add_executor_job(self._transport.read_frame) if self._transport else None
                if frame is None:
                    if self._transport is not None and not self._transport.is_active():
                        _LOGGER.warning("ELTAKO gateway serial transport is no longer active: port=%s gateway_type=%s", self.port, self.gateway_type)
                        try:
                            await self.hass.async_add_executor_job(self._transport.close)
                        finally:
                            self._transport = None
                        self._notify_gateway_status("disconnected")
                    await asyncio.sleep(0.05)
                    continue
                self._handle_received_frame(frame)
            except asyncio.CancelledError:
                raise
            except Exception as err:
                _LOGGER.warning("ELTAKO gateway read failed, reopening serial transport: port=%s gateway_type=%s error=%s", self.port, self.gateway_type, err)
                if self._transport is not None:
                    try:
                        await self.hass.async_add_executor_job(self._transport.close)
                    finally:
                        self._transport = None
                    self._notify_gateway_status("read_failed")
                await asyncio.sleep(1)

    def _notify_gateway_status(self, reason: str) -> None:
        """Wake gateway status entities even when no radio telegram arrives.

        Home Assistant binary/status sensors previously updated only when a
        telegram was dispatched. On USB unplug there is no telegram, so the
        Connected entity could stay stale until the next received message.
        """
        self._status_sequence += 1
        telegram = EltakoTelegram(
            sender_id="__gateway_status__",
            eep=None,
            raw=b"",
            decoded={
                "gateway_status": reason,
                "connected": self.is_connected,
                "status_sequence": self._status_sequence,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            },
        )
        self._dispatch(telegram)

    def dispatch_debug_telegram(self, telegram: EltakoTelegram) -> None:
        self._dispatch(telegram)

    def _dispatch(self, telegram: EltakoTelegram) -> None:
        self._last_telegram = telegram
        if telegram.sender_id != "__gateway_status__":
            diagnostic_event(
                self.hass,
                "telegram_received",
                level="debug",
                entry_id=self.entry_id,
                gateway=self.gateway_type,
                port=self.port,
                sender_id=telegram.sender_id,
                eep=telegram.eep,
                raw=telegram.raw,
                decoded=telegram.decoded,
            )
        for listener in list(self._listeners):
            listener(telegram)

    @property
    def last_telegram(self) -> EltakoTelegram | None:
        return self._last_telegram

    @property
    def is_connected(self) -> bool:
        return self._transport is not None and self._transport.is_active()

    @property
    def last_message_received(self) -> str | None:
        return self._last_message_received

    async def async_reconnect(self) -> None:
        _LOGGER.info("Reconnecting ELTAKO gateway entry=%s port=%s", self.entry_id, self.port)
        if self._transport is not None:
            await self.hass.async_add_executor_job(self._transport.close)
            self._transport = None
            self._notify_gateway_status("reconnect_close")
        await self.async_probe()
        await self._async_ensure_transport()
        self._notify_gateway_status("reconnect_open")

    @property
    def last_send_error(self) -> str | None:
        return self._last_send_error

    def _fks_sv_effective_sender_id(self, device: dict[str, Any]) -> str:
        sender_id = _get_sender_id(device)
        if not sender_id:
            raise UnsupportedEltakoCommand("FKS-SV YAML enthaelt keine sender.id")
        return _effective_sender_id_for_gateway(
            sender_id,
            self.gateway_type,
            self.base_id or self.selected_gateway.get("base_id"),
            device=device,
        )

    def _fks_sv_tx_status(self) -> int:
        """Return the ERP1 status byte used for controller replies.

        FAM-USB/EnOcean Programmer transmit paths are more reliable with the
        standard T21/NU radio bits set. Direct RS485 gateway paths keep the
        neutral 4BS status byte.
        """
        return 0x30 if self.gateway_type == GATEWAY_TYPE_FAM_USB else 0x00

    def _fks_sv_lock(self, device: dict[str, Any]) -> asyncio.Lock:
        key = _normalized_address_or_none(device.get("id")) or str(device.get("id") or "fks-sv")
        lock = self._fks_sv_reply_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._fks_sv_reply_locks[key] = lock
        return lock

    async def async_send_fks_sv_control_response(
        self,
        device: dict[str, Any],
        *,
        target_temperature: float,
        room_temperature: float | None,
        hvac_mode: str = "heat",
    ) -> bool:
        """Reply to an FKS-SV while its receive window is open."""
        async with self._fks_sv_lock(device):
            try:
                sender_id = self._fks_sv_effective_sender_id(device)
                status = self._fks_sv_tx_status()
                if str(hvac_mode).lower().endswith("off") or str(hvac_mode).lower() == "off":
                    message = build_a5_20_01_valve_position(
                        sender_id,
                        valve_position=0,
                        room_temperature=room_temperature,
                        status=status,
                    )
                else:
                    message = build_a5_20_01_temperature_setpoint(
                        sender_id,
                        target_temperature=target_temperature,
                        room_temperature=room_temperature,
                        summer_mode=bool(_device_raw_option(device, "summer_mode", False)),
                        status=status,
                    )
                frame = await self._async_send_esp2_message(message)
                self._last_send_error = None
                _LOGGER.info(
                    "FKS-SV control reply sent: device_id=%s sender_id=%s target=%s room_temperature=%s hvac_mode=%s frame=%s",
                    device.get("id"),
                    sender_id,
                    target_temperature,
                    room_temperature,
                    hvac_mode,
                    frame.hex("-"),
                )
                return True
            except Exception as err:
                self._last_send_error = str(err) or err.__class__.__name__
                _LOGGER.exception("FKS-SV control reply failed for %s", device.get("id"))
                return False

    async def async_send_fks_sv_teach_in_response(
        self,
        device: dict[str, Any],
        *,
        query_data: bytes,
        target_temperature: float,
        room_temperature: float | None,
        hvac_mode: str = "heat",
    ) -> bool:
        """Answer an FKS-SV teach-in query and send the current control value."""
        async with self._fks_sv_lock(device):
            try:
                sender_id = self._fks_sv_effective_sender_id(device)
                status = self._fks_sv_tx_status()
                teach_message = build_a5_20_01_teach_in_response(sender_id, query_data, status=status)
                teach_frame = await self._async_send_esp2_message(teach_message)

                # The valve is still awake after the teach-in response. Send the
                # actual setpoint in the same receive window so it can start the
                # reference run and immediately adopt the configured room value.
                await asyncio.sleep(0.05)
                if str(hvac_mode).lower().endswith("off") or str(hvac_mode).lower() == "off":
                    control_message = build_a5_20_01_valve_position(
                        sender_id,
                        valve_position=0,
                        room_temperature=room_temperature,
                        status=status,
                    )
                else:
                    control_message = build_a5_20_01_temperature_setpoint(
                        sender_id,
                        target_temperature=target_temperature,
                        room_temperature=room_temperature,
                        summer_mode=bool(_device_raw_option(device, "summer_mode", False)),
                        status=status,
                    )
                control_frame = await self._async_send_esp2_message(control_message)
                self._last_send_error = None
                _LOGGER.info(
                    "FKS-SV teach-in completed: device_id=%s sender_id=%s teach_frame=%s control_frame=%s",
                    device.get("id"),
                    sender_id,
                    teach_frame.hex("-"),
                    control_frame.hex("-"),
                )
                return True
            except Exception as err:
                self._last_send_error = str(err) or err.__class__.__name__
                _LOGGER.exception("FKS-SV teach-in response failed for %s", device.get("id"))
                return False

    async def async_send_actuator_command(self, device: dict[str, Any], command: str, **kwargs: Any) -> bool:
        """Build and send an actuator command using the internal bus core.

        No eltako14bus/eltakobus EEP classes are required here. The first
        supported send path is ESP2 over FAM14/FGW14-USB RS485.
        """
        try:
            msg = _build_actuator_message(device, command, gateway_type=self.gateway_type, gateway_base_id=self.base_id, **kwargs)
        except UnsupportedCommandError as err:
            self._last_send_error = str(err)
            _LOGGER.warning(
                "ELTAKO command not supported yet: command=%s device_id=%s eep=%s sender_id=%s sender_eep=%s reason=%s",
                command,
                device.get("id"),
                device.get("eep"),
                device.get("sender_id"),
                device.get("sender_eep"),
                err,
            )
            return False
        except Exception as err:
            self._last_send_error = str(err) or err.__class__.__name__
            _LOGGER.exception(
                "Could not build ELTAKO command: command=%s device_id=%s eep=%s sender_id=%s sender_eep=%s error=%s",
                command,
                device.get("id"),
                device.get("eep"),
                device.get("sender_id"),
                device.get("sender_eep"),
                self._last_send_error,
            )
            return False

        self._last_send_error = None
        messages = msg if isinstance(msg, (list, tuple)) else [msg]
        payloads: list[str] = []
        effective_sender_ids: list[str] = []
        for one_msg in messages:
            body = one_msg.body if isinstance(one_msg, ESP2Message) else None
            if body is None and isinstance(one_msg, (bytes, bytearray)):
                raw_frame = bytes(one_msg)
                if len(raw_frame) == 14 and raw_frame.startswith(b"\xA5\x5A"):
                    body = raw_frame[2:13]
            if body is not None and len(body) == 11:
                payloads.append(bytes(body[2:6]).hex("-").upper())
                effective_sender_ids.append(format_address(bytes(body[6:10])))
        model_text = " ".join(
            str(device.get(key) or "")
            for key in ("type", "model", "name", "description")
        ).upper()
        is_frgbw14 = _is_frgbw14_device_config(device)
        frgbw_frame_code = "6B" if is_frgbw14 else None
        is_fhk = (
            str(device.get("eep") or "").strip().upper() == "A5-10-06"
            or str(device.get("sender_eep") or "").strip().upper() == "A5-10-06"
        )
        protocol_role = (
            "frgbw_controller_command"
            if is_frgbw14
            else (
                (
                    "fhk_rps_mode_command"
                    if command in {"set_hvac_mode", "set_preset_mode"}
                    else "fhk_a5_10_06_setpoint_command"
                )
                if is_fhk
                else None
            )
        )
        inter_message_delay = (
            0.02 if is_frgbw14 and len(messages) > 1
            else (0.12 if command == "stop" and len(messages) > 1 else 0.0)
        )
        _LOGGER.info(
            "ELTAKO send start: command=%s device=%s device_id=%s eep=%s sender_id=%s effective_sender_ids=%s sender_eep=%s gateway=%s port=%s messages=%s payloads=%s role=%s delay=%.3fs",
            command, device.get("name"), device.get("id"), device.get("eep"),
            device.get("sender_id"), effective_sender_ids, device.get("sender_eep"), self.gateway_type,
            self.port, len(messages), payloads, protocol_role, inter_message_delay,
        )
        diagnostic_event(
            self.hass,
            "send_start",
            entry_id=self.entry_id,
            gateway=self.gateway_type,
            port=self.port,
            configured_gateway_type=self.configured_gateway_type,
            selected_gateway_type=(self.selected_gateway or {}).get("device_type"),
            stable_serial_path=self.stable_serial_path,
            current_devname=self.current_devname,
            usb_serial=self.usb_serial,
            usb_interface=self.usb_interface,
            baudrate=self.baudrate,
            protocol=self.usb_protocol,
            rs485_mode=False,
            command=command,
            device=device.get("name"),
            device_id=device.get("id"),
            eep=device.get("eep"),
            sender_id=device.get("sender_id"),
            effective_sender_ids=effective_sender_ids,
            sender_eep=device.get("sender_eep"),
            data_hex=payloads,
            protocol_role=protocol_role,
            message_count=len(messages),
            delay=inter_message_delay,
            frame_code=frgbw_frame_code,
        )
        async with self._send_lock:
            _LOGGER.debug("ELTAKO send lock acquired: command=%s device_id=%s", command, device.get("id"))
            diagnostic_event(self.hass, "send_lock_acquired", level="debug", entry_id=self.entry_id, gateway=self.gateway_type, command=command, device_id=device.get("id"))
            for attempt in (1, 2):
                try:
                    await self._async_ensure_transport()
                    frames: list[bytes] = []
                    if is_frgbw14 and len(messages) > 1:
                        for index, one_msg in enumerate(messages):
                            diagnostic_event(
                                self.hass,
                                "telegram_send_attempt",
                                level="debug",
                                entry_id=self.entry_id,
                                gateway=self.gateway_type,
                                command=command,
                                device_id=device.get("id"),
                                sender_id=device.get("sender_id"),
                                index=index + 1,
                                total=len(messages),
                                message=str(one_msg),
                                burst=True,
                            )
                        frames = await asyncio.wait_for(
                            self._async_send_esp2_messages(
                                messages,
                                inter_frame_delay=inter_message_delay,
                            ),
                            timeout=3.0,
                        )
                        for index, frame in enumerate(frames):
                            diagnostic_event(
                                self.hass,
                                "telegram_sent",
                                level="debug",
                                entry_id=self.entry_id,
                                gateway=self.gateway_type,
                                command=command,
                                device_id=device.get("id"),
                                index=index + 1,
                                total=len(frames),
                                frame=frame,
                                burst=True,
                            )
                    else:
                        for index, one_msg in enumerate(messages):
                            _LOGGER.debug(
                                "ELTAKO telegram send %s/%s: command=%s device_id=%s sender_id=%s gateway=%s",
                                index + 1, len(messages), command, device.get("id"),
                                device.get("sender_id"), self.gateway_type,
                            )
                            diagnostic_event(self.hass, "telegram_send_attempt", level="debug", entry_id=self.entry_id, gateway=self.gateway_type, command=command, device_id=device.get("id"), sender_id=device.get("sender_id"), index=index + 1, total=len(messages), message=str(one_msg))
                            frame = await asyncio.wait_for(self._async_send_esp2_message(one_msg), timeout=3.0)
                            frames.append(frame)
                            diagnostic_event(self.hass, "telegram_sent", level="debug", entry_id=self.entry_id, gateway=self.gateway_type, command=command, device_id=device.get("id"), index=index + 1, total=len(messages), frame=frame)
                            _LOGGER.debug(
                                "ELTAKO telegram sent %s/%s: command=%s device_id=%s frame=%s",
                                index + 1, len(messages), command, device.get("id"), frame.hex("-"),
                            )
                            if inter_message_delay and index < len(messages) - 1:
                                await asyncio.sleep(inter_message_delay)
                    self._last_send_error = None
                    diagnostic_event(
                        self.hass,
                        "send_finished",
                        entry_id=self.entry_id,
                        gateway=self.gateway_type,
                        port=self.port,
                        baudrate=self.baudrate,
                        protocol=self.usb_protocol,
                        rs485_mode=False,
                        command=command,
                        device_id=device.get("id"),
                        frames=frames,
                        attempt=attempt,
                    )
                    _LOGGER.info(
                        "ELTAKO send finished: command=%s device_id=%s eep=%s sender_id=%s sender_eep=%s gateway_type=%s base_id=%s port=%s baudrate=%s frames=%s attempt=%s",
                        command, device.get("id"), device.get("eep"), device.get("sender_id"),
                        device.get("sender_eep"), self.gateway_type, self.base_id, self.port,
                        self.baudrate, [frame.hex("-") for frame in frames], attempt,
                    )
                    return True
                except Exception as err:
                    self._last_send_error = str(err) or err.__class__.__name__
                    diagnostic_event(self.hass, "send_failed", level="error", entry_id=self.entry_id, gateway=self.gateway_type, command=command, device_id=device.get("id"), attempt=attempt, error=self._last_send_error)
                    _LOGGER.exception(
                        "ELTAKO send attempt failed: command=%s device_id=%s port=%s gateway_type=%s attempt=%s error=%s",
                        command, device.get("id"), self.port, self.gateway_type, attempt, self._last_send_error,
                    )
                    if self._transport is not None:
                        try:
                            await self.hass.async_add_executor_job(self._transport.close)
                        finally:
                            self._transport = None
                    if attempt == 1:
                        await self.async_probe()
                        await asyncio.sleep(0.5)
                        continue
                    _LOGGER.error(
                        "ELTAKO send failed permanently: command=%s device_id=%s error=%s",
                        command, device.get("id"), self._last_send_error,
                    )
                    return False
        return False

    async def _async_ensure_transport(self) -> None:
        """Ensure exactly one deterministic serial transport is open.

        v0.1.22 intentionally uses the internal pyserial ESP2 transport for RX
        and TX. The temporary eltako14bus hybrid RX path could consume the serial
        port without dispatching frames when its message object could not be
        converted back into a raw ESP2 frame. A single reader is more predictable
        and keeps FAM14/FGW14-USB traffic observable.
        """
        if self._transport is not None and self._transport.is_active():
            if _serial_port_path_available(self.port):
                return
            _LOGGER.info("ELTAKO serial path disappeared, reopening transport: port=%s gateway_type=%s", self.port, self.gateway_type)

        if self._transport is not None:
            await self.hass.async_add_executor_job(self._transport.close)
            self._transport = None
            self._notify_gateway_status("transport_closed")

        resolved_port = await self.hass.async_add_executor_job(_resolve_gateway_serial_port, self.port, self.gateway_type, self.selected_gateway)
        if resolved_port != self.port:
            _LOGGER.info(
                "ELTAKO gateway serial port auto-resolved before open: gateway_type=%s old=%s new=%s",
                self.gateway_type,
                self.port,
                resolved_port,
            )
            self.port = resolved_port

        await self._async_refresh_port_descriptor()

        mismatch = await self.hass.async_add_executor_job(_port_descriptor_mismatches_gateway, self.port, self.gateway_type)
        if mismatch:
            self._last_send_error = mismatch
            raise RuntimeError(mismatch)

        self.baudrate = 9600 if self.gateway_type == GATEWAY_TYPE_FAM_USB else 57600
        self.message_delay = 0.10 if self.gateway_type == GATEWAY_TYPE_FAM_USB else (0.001 if self.gateway_type == GATEWAY_TYPE_FAM14 else 0.01)
        # FAM14 and FGW14-USB expose an ESP2 serial interface through their
        # FTDI adapter. Grimm/eltako14bus writes it as a normal serial port;
        # enabling pyserial's RS485Settings would add RTS direction control
        # that these gateways neither require nor use.
        enable_rs485 = False
        self._transport = SerialTransport(
            self.port,
            baudrate=self.baudrate,
            timeout=0.2,
            write_timeout=1.0,
            delay=self.message_delay,
            rs485_mode=enable_rs485,
        )
        await self.hass.async_add_executor_job(self._transport.open)
        self._notify_gateway_status("transport_open")
        self._rx_mode = "internal_pyserial"
        _LOGGER.info(
            "ELTAKO gateway using internal ESP2 serial transport: port=%s gateway_type=%s baudrate=%s rs485_mode=%s",
            self.port,
            self.gateway_type,
            self.baudrate,
            enable_rs485,
        )

    async def _async_send_esp2_message(self, msg: Any) -> bytes:
        await self._async_ensure_transport()
        if self._transport is None:
            raise RuntimeError("Serial transport is not initialized")
        return await self.hass.async_add_executor_job(self._transport.send, msg)

    async def _async_send_esp2_messages(
        self,
        messages: list[Any] | tuple[Any, ...],
        *,
        inter_frame_delay: float,
    ) -> list[bytes]:
        await self._async_ensure_transport()
        if self._transport is None:
            raise RuntimeError("Serial transport is not initialized")
        return await self.hass.async_add_executor_job(
            lambda: self._transport.send_many(
                messages,
                inter_frame_delay=inter_frame_delay,
            )
        )


# Backwards-compatible alias used by entity modules.
class UnsupportedEltakoCommand(UnsupportedCommandError):
    """Raised when an actuator command cannot be represented safely yet."""



def _rgbw_model_text(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("type"),
            device.get("model"),
            raw.get("name"),
            raw.get("device_type"),
            raw.get("comment"),
        )
    ).upper()


def _is_frgbw14_device_config(device: dict[str, Any]) -> bool:
    return "FRGBW14" in _rgbw_model_text(device)


def _is_rgbw_device_config(device: dict[str, Any]) -> bool:
    device_eep = str(device.get("eep") or "").strip().upper()
    sender_eep = str(device.get("sender_eep") or "").strip().upper()
    model_text = _rgbw_model_text(device)
    return (
        device_eep in {"07-3F-7F"}
        or sender_eep in {"07-3F-7F"}
        or "FRGBW14" in model_text
        or "FRGBW71" in model_text
    )


def _hs_to_rgb_tuple(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        h = float(value[0]) % 360.0
        sat = max(0.0, min(100.0, float(value[1]))) / 100.0
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, sat, 1.0)
        return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))
    except Exception:
        return None


# A5-38-08 / FUNC=38 command-2 dimmer learn telegram.
# Data bytes are ordered DB3, DB2, DB1, DB0.
TEACH_IN_A5_38_08_DIMMER_FUNC38 = bytes([0xE0, 0x40, 0x0D, 0x80])

# FRGBW14 / FRGBW71L free profile EEP 07-3F-7F learn telegram.
# GFA5-confirmed DB3..DB0: FF-F8-0D-87. This is required for the free RGB profile teach-in.
TEACH_IN_07_3F_7F_RGBW_FREE_PROFILE = bytes([0xFF, 0xF8, 0x0D, 0x87])

# ELTAKO controller teach-in matrix from "Inhalte der ELTAKO-Funktelegramme".
# All payloads are DB3, DB2, DB1, DB0.
TEACH_IN_FUNC38_SWITCH_CMD1 = bytes([0xE0, 0x40, 0x0D, 0x80])
TEACH_IN_FUNC38_DIMMER_CMD2 = bytes([0xE0, 0x40, 0x0D, 0x80])
TEACH_IN_FSUD_230V_DIMMER = bytes([0x02, 0x00, 0x00, 0x00])
TEACH_IN_FUNC3F_COVER_7F = bytes([0xFF, 0xF8, 0x0D, 0x80])
TEACH_IN_A5_20_01_FKS_SV = bytes([0x80, 0x08, 0x0D, 0x80])
# This integration uses this A5-10-06 teach-in payload for
# climate/thermostat controllers. It is different from the normal runtime
# set-temperature telegram and is required for FHK/F4HK/FUTH style learning.
TEACH_IN_A5_10_06_HEATING_COOLING = bytes([0x40, 0x30, 0x0D, 0x87])
TEACH_IN_FD2G14_COLOR_TEMP = bytes([0xE0, 0x40, 0x0D, 0x80])
TEACH_IN_FHK61SSR_PWM = bytes([0xE0, 0x40, 0x0D, 0x80])


# F6-02-01 rocker teach-in pattern used by many decentral 61/62 devices
# when they are taught as an ELTAKO TF/rocker. 0x70 corresponds to the
# top/right rocker press in the common F6-02 layout; a release frame prevents
# the actuator from treating the teach-in as a long press.
def _build_f6_02_01_teach_in_sequence(sender_id: str) -> list[Any]:
    return [
        build_f6_02_01_rocker(sender_id, action=3, pressed=True, status=0x31),
        build_f6_02_01_rocker(sender_id, action=0, pressed=False, status=0x20),
        build_f6_02_01_rocker(sender_id, action=3, pressed=True, status=0x31),
    ]


def _normalize_device_specific_decoded(device: dict[str, Any], decoded: dict[str, Any]) -> None:
    """Remove cross-profile aliases and add a clear device-specific state.

    Several ELTAKO devices share the same EEP. The generic decoder therefore
    exposes compatibility aliases for every possible consumer. Once the YAML
    device is known, keep only the semantics that belong to that device.
    """
    name = str(device.get("name") or device.get("device_family") or "").upper()
    eep = str(device.get("eep") or "").upper()

    if "FSM60B" in name and eep == "A5-30-03":
        wet = bool(decoded.get("moisture", decoded.get("water_alarm", decoded.get("alarm", False))))
        decoded.update({
            "moisture": wet,
            "wet": wet,
            "water_alarm": wet,
            "state": "nass" if wet else "trocken",
            "telegram_type": "fsm60b_mode_3_moisture",
        })
        for key in (
            "smoke_alarm", "temperature", "temperature_raw", "alarm",
            "pressed", "open", "closed",
        ):
            decoded.pop(key, None)
        return

    if ("FRWB" in name or "FHMB" in name) and eep == "A5-30-03":
        alarm = bool(decoded.get("smoke_alarm", decoded.get("alarm", False)))
        decoded["alarm"] = alarm
        decoded["state"] = "Alarm" if alarm else "kein Alarm"
        decoded["telegram_type"] = "a5_30_03_alarm_temperature"
        for key in ("moisture", "wet", "water_alarm", "pressed", "open", "closed"):
            decoded.pop(key, None)
        return

    if "FFG7B" in name or "FTKE" in name or "FFTE" in name:
        if "window_state" in decoded:
            decoded["state"] = decoded["window_state"]

    if eep in {"A5-07-01", "A5-08-01"} and ("FBH" in name or "FBHT" in name):
        movement = bool(decoded.get("movement", decoded.get("motion", False)))
        decoded["state"] = "Bewegung" if movement else "keine Bewegung"

    if eep == "A5-13-01" and ("FWS61" in name or "FWG14MS" in name):
        if "rain" in decoded:
            decoded["state"] = "Regen" if decoded.get("rain") else "kein Regen"


def _device_name_upper(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    return " ".join(
        str(value or "")
        for value in (
            device.get("name"),
            device.get("device_type"),
            raw.get("name"),
            raw.get("device_type"),
            raw.get("model"),
            raw.get("comment"),
        )
    ).upper()



def _is_cover_direct_command_device(device: dict[str, Any], sender_eep: str, device_eep: str, platform: str) -> bool:
    """FSB/FJ direct travel command, FUNC=3F / TYPE=7F."""
    name = _device_name_upper(device)
    return (
        platform == "cover"
        or sender_eep in {"H5-3F-7F", "G5-3F-7F", "A5-3F-7F"}
        or device_eep in {"H5-3F-7F", "G5-3F-7F", "A5-3F-7F"}
        or any(model in name for model in ("FSB14", "FSB61", "FSB71", "FJ62", "FJ62NP", "FJ62NPN"))
    )


def _is_func38_switch_device(device: dict[str, Any], sender_eep: str, device_eep: str) -> bool:
    """Direct switching command, FUNC=38 / Command 1."""
    name = _device_name_upper(device)
    switch_models = (
        "FSR14", "FSR71", "FMZ14", "FSR61", "FSR61NP", "FSR61G", "FSR61LN",
        "FLC61NP", "FR62", "FR62NP", "FL62", "FL62NP",
    )
    return any(model in name for model in switch_models) or device_eep in {"M5-38-08"}


def _is_func38_dimmer_device(device: dict[str, Any], sender_eep: str, device_eep: str) -> bool:
    """Direct dimming command, FUNC=38 / Command 2."""
    name = _device_name_upper(device)
    dimmer_models = (
        "FUD14", "FUD71", "FDG14", "FD2G14", "FUD61NP", "FUD61NPN", "FD62NP", "FD62NPN",
    )
    return sender_eep == "A5-38-08" or device_eep == "A5-38-08" or any(model in name for model in dimmer_models)


def _is_fsud_230v(device: dict[str, Any]) -> bool:
    name = _device_name_upper(device)
    return "FSUD" in name


def _is_fhk_pwm_device(device: dict[str, Any], sender_eep: str, device_eep: str) -> bool:
    name = _device_name_upper(device)
    return "FHK61SSR" in name


def _prefers_rocker_teach_in(device: dict[str, Any], sender_eep: str, device_eep: str, platform: str) -> bool:
    name = _device_name_upper(device)
    if sender_eep in {"F6-02-01"}:
        return True
    # Shading/roller actuators and simple relay/switch actuators from the
    # decentralized 61/62 families commonly learn a rocker telegram first.
    # FUD/FD dimmers are intentionally excluded because their documented
    # software teach-in uses FUNC=38 / A5-38-08 (E0-40-0D-80).
    rocker_models = (
        "FSR61", "FSR71", "FLC61NP", "FL62", "FSB61", "FSB71", "FJ62",
    )
    dimmer_models = ("FUD14", "FUD71", "FDG14", "FUD61", "FD62")
    if any(model in name for model in dimmer_models):
        return False
    if any(model in name for model in rocker_models):
        return True
    if platform == "cover" and (sender_eep == "H5-3F-7F" or device_eep in {"G5-3F-7F", "A5-3F-7F"}):
        return True
    return False



def _fam_usb_4bs_rf_variants(address: bytes, data: bytes) -> list[Any]:
    """Return 4BS TX variants that FAM-USB/TCM variants accept reliably.

    Some FAM-USB / EnOcean Programmer combinations ignore 4BS transmit frames
    with a zero status byte although the frame is syntactically valid ESP2.
    ELTAKO/EnOcean tools commonly use a status byte with NU/T21 bits set for
    radio transmission. For teach-in this helper sends the same ERP payload
    first in the strict form and then in the radio-safe form so a second FAM-USB
    sniffer or a FAM14 must see at least one RF telegram.
    """
    return [
        build_regular_4bs(address, data, status=0x00, outgoing=True),
        build_regular_4bs(address, data, status=0x30, outgoing=True),
    ]




def _is_fms14_device(device: dict[str, Any]) -> bool:
    """Return True for an FMS14 channel definition.

    FMS14 is a two-channel Series-14 actor. EEDTOY represents each channel as
    its own switch entity/address, therefore the command builder must use the
    sender/channel address of the individual YAML entry without collapsing the
    two channels.
    """
    if not isinstance(device, dict):
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
    return "FMS14" in text

def _get_sender_id(device: dict[str, Any]) -> str:
    sender_id = str(device.get("sender_id") or "").strip()
    if not sender_id and isinstance(device.get("sender"), dict):
        sender_id = str(device["sender"].get("id") or "").strip()
    if not sender_id and isinstance(device.get("raw"), dict):
        raw_sender = device["raw"].get("sender")
        if isinstance(raw_sender, dict):
            sender_id = str(raw_sender.get("id") or "").strip()
    return sender_id

def _get_sender_eep(device: dict[str, Any]) -> str:
    sender_eep = str(device.get("sender_eep") or "").strip().upper()
    if not sender_eep and isinstance(device.get("sender"), dict):
        sender_eep = str(device["sender"].get("eep") or "").strip().upper()
    if not sender_eep and isinstance(device.get("raw"), dict):
        raw_sender = device["raw"].get("sender")
        if isinstance(raw_sender, dict):
            sender_eep = str(raw_sender.get("eep") or "").strip().upper()
    return sender_eep




def _fam_usb_effective_sender_id(sender_id: str, gateway_base_id: str | None) -> str:
    """Return a sender id that a FAM-USB can actually transmit.

    FAM-USB/EnOcean TCM devices can only transmit radio telegrams from their
    own base-id range. Series-14 YAML often contains learned bus sender ids like
    00-00-B0-04. Those are valid for FAM14/FGW14 bus programming, but a FAM-USB
    will not put them on RF. For FAM-USB we therefore keep the sender offset
    byte and replace the first three bytes by the gateway base-id prefix, e.g.
    00-00-B0-04 with base FF-A6-07-00 becomes FF-A6-07-04.
    """
    original = format_address(parse_address(sender_id))
    if not gateway_base_id:
        return original
    try:
        sender = parse_address(original)
        base = parse_address(gateway_base_id)
    except Exception:
        return original
    if sender[:3] == base[:3]:
        return original
    effective = bytes([base[0], base[1], base[2], sender[3]])
    return format_address(effective)


def _series14_pct_offset_from_device(device: dict[str, Any]) -> int | None:
    """Extract the Series-14 PCT address/channel offset from the YAML device.

    For a FAM-USB controlling Series-14 actors through a FAM14, the controller
    sender must be built like the multiple-gateway mapping: FAM-USB
    base-id + the Series-14 internal address. The plain sender.id field can be
    stale or imported from a different gateway section. Therefore for Series-14
    devices we prefer the explicit PCT address 00-00-00-xx from device.id/name
    over sender.id. This fixes cases where a cover named 00-00-00-0B was
    transmitted as FF-A6-07-4D.
    """
    import re

    candidates: list[str] = []
    for key in ("id", "device_id"):
        value = device.get(key)
        if value not in (None, ""):
            candidates.append(str(value))
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    for key in ("id", "device_id", "address", "base_address", "pct14_address", "entry_address", "comment", "name", "device_type"):
        value = raw.get(key)
        if value not in (None, ""):
            candidates.append(str(value))
    for key in ("name", "comment", "device_type", "model"):
        value = device.get(key)
        if value not in (None, ""):
            candidates.append(str(value))

    for text in candidates:
        match = re.search(r"00-00-00-([0-9A-Fa-f]{1,2})", text)
        if match:
            return int(match.group(1), 16) & 0xFF

    for text in candidates:
        match = re.search(r"PCT14\s+Adresse\s+(\d+)", text, re.IGNORECASE)
        if match:
            value = int(match.group(1), 10)
            if 0 <= value <= 0xFF:
                return value
    return None


def _fam_usb_effective_sender_id_for_device(device: dict[str, Any], sender_id: str, gateway_base_id: str | None) -> str:
    """FAM-USB sender mapping for Series-14 and wireless actors.

    The YAML sender.id is the authoritative HA/controller sender.  Earlier
    builds preferred a PCT/device address parsed from comments or names.  That
    can produce a wrong RF sender for multi-channel cover actors, e.g. an
    FSB entry named 00-00-00-0B being transmitted as FF-A6-07-4D.

    For FAM-USB the EnOcean TCM can only send from its own base-id range, so
    we keep the low byte of sender.id and replace only the prefix with the
    FAM-USB base-id.  Only if sender.id is absent/invalid do we fall back to
    a PCT address parsed from the device metadata.
    """
    if not gateway_base_id:
        return _fam_usb_effective_sender_id(sender_id, gateway_base_id)
    try:
        base = parse_address(gateway_base_id)
    except Exception:
        return _fam_usb_effective_sender_id(sender_id, gateway_base_id)

    try:
        sender = parse_address(format_address(parse_address(sender_id)))
        effective = bytes([base[0], base[1], base[2], sender[3]])
        return format_address(effective)
    except Exception:
        pass

    offset = _series14_pct_offset_from_device(device)
    if offset is not None:
        effective = bytes([base[0], base[1], base[2], offset])
        return format_address(effective)
    return _fam_usb_effective_sender_id(sender_id, gateway_base_id)


def _effective_sender_id_for_gateway(sender_id: str, gateway_type: str | None, gateway_base_id: str | None = None, device: dict[str, Any] | None = None) -> str:
    gw_type = str(gateway_type or "").strip().lower()
    if isinstance(device, dict) and _is_frgbw14_device_config(device) and gw_type != GATEWAY_TYPE_FAM_USB:
        # Direct Series-14 control uses the internal 00-00-B0-xx controller ID
        # entered in the actuator.  A radio transceiver is different: it can
        # only transmit from its own base-ID range and is handled below.
        return format_address(parse_address(sender_id))
    if gw_type == GATEWAY_TYPE_FAM_USB:
        if isinstance(device, dict):
            return _fam_usb_effective_sender_id_for_device(device, sender_id, gateway_base_id)
        return _fam_usb_effective_sender_id(sender_id, gateway_base_id)
    return format_address(parse_address(sender_id))


def _sender_id_in_gateway_base_range(sender_id: str, gateway_base_id: str | None) -> str:
    """Map a logical HA sender offset into the selected gateway base-id range.

    Series-14 devices such as FRGBW14 must receive controller telegrams from an
    address that belongs to the selected FAM14/FGW14-USB gateway. EEDTOY/PCT14
    exports can contain logical sender ids such as 00-00-B0-01. For the actual
    TX telegram we keep the low offset byte and replace the prefix with the
    gateway base-id prefix, for example 00-00-B0-01 with base FF-D8-9D-00
    becomes FF-D8-9D-01. Explicit sender ids already in the base range stay
    unchanged.
    """
    original = format_address(parse_address(sender_id))
    if not gateway_base_id:
        return original
    try:
        sender = parse_address(original)
        base = parse_address(gateway_base_id)
    except Exception:
        return original
    if sender[:3] == base[:3]:
        return original
    return format_address(bytes([base[0], base[1], base[2], sender[3]]))

def _build_teach_in_message(device: dict[str, Any], gateway_type: str | None = None, gateway_base_id: str | None = None) -> Any:
    """Build a documented ELTAKO teach-in telegram for this device.

    The mapping is intentionally based on the ELTAKO telegram table instead of
    falling back to normal ON/OFF commands:

    * FUNC=38 Command 1 switch actors:      E0-40-0D-80
    * FUNC=38 Command 2 dimmers:            E0-40-0D-80
      (FSUD-230V special learn payload:     02-00-00-00)
    * FUNC=3F TYPE=7F covers/shutters:      FF-F8-0D-80
    * FRGBW free profile 07-3F-7F:          FF-F8-0D-87

    If a device class is not documented here, the function raises an explicit
    error. Sending a normal command as a substitute for learn telegrams caused
    confusing failures and is deliberately not done anymore.
    """
    sender_id = _get_sender_id(device)
    sender_eep = _get_sender_eep(device) or str(device.get("eep") or "").strip().upper()
    device_eep = str(device.get("eep") or "").strip().upper()
    platform = str(device.get("platform") or "").strip().lower()
    gw_type = str(gateway_type or "").strip().lower()
    if not sender_id:
        raise UnsupportedEltakoCommand("YAML enthaelt keinen sender.id fuer das Lerntelegramm")

    # FAM-USB can only transmit from its own base-id range. Direct FAM14/FGW14
    # bus paths keep the sender id from YAML/PCT14 unchanged.
    effective_sender_id = _effective_sender_id_for_gateway(sender_id, gw_type, gateway_base_id, device=device)
    if effective_sender_id != format_address(parse_address(sender_id)):
        _LOGGER.info(
            "ELTAKO teach-in sender id translated to gateway base range: original=%s effective=%s base_id=%s device=%s",
            sender_id,
            effective_sender_id,
            gateway_base_id,
            device.get("name"),
        )
    address = parse_address(effective_sender_id)

    name = _device_name_upper(device)
    status = 0x80 if gw_type == GATEWAY_TYPE_FAM_USB else 0x00

    if _is_rgbw_device_config(device) or sender_eep in {"07-3F-7F"} or device_eep in {"07-3F-7F"}:
        _LOGGER.info("ELTAKO teach-in matrix selected: FRGBW free profile 07-3F-7F, payload=FF-F8-0D-87 device=%s", device.get("name"))
        return [build_regular_4bs(address, TEACH_IN_07_3F_7F_RGBW_FREE_PROFILE, status=status, outgoing=True)]

    if _is_cover_direct_command_device(device, sender_eep, device_eep, platform):
        _LOGGER.info("ELTAKO teach-in matrix selected: FUNC=3F TYPE=7F cover/shutter, payload=FF-F8-0D-80 device=%s", device.get("name"))
        return [build_regular_4bs(address, TEACH_IN_FUNC3F_COVER_7F, status=status, outgoing=True)]

    if _is_fsud_230v(device):
        _LOGGER.info("ELTAKO teach-in matrix selected: FSUD-230V special dimmer learn, payload=02-00-00-00 device=%s", device.get("name"))
        return [build_regular_4bs(address, TEACH_IN_FSUD_230V_DIMMER, status=status, outgoing=True)]

    if _is_func38_dimmer_device(device, sender_eep, device_eep):
        _LOGGER.info("ELTAKO teach-in matrix selected: FUNC=38 Command 2 dimmer, payload=E0-40-0D-80 device=%s", device.get("name"))
        return [build_regular_4bs(address, TEACH_IN_FUNC38_DIMMER_CMD2, status=status, outgoing=True)]

    if _is_func38_switch_device(device, sender_eep, device_eep):
        _LOGGER.info("ELTAKO teach-in matrix selected: FUNC=38 Command 1 switch, payload=E0-40-0D-80 device=%s", device.get("name"))
        return [build_regular_4bs(address, TEACH_IN_FUNC38_SWITCH_CMD1, status=status, outgoing=True)]

    if _is_fhk_pwm_device(device, sender_eep, device_eep):
        _LOGGER.info("ELTAKO teach-in matrix selected: FHK61SSR PWM, payload=E0-40-0D-80 device=%s", device.get("name"))
        return [build_regular_4bs(address, TEACH_IN_FHK61SSR_PWM, status=status, outgoing=True)]

    if _is_futh55ed_device(device) and not (sender_eep == "A5-10-06" or device_eep == "A5-10-06"):
        raise UnsupportedEltakoCommand(
            "Für dieses FUTH55-Profil ist kein virtueller HA-Sender vorgesehen"
        )

    if sender_eep == "A5-20-01" or device_eep == "A5-20-01" or "FKS-SV" in name:
        raise UnsupportedEltakoCommand(
            "FKS-SV wird bidirektional eingelernt: Integration aktiv lassen und den Taster am Ventil kurz druecken"
        )

    if sender_eep == "A5-10-06" or device_eep == "A5-10-06" or "FHK14" in name or "F4HK14" in name:
        _LOGGER.info("ELTAKO teach-in matrix selected: A5-10-06 heating/cooling, payload=40-30-0D-87 status=80 device=%s", device.get("name"))
        return [build_regular_4bs(address, TEACH_IN_A5_10_06_HEATING_COOLING, status=0x80, outgoing=True)]

    raise UnsupportedEltakoCommand(f"Kein dokumentiertes Lerntelegramm fuer sender.eep {sender_eep or device_eep} / device {device.get('name')}")

def _build_actuator_message(device: dict[str, Any], command: str, **kwargs: Any) -> Any:
    sender_id = _get_sender_id(device)
    gateway_type = kwargs.get("gateway_type")
    gateway_base_id = kwargs.get("gateway_base_id")
    sender_eep = _get_sender_eep(device)
    device_eep = str(device.get("eep") or "").strip().upper()
    platform = str(device.get("platform") or "").strip().lower()

    if not sender_id:
        raise UnsupportedEltakoCommand("YAML enthaelt keinen sender.id fuer diesen Aktor")

    if command == "teach_in":
        return _build_teach_in_message(device, gateway_type, gateway_base_id)

    if command == "frgbw_free_profile_teach_in":
        if not (_is_rgbw_device_config(device) or sender_eep in {"07-3F-7F"} or device_eep in {"07-3F-7F"}):
            raise UnsupportedEltakoCommand("FRGBW freies Profil ist nur fuer FRGBW/07-3F-7F vorgesehen")
        effective_sender_id = _effective_sender_id_for_gateway(sender_id, gateway_type, gateway_base_id, device=device)
        if effective_sender_id != format_address(parse_address(sender_id)):
            _LOGGER.info("ELTAKO FAM-USB sender id translated to gateway base range: original=%s effective=%s base_id=%s command=%s device=%s", sender_id, effective_sender_id, gateway_base_id, command, device.get("name"))
        if _is_frgbw14_device_config(device):
            raise UnsupportedEltakoCommand(
                "FRGBW14 ist ein Series-14-Busaktor; die Controller-ID wird in PCT14/YAML zugeordnet, nicht per HA-Lerntelegramm"
            )
        address = parse_address(effective_sender_id)
        _LOGGER.info("ELTAKO FRGBW free-profile teach-in: device=%s sender_id=%s payload=FF-F8-0D-87 status=81", device.get("name"), effective_sender_id)
        return [
            build_regular_4bs(address, TEACH_IN_07_3F_7F_RGBW_FREE_PROFILE, status=0x81, outgoing=True)
        ]

    if command in {"teach_in_rocker_top", "teach_in_rocker_up", "teach_in_rocker_down"}:
        effective_sender_id = _effective_sender_id_for_gateway(sender_id, gateway_type, gateway_base_id, device=device)
        if effective_sender_id != format_address(parse_address(sender_id)):
            _LOGGER.info(
                "ELTAKO rocker teach-in sender id translated to gateway base range: original=%s effective=%s base_id=%s command=%s device=%s",
                sender_id,
                effective_sender_id,
                gateway_base_id,
                command,
                device.get("name"),
            )
        # ELTAKO F6-02-01 rocker positions from the telegram table:
        # 0x70 = top/up press, 0x50 = bottom/down press, 0x00 = release.
        action = 2 if command == "teach_in_rocker_down" else 3
        data_label = "50" if action == 2 else "70"
        _LOGGER.info(
            "ELTAKO rocker teach-in selected: command=%s sender_id=%s data=%s-00-%s device=%s",
            command,
            effective_sender_id,
            data_label,
            data_label,
            device.get("name"),
        )
        return [
            build_f6_02_01_rocker(effective_sender_id, action=action, pressed=True, status=0x31),
            build_f6_02_01_rocker(effective_sender_id, action=0, pressed=False, status=0x20),
            build_f6_02_01_rocker(effective_sender_id, action=action, pressed=True, status=0x31),
        ]

    if not sender_eep:
        raise UnsupportedEltakoCommand("YAML enthaelt keinen sender.eep fuer diesen Aktor")

    effective_sender_id = _effective_sender_id_for_gateway(sender_id, gateway_type, gateway_base_id, device=device)
    # v0.1.91: FRGBW14 on FAM14/FGW14-USB now uses the exact same RS485/ESP2
    # transmit principle as working Series-14 actors such as FSR14: the YAML
    # sender.id is the controller identity already written/known in PCT14. Do
    # not remap it into the FAM14 base-id range here; doing so changes the
    # learned sender and prevents the bus actor from reacting.
    if effective_sender_id != format_address(parse_address(sender_id)):
        _LOGGER.info("ELTAKO sender id translated to gateway base range: original=%s effective=%s base_id=%s command=%s device=%s gateway_type=%s", sender_id, effective_sender_id, gateway_base_id, command, device.get("name"), gateway_type)
    sender_id = effective_sender_id
    gw_type = str(gateway_type or "").strip().lower()
    # FRGBW14 is a Series-14 bus actuator.  A host-to-gateway frame is always a
    # TRT/0x6B send request.  The 0x0B frames seen in a sniffer are receive
    # telegrams emitted by the gateway and must never be written back as TX.
    frgbw_destination_id = None
    if _is_frgbw14_device_config(device):
        if gw_type != GATEWAY_TYPE_FAM_USB and not sender_id.upper().startswith("00-00-B0-"):
            raise UnsupportedEltakoCommand(
                "FRGBW14 am Series-14-Bus benoetigt eine in PCT14 programmierte "
                "interne Controller-ID 00-00-B0-xx; eine GFA5-Funk-ID ist kein Ersatz"
            )
        _LOGGER.info(
            "ELTAKO FRGBW14 controller path selected: device=%s device_id=%s sender_id=%s gateway_type=%s base_id=%s destination_id=none status=80 h_seq=TRT frame_code=6B",
            device.get("name"),
            device.get("id"),
            sender_id,
            gateway_type,
            gateway_base_id,
        )

    if platform == "switch" and _is_fms14_device(device):
        # FMS14 is controlled like the working FSR14 Series-14 actors: use the
        # learned A5-38-08 central switching sender.  ORG 0x05 telegrams with
        # 0x70/0x50 are actuator feedback, not the HA control telegram.
        # ON  = 01-00-00-09, OFF = 01-00-00-08, status 0x00.
        if command in {"turn_on", "turn_off"}:
            _LOGGER.info(
                "ELTAKO FMS14 A5-38-08 switch path selected: device=%s device_id=%s sender_id=%s command=%s payload=%s",
                device.get("name"),
                device.get("id"),
                sender_id,
                command,
                "01-00-00-09" if command == "turn_on" else "01-00-00-08",
            )
            return build_a5_38_08_switch(sender_id, command == "turn_on")

    if platform == "light":
        if _is_rgbw_device_config(device):
            # FRGBW14 and FRGBW71L use the ELTAKO 07-3F-7F RGB component data
            # model. For FRGBW14, sender.id is the controller identity already
            # present in the actuator's PCT14 sensor/controller relation.
            is_frgbw14 = _is_frgbw14_device_config(device)
            # The working GFA5 trace uses status 0x80 on the Series-14 path.
            # Do not derive this from the gateway label (which may be "auto").
            rgbw_status = 0x80 if is_frgbw14 else 0x81
            if command == "turn_off":
                return build_07_3f_7f_off_messages(
                    sender_id,
                    destination_id=frgbw_destination_id,
                    include_white_zero=False,
                    status=rgbw_status,
                    outgoing=True,
                )
            if command == "turn_on":
                rgbw = kwargs.get("rgbw_color")
                rgb = kwargs.get("rgb_color")
                brightness = int(kwargs.get("brightness", 255) or 255)
                if isinstance(rgbw, (list, tuple)) and len(rgbw) >= 4:
                    return build_07_3f_7f_rgbw_messages(
                        sender_id,
                        destination_id=frgbw_destination_id,
                        r=int(rgbw[0]),
                        g=int(rgbw[1]),
                        b=int(rgbw[2]),
                        w=int(rgbw[3]),
                        brightness=brightness,
                        state=True,
                        status=rgbw_status,
                        include_white=False,
                        outgoing=True,
                    )
                if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
                    return build_07_3f_7f_rgbw_messages(
                        sender_id,
                        destination_id=frgbw_destination_id,
                        r=int(rgb[0]),
                        g=int(rgb[1]),
                        b=int(rgb[2]),
                        w=0,
                        brightness=brightness,
                        state=True,
                        status=rgbw_status,
                        include_white=False,
                        outgoing=True,
                    )
                if is_frgbw14:
                    # Never mix A5-38-08 with the free RGBW profile for
                    # FRGBW14. A plain ON sends a complete visible white target
                    # using the same 0x10/0x11/0x12 byte mapping as FRGBW71L.
                    return build_07_3f_7f_rgbw_messages(
                        sender_id,
                        destination_id=frgbw_destination_id,
                        r=255,
                        g=255,
                        b=255,
                        w=0,
                        brightness=brightness,
                        state=True,
                        status=rgbw_status,
                        include_white=False,
                        outgoing=True,
                    )
                # Keep the already working FRGBW71L plain-ON behavior.
                if gw_type in (GATEWAY_TYPE_FAM14, GATEWAY_TYPE_FGW14USB):
                    return build_07_3f_7f_rgbw_messages(
                        sender_id,
                        destination_id=frgbw_destination_id,
                        r=255,
                        g=255,
                        b=255,
                        w=0,
                        brightness=255,
                        state=True,
                        status=0x81,
                    )
                return [build_a5_38_08_dimming(sender_id, 100, ramping_time=0, state=True) for _ in range(3)]

        if sender_eep == "A5-38-08":
            dimming_speed = _safe_int(_device_raw_option(device, "dimming_speed", 0), 0)
            dimming_speed = max(0, min(255, dimming_speed))
            if command == "turn_on":
                brightness = int(kwargs.get("brightness", 255) or 255)
                if device_eep == "A5-38-08":
                    percent = max(1, min(100, int(round(brightness / 255.0 * 100.0))))
                    return build_a5_38_08_dimming(sender_id, percent, ramping_time=dimming_speed, state=True)
                return build_a5_38_08_switch(sender_id, True)

            if command == "turn_off":
                if device_eep == "A5-38-08":
                    return build_a5_38_08_dimming(sender_id, 0, ramping_time=dimming_speed, state=False)
                return build_a5_38_08_switch(sender_id, False)

        if sender_eep in ("F6-02-01",):
            # Diagnostic/fallback only. Series-14 actuators generated by EEDTOY
            # should normally use sender.eep A5-38-08 for light commands.
            action = 1 if command == "turn_on" else 0
            return build_f6_02_01_rocker(sender_id, action=action, pressed=True)

    if platform == "climate":
        if sender_eep == "A5-20-01" or device_eep == "A5-20-01":
            if command == "set_temperature":
                return build_a5_20_01_temperature_setpoint(
                    sender_id,
                    target_temperature=kwargs.get("temperature"),
                    room_temperature=kwargs.get("current_temperature"),
                )
            if command == "set_hvac_mode":
                hvac_mode = str(kwargs.get("hvac_mode") or "heat")
                raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
                if hvac_mode.endswith("off") or hvac_mode == "off":
                    return build_a5_20_01_valve_position(sender_id, valve_position=0)
                target = raw.get("target_temperature") or raw.get("min_target_temperature") or 20
                return build_a5_20_01_temperature_setpoint(sender_id, target_temperature=target)
            if command == "set_valve_position":
                return build_a5_20_01_valve_position(sender_id, valve_position=kwargs.get("valve_position", 0))

        if sender_eep != "A5-10-06" and device_eep != "A5-10-06":
            raise UnsupportedEltakoCommand(f"Climate sender.eep {sender_eep} wird noch nicht unterstuetzt")
        if command == "set_temperature":
            return build_a5_10_06_room_control(
                sender_id,
                target_temperature=kwargs.get("temperature"),
                # Match the established software-controller implementation:
                # DB1=0x00 (40 C placeholder). The room sensor learned in FHK
                # function group 1 provides the authoritative actual value.
                current_temperature=None,
                # Preserve the current actuator mode exactly as Grimm does
                # when changing only the target temperature.
                hvac_mode=kwargs.get("heater_mode") or "heat",
                priority=(device.get("priority") or (device.get("raw") if isinstance(device.get("raw"), dict) else {}).get("priority")),
            )
        if command == "set_hvac_mode":
            hvac_mode = str(kwargs.get("hvac_mode") or "heat")
            return build_fhk_mode_command(sender_id, hvac_mode)
        if command == "set_preset_mode":
            return build_fhk_mode_command(sender_id, kwargs.get("preset_mode"))

    if platform == "cover":
        if sender_eep != "H5-3F-7F":
            raise UnsupportedEltakoCommand(f"Cover sender.eep {sender_eep} wird noch nicht unterstuetzt")
        raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
        if command == "open":
            configured = _safe_int(raw.get("time_opens"), 254) + 1
            requested = kwargs.get("duration_seconds")
            seconds = configured if requested is None else max(1, int(round(float(requested))))
            return build_h5_3f_7f_cover(sender_id, "open", duration_seconds=min(seconds, 255))
        if command == "close":
            configured = _safe_int(raw.get("time_closes"), 254) + 1
            requested = kwargs.get("duration_seconds")
            seconds = configured if requested is None else max(1, int(round(float(requested))))
            return build_h5_3f_7f_cover(sender_id, "close", duration_seconds=min(seconds, 255))
        if command == "stop":
            # Wireless cover actuators can miss a single short stop telegram.
            # Send the identical H5 stop command three times. The command is
            # idempotent and repeated transmission is also consistent with
            # normal EnOcean radio redundancy.
            stop = build_h5_3f_7f_cover(sender_id, "stop", duration_seconds=0)
            return [stop, stop, stop]

    raise UnsupportedEltakoCommand(
        f"command={command}, platform={platform}, device_eep={device_eep}, sender_eep={sender_eep}"
    )


def _candidate_addresses_for_device(device: dict[str, Any]) -> set[str]:
    """Return all physical/logical addresses that may identify a YAML device."""
    result: set[str] = set()
    device_id = str(device.get("id") or "").strip().upper()
    sender_id = str(device.get("sender_id") or "").strip().upper()
    if device_id:
        result.add(device_id)
    if sender_id:
        result.add(sender_id)

    gateway = device.get("gateway") if isinstance(device.get("gateway"), dict) else {}
    base_id = str(gateway.get("base_id") or "").strip().upper()
    if device_id.startswith("00-00-00-") and base_id:
        try:
            base = bytearray(parse_address(base_id))
            offset = parse_address(device_id)[3]
            base[3] = (base[3] + offset) & 0xFF
            result.add(format_address(base))
        except Exception:
            pass

    return {address for address in result if address}


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _probe_gateway_sync(port: str, configured_gateway_type: str) -> GatewayProbeResult:
    """Probe the selected gateway without importing external ELTAKO packages."""
    normalized = port.lower()

    if normalized.startswith("tcp://"):
        return GatewayProbeResult(
            detected_gateway_type=configured_gateway_type if configured_gateway_type != GATEWAY_TYPE_AUTO else GATEWAY_TYPE_AUTO,
            base_id=None,
            transport="tcp",
            ok=True,
            message="Network gateway path stored. Active TCP probing is not implemented yet.",
        )

    descriptor_type = _infer_gateway_from_path(normalized)
    mismatch = _port_descriptor_mismatches_gateway(port, configured_gateway_type)
    if mismatch:
        return GatewayProbeResult(
            detected_gateway_type=configured_gateway_type,
            base_id=None,
            transport="serial",
            ok=False,
            message=mismatch,
        )

    # Respect the gateway type explicitly selected by the user before descriptor
    # inference. A configured FGW14-USB must never be reclassified as FAM-USB
    # merely because HA pointed it at a stale EnOcean Programmer /dev/ttyUSBx.
    if configured_gateway_type == GATEWAY_TYPE_FAM_USB:
        return GatewayProbeResult(
            detected_gateway_type=GATEWAY_TYPE_FAM_USB,
            base_id=None,
            transport="esp2_9600",
            ok=True,
            message="FAM-USB / EnOcean USB-Gateway erkannt. Senden erfolgt per ESP2 mit 9600 Baud.",
        )

    if configured_gateway_type in (GATEWAY_TYPE_FAM14, GATEWAY_TYPE_FGW14USB):
        return GatewayProbeResult(
            detected_gateway_type=configured_gateway_type,
            base_id=None,
            transport="rs485_57600",
            ok=True,
            message="RS485-Busanschluss manuell gesetzt. Senden erfolgt per ESP2 mit 57600 Baud.",
        )

    if descriptor_type == GATEWAY_TYPE_FAM_USB:
        return GatewayProbeResult(
            detected_gateway_type=GATEWAY_TYPE_FAM_USB,
            base_id=None,
            transport="esp2_9600",
            ok=True,
            message="FAM-USB / EnOcean USB-Gateway erkannt. Senden erfolgt per ESP2 mit 9600 Baud.",
        )

    if descriptor_type in (GATEWAY_TYPE_FAM14, GATEWAY_TYPE_FGW14USB, GATEWAY_TYPE_AUTO):
        return GatewayProbeResult(
            detected_gateway_type=GATEWAY_TYPE_AUTO,
            base_id=None,
            transport="rs485_57600",
            ok=True,
            message="RS485-Busanschluss erkannt. Senden erfolgt ueber den internen ESP2-Bus-Core.",
        )

    return GatewayProbeResult(
        detected_gateway_type=configured_gateway_type,
        base_id=None,
        transport="serial",
        ok=True,
        message="Gateway anhand Pfad nicht eindeutig erkannt. Port wurde gespeichert und kann erneut geprueft werden.",
    )


def _infer_gateway_from_path(normalized_port: str) -> str:
    if "enocean_gmbh_enocean_programmer" in normalized_port or "enocean" in normalized_port:
        return GATEWAY_TYPE_FAM_USB

    if "ftdi_ft232r_usb_uart" in normalized_port or "ft232r" in normalized_port or "ftdi" in normalized_port:
        return GATEWAY_TYPE_AUTO

    return GATEWAY_TYPE_AUTO
