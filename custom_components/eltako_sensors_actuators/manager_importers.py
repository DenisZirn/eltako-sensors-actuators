from __future__ import annotations

import html
import json
import re
from typing import Any
from xml.etree import ElementTree as ET


FWG14MS_ID_RANGES = (
    {"value": "1", "base_id": "00-00-18-00", "end_id": "00-00-18-0C"},
    {"value": "2", "base_id": "00-00-18-10", "end_id": "00-00-18-1C"},
)


def _local_name(tag: str) -> str:
    return str(tag or "").split("}")[-1].lower()


def _children(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    wanted = name.lower()
    return [child for child in list(element) if _local_name(child.tag) == wanted]


def _child(element: ET.Element | None, name: str) -> ET.Element | None:
    items = _children(element, name)
    return items[0] if items else None


def _descendants(element: ET.Element | None, name: str) -> list[ET.Element]:
    if element is None:
        return []
    wanted = name.lower()
    return [node for node in element.iter() if _local_name(node.tag) == wanted]


def _text(element: ET.Element | None, path: str, default: str = "") -> str:
    current = element
    for part in (item.strip() for item in path.split(">")):
        current = _child(current, part)
        if current is None:
            return default
    value = (current.text or "").strip()
    return value if value else default


def _hex_id(value: int) -> str:
    number = int(value) & 0xFFFFFFFF
    return "-".join(f"{(number >> shift) & 0xFF:02X}" for shift in (24, 16, 8, 0))


def _little_endian_decimal_id(value: Any) -> str:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return ""
    raw = tuple((number >> shift) & 0xFF for shift in (0, 8, 16, 24))
    return "-".join(f"{item:02X}" for item in raw)


def _normal_id(value: Any) -> str:
    clean = re.sub(r"[-:\s]", "", str(value or "").strip().upper())
    if not re.fullmatch(r"[0-9A-F]{8}", clean):
        return ""
    if clean in {"00000000", "FFFFFFFF"}:
        return ""
    return "-".join(clean[index:index + 2] for index in range(0, 8, 2))


def _catalog_map(catalog: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("key")): item
        for item in catalog.get("devices", [])
        if isinstance(item, dict) and item.get("key")
    }


def pct14_mapping(model_name: str) -> dict[str, Any] | None:
    name = str(model_name or "").upper()
    if name.startswith("FGW14"):
        return {"gateway": "fgw14usb"}
    if name.startswith("FSB14"):
        return {"profile_key": "G5-3F-7F-FSB14", "platform": "cover", "time_opens": 25, "time_closes": 25}
    if name.startswith("FD2G14"):
        return {"profile_key": "A5-38-08-FD2G14", "platform": "light", "dali": True}
    if name.startswith("FDG14"):
        return {"profile_key": "A5-38-08-FDG14", "platform": "light", "dali": True}
    if name.startswith("FRGBW14"):
        return {"profile_key": "07-3F-7F-FRGBW14", "platform": "light", "sender_eep": "07-3F-7F", "channels": 1, "rgbw": True}
    if name.startswith("FRGBW71"):
        return {"profile_key": "07-3F-7F-FRGBW71L", "platform": "light", "sender_eep": "07-3F-7F", "channels": 1, "rgbw": True}
    if name.startswith("FUD14"):
        return {"profile_key": "A5-38-08-FUD14", "platform": "light"}
    if name.startswith("F4SR14"):
        return {"profile_key": "M5-38-08-F4SR14-LED", "platform": "light"}
    if name.startswith("FSR14SSR"):
        return {"profile_key": "M5-38-08-FSR14-2X", "platform": "light"}
    if name.startswith(("FSR14-4", "FSR14_4")):
        return {"profile_key": "M5-38-08-FSR14-4X", "platform": "light"}
    if name.startswith(("FSR14-2", "FSR14_2")):
        return {"profile_key": "M5-38-08-FSR14-2X", "platform": "light"}
    if name.startswith("FSR14"):
        return {"profile_key": "M5-38-08-FSR14-2X", "platform": "light"}
    if name.startswith("FMS14"):
        return {"profile_key": "M5-38-08-FMS14", "platform": "light", "sender_eep": "A5-38-08", "channels": 2}
    if name.startswith("F2L14"):
        return {"profile_key": "F6-02-01-F2L14", "platform": "fan", "sender_eep": "F6-02-01", "logical_fan": True, "address_span": 2}
    if name.startswith("FMZ14"):
        return {"profile_key": "M5-38-08-FMZ14", "platform": "light", "sender_eep": "F6-02-01"}
    if name.startswith("FAE14LPR"):
        return {"profile_key": "A5-10-06-FAE14LPR", "platform": "climate", "min_target_temperature": 16, "max_target_temperature": 25}
    if name.startswith("FTS14EM"):
        return {"profile_key": "F6-02-01-FTS14EM-UT", "platform": "binary_sensor", "fts14em": True}
    if name.startswith(("FHK14", "F4HK14", "FAE14SSR")):
        return {"profile_key": "A5-10-06", "platform": "climate", "min_target_temperature": 16, "max_target_temperature": 25}
    if name.startswith("FWG14MS"):
        return {"profile_key": "A5-13-01-FWG14MS", "platform": "sensor", "weather": True, "fwg14ms": True}
    if name.startswith("F3Z14D"):
        return {"profile_key": "A5-12-01-F3Z14D", "platform": "sensor", "channels": 3, "meter_tariffs": [1]}
    if name.startswith(("FWZ14", "DSZ14")):
        return {"profile_key": "A5-12-01", "platform": "sensor"}
    return None


def _pct14_model_name(model_name: str) -> str:
    upper = str(model_name or "").upper()
    if upper.startswith(("FSR14-4", "FSR14_4")):
        return "FSR14-4x"
    if upper.startswith(("FSR14-2", "FSR14_2")):
        return "FSR14-2x"
    if upper.startswith(("FSR14-1", "FSR14_1")):
        return "FSR14_1X"
    if upper.startswith("F4SR14"):
        return "F4SR14_LED"
    for known in ("FMS14", "F2L14", "FWG14MS", "F3Z14D"):
        if upper.startswith(known):
            return known
    return str(model_name or "Gerät").strip() or "Gerät"


def parse_pct14_xml(text: str, catalog: dict[str, Any]) -> dict[str, Any]:
    try:
        root = ET.fromstring(str(text or ""))
    except ET.ParseError as err:
        raise ValueError("Die Datei ist keine gültige PCT14-XML-Datei.") from err

    profiles = _catalog_map(catalog)
    root_device = next((item for item in root.iter() if _local_name(item.tag) == "rootdevice"), None)
    base_node = _descendants(root_device, "baseid")
    base_id = ""
    if base_node:
        parts = [
            _text(base_node[0], f"baseid_byte_{index}", "0")
            for index in range(4)
        ]
        try:
            base_id = "-".join(f"{int(part):02X}" for part in parts)
        except ValueError:
            base_id = ""

    devices_container = next((item for item in root.iter() if _local_name(item.tag) == "devices"), None)
    device_nodes = _children(devices_container, "device")
    rows: list[dict[str, Any]] = []
    unsupported: list[str] = []
    extra_gateways: list[dict[str, Any]] = []
    fwg_index = 0

    for node in device_nodes:
        model = _text(node, "name")
        address = int(_text(node, "header > address", "0") or 0)
        mapping = pct14_mapping(model)
        if mapping is None:
            unsupported.append(model or f"Adresse {address}")
            continue
        if mapping.get("gateway"):
            extra_gateways.append({"type": mapping["gateway"], "base_id": base_id, "source": "pct14"})
            continue

        profile_key = str(mapping["profile_key"])
        profile = profiles.get(profile_key)
        if profile is None:
            unsupported.append(f"{model}: Profil {profile_key} fehlt im Katalog")
            continue

        address_range = max(1, int(_text(node, "header > addressrange", "1") or 1))
        channels_parent = _child(node, "channels")
        groups_parent = _child(node, "groups")
        channels = _children(channels_parent, "channel")
        groups = _children(groups_parent, "group")
        channel_count = int(mapping.get("channels") or max(address_range, len(channels), len(groups), 1))

        if mapping.get("fwg14ms"):
            if fwg_index >= len(FWG14MS_ID_RANGES):
                unsupported.append(f"{model}: nur ID-Bereich Position 1 und 2 werden unterstützt")
                continue
            selected_range = FWG14MS_ID_RANGES[fwg_index]
            bus_id = _hex_id(address)
            rows.append({
                "selected": True,
                "source": "PCT14",
                "bus_system_id": f"pct14:{base_id}" if base_id else "",
                "bus_base_id": base_id,
                "profile_key": profile_key,
                "id": selected_range["base_id"],
                "name": f"FWG14MS {bus_id}",
                "area": "",
                "area_hint": f"PCT14 Adresse {address} · ID-Bereich Position {selected_range['value']}",
                "bus_address": bus_id,
                "fwg14ms_id_range": selected_range["value"],
                "sender_id": "",
                "sender_eep": "",
                "device_class": profile.get("default_dc") or "",
                "warning": "",
            })
            fwg_index += 1
            continue

        if mapping.get("fts14em"):
            raw_text = " ".join((part or "") for part in node.itertext()).upper()
            mode = "RT" if re.search(r"(^|[^A-Z])RT([^A-Z]|$)", raw_text) else "UT"
            rows.append({
                "selected": False,
                "source": "PCT14",
                "bus_system_id": f"pct14:{base_id}" if base_id else "",
                "bus_base_id": base_id,
                "profile_key": profile_key,
                "id": "",
                "name": f"FTS14EM {mode}",
                "area": "",
                "area_hint": f"PCT14 Adresse {address} · Basis-ID · {mode}",
                "operating_mode": mode,
                "sender_id": "",
                "sender_eep": "",
                "device_class": "",
                "warning": "E1-Basis-ID im Lernmodus ermitteln und hier eintragen",
            })
            continue

        if mapping.get("logical_fan"):
            description = ""
            for channel in channels:
                description = str(channel.attrib.get("description") or "").strip()
                if description:
                    break
            stage_1 = _hex_id(address)
            stage_2 = _hex_id(address + 1)
            fan_mode = "exclusive"
            range_parent = _child(node, "rangeofid")
            for learned in _children(range_parent, "entry"):
                if (
                    int(_text(learned, "entry_function", "-1") or -1) == 56
                    and int(_text(learned, "entry_button", "-1") or -1) == 7
                    and int(_text(learned, "entry_channel", "-1") or -1) == 3
                ):
                    fan_mode = "additive" if int(_text(learned, "entry_value", "0") or 0) == 1 else "exclusive"
                    break
            rows.append({
                "selected": True,
                "source": "PCT14",
                "bus_system_id": f"pct14:{base_id}" if base_id else "",
                "bus_base_id": base_id,
                "profile_key": profile_key,
                "id": stage_1,
                "name": description or f"F2L14 {stage_1}",
                "area": "",
                "area_hint": f"PCT14 Adresse {address} · 2 Stufen",
                "bus_address": stage_1,
                "stage_1_id": stage_1,
                "stage_2_id": stage_2,
                "f2l14_mode": fan_mode,
                "sender_id": _hex_id(0xB000 + address),
                "sender_eep": mapping.get("sender_eep") or profile.get("sender_eep") or "",
                "device_class": "",
                "warning": "",
            })
            continue

        sender_by_channel: dict[int, str] = {}
        range_parent = _child(node, "rangeofid")
        for learned in _children(range_parent, "entry"):
            sender = _little_endian_decimal_id(_text(learned, "entry_id"))
            channel_number = int(_text(learned, "entry_channel", "0") or 0)
            if mapping.get("dali"):
                raw_group = _text(learned, "entry_group", "")
                if raw_group:
                    channel_number = int(raw_group) + 1
            if re.fullmatch(r"00-00-B0-[0-9A-F]{2}", sender) and channel_number > 0:
                sender_by_channel.setdefault(channel_number, sender)

        for index in range(channel_count):
            channel_number = index + 1
            channel = next(
                (item for item in channels if int(item.attrib.get("channelnumber") or 0) == channel_number),
                None,
            )
            group = next(
                (item for item in groups if int(item.attrib.get("groupnumber") or -1) == index),
                None,
            )
            description = str(
                (channel.attrib.get("description") if channel is not None else "")
                or (group.attrib.get("description") if group is not None else "")
                or ""
            ).strip()
            device_id = _hex_id(address + index)
            needs_sender = bool(profile.get("needs_sender"))
            fallback_sender = _hex_id(0xB000 + address + index) if needs_sender else ""
            sender_id = fallback_sender or sender_by_channel.get(channel_number, "")
            model_name = _pct14_model_name(model)
            suffix = f" ({channel_number}/{channel_count})" if channel_count > 1 else ""
            hint = f"PCT14 Adresse {address}"
            if channel_count > 1:
                hint += f" · Kanal {channel_number}"
            if mapping.get("dali"):
                hint += " · DALI-Gateway"
            if mapping.get("rgbw"):
                hint += " · RGBW-Profil"
            rows.append({
                "selected": True,
                "source": "PCT14",
                "bus_system_id": f"pct14:{base_id}" if base_id else "",
                "bus_base_id": base_id,
                "profile_key": profile_key,
                "id": device_id,
                "bus_address": device_id,
                "name": description or f"{model_name} {device_id}{suffix}",
                "area": "",
                "area_hint": hint,
                "sender_id": sender_id,
                "sender_eep": mapping.get("sender_eep") or profile.get("sender_eep") or "",
                "device_class": "shutter" if mapping.get("platform") == "cover" else (profile.get("default_dc") or ""),
                "time_opens": mapping.get("time_opens"),
                "time_closes": mapping.get("time_closes"),
                "min_target_temperature": mapping.get("min_target_temperature"),
                "max_target_temperature": mapping.get("max_target_temperature"),
                "meter_tariffs": mapping.get("meter_tariffs") or [],
                "warning": "" if (not needs_sender or sender_id) else "Sender-ID fehlt",
            })

    return {
        "format": "pct14",
        "base_id": base_id,
        "rows": rows,
        "unsupported": unsupported,
        "extra_gateways": extra_gateways,
        "summary": {
            "devices": len(rows),
            "unsupported": len(unsupported),
            "base_id": base_id,
        },
    }


def _extract_json_array(source: str, key: str = "") -> str | None:
    start_at = 0
    if key:
        match = re.search(rf'"{re.escape(key)}"\s*:', source, re.IGNORECASE)
        if not match:
            return None
        start_at = match.end()
    start = source.find("[", start_at)
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        character = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return source[start:index + 1]
    return None


def _decode_minisafe_text(value: str) -> str:
    source = html.unescape(str(value or ""))
    return re.sub(r'\\(?!["\\/bfnrtu])', "", source)


def _minisafe_sid(value: Any) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"^0+(?=.)", "", text)


def _minisafe_sender_states(source: str) -> list[dict[str, Any]]:
    array_text = _extract_json_array(source, "getStates")
    if not array_text:
        marker = re.search(r"^[^\r\n]*:[ \t]*/?getStates[ \t]*:?[ \t]*$", source, re.IGNORECASE | re.MULTILINE)
        if marker:
            tail = source[marker.end():].lstrip()
            if tail.startswith("["):
                array_text = _extract_json_array(tail)
    if not array_text:
        return []
    try:
        parsed = json.loads(array_text)
    except json.JSONDecodeError:
        return []
    return [
        state
        for state in parsed
        if isinstance(state, dict)
        and str(state.get("type") or "").upper() == "ENOCEAN"
        and state.get("virtual") is not True
    ]


def _minisafe_sender(device: dict[str, Any], states: list[dict[str, Any]]) -> tuple[str, str]:
    info = device.get("info") if isinstance(device.get("info"), dict) else {}
    sid = _minisafe_sid(info.get("sid"))
    address = _normal_id(info.get("address"))
    matches = [
        state for state in states
        if sid
        and _minisafe_sid(state.get("sid")) == sid
        and (not state.get("adr") or _normal_id(state.get("adr")) == address)
        and (
            state.get("gateway") is None
            or info.get("gateway") is None
            or str(state.get("gateway")) == str(info.get("gateway"))
        )
    ]
    raw_ids = [info.get("senderID"), *(state.get("senderID") for state in matches)]
    ids = sorted({_normal_id(value) for value in raw_ids if _normal_id(value)})
    if len(ids) > 1:
        return "", "Mehrere unterschiedliche Sender-IDs gefunden"
    if len(ids) == 1:
        return ids[0], ""
    if any(value not in (None, "") for value in raw_ids):
        return "", "Ungültige Sender-ID"
    return "", ""


def _profile_search_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def _minisafe_profile(device: dict[str, Any], catalog: dict[str, Any]) -> str:
    profiles = _catalog_map(catalog)
    info = device.get("info") if isinstance(device.get("info"), dict) else {}
    device_text = str(info.get("deviceText") or "").strip()
    descriptor = f"{device_text} {info.get('data') or ''}".upper()

    fixed = (
        (r"FTR(?:55|65)(?:DSB|HS)", "A5-10-06-FTR-FHK"),
        (r"ELTAKO_BUTTON4|FUNKTASTER.*4\s*TASTEN", "F6-02-01-4CH"),
        (r"FUD61NPN-230V", "A5-38-08-FUD61NPN-230V"),
        (r"FSR61-230V", "M5-38-08-FSR61-230V"),
    )
    for pattern, key in fixed:
        if re.search(pattern, descriptor) and key in profiles:
            return key

    normalized = _profile_search_text(device_text)
    if not normalized:
        return ""
    matches: list[str] = []
    for key, profile in profiles.items():
        names = str(profile.get("eltako") or "").split(",")
        if any(
            search and search in normalized
            for search in (_profile_search_text(name) for name in names)
        ):
            matches.append(key)
    return matches[0] if len(matches) == 1 else ""


def parse_minisafe2(text: str, catalog: dict[str, Any]) -> dict[str, Any]:
    decoded = _decode_minisafe_text(text).strip()
    if not decoded:
        raise ValueError("MiniSafe2-Konfiguration ist leer.")

    json_start = decoded.find("{")
    candidate = decoded[json_start:] if json_start >= 0 else decoded
    rooms: list[Any]
    devices: list[Any]
    try:
        parsed = json.loads(candidate)
        system = parsed.get("system", parsed) if isinstance(parsed, dict) else {}
        rooms = system.get("rooms", []) if isinstance(system, dict) else []
        devices = system.get("devices", []) if isinstance(system, dict) else []
        if not isinstance(devices, list):
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        rooms_text = _extract_json_array(candidate, "rooms") or "[]"
        devices_text = _extract_json_array(candidate, "devices")
        if not devices_text:
            raise ValueError("MiniSafe2-Konfiguration enthält keine lesbare Geräteliste.")
        try:
            rooms = json.loads(rooms_text)
            devices = json.loads(devices_text)
        except json.JSONDecodeError as err:
            raise ValueError("MiniSafe2-Konfiguration ist ungültig.") from err

    room_map = {
        int(room.get("index")): str(room.get("name") or "").strip()
        for room in rooms
        if isinstance(room, dict) and str(room.get("index") or "").lstrip("-").isdigit()
    }
    states = _minisafe_sender_states(decoded)
    rows: list[dict[str, Any]] = []
    unsupported: list[str] = []

    for source_index, device in enumerate(devices):
        if not isinstance(device, dict):
            continue
        info = device.get("info") if isinstance(device.get("info"), dict) else {}
        if (
            str(info.get("type") or "").upper() != "ENOCEAN"
            or str(info.get("vendor") or "").lower() != "eltako"
            or info.get("virtual") is True
        ):
            continue
        device_id = _normal_id(info.get("address"))
        if not device_id:
            continue
        profile_key = _minisafe_profile(device, catalog)
        sender_id, sender_warning = _minisafe_sender(device, states)
        name = str(device.get("name") or info.get("deviceText") or f"MiniSafe2 {source_index + 1}").strip()
        room = room_map.get(int(device.get("room") or 0), "")
        warning_parts = []
        if not profile_key:
            warning_parts.append("Geräteprofil manuell auswählen")
            unsupported.append(str(info.get("deviceText") or name))
        if sender_warning:
            warning_parts.append(sender_warning)
        rows.append({
            "selected": bool(profile_key),
            "source": "MiniSafe2",
            "source_index": source_index,
            "profile_key": profile_key,
            "id": device_id,
            "name": name,
            "area": room,
            "area_hint": "",
            "sender_id": sender_id,
            "sender_id_source": "minisafe2" if sender_id else "",
            "sender_eep": "",
            "device_class": "",
            "device_text": str(info.get("deviceText") or info.get("data") or "").strip(),
            "target": str(info.get("_target") or "").strip(),
            "sid": _minisafe_sid(info.get("sid")),
            "warning": " · ".join(warning_parts),
        })

    return {
        "format": "minisafe2",
        "rows": rows,
        "unsupported": unsupported,
        "summary": {
            "devices": len(rows),
            "recognized": sum(1 for row in rows if row.get("profile_key")),
            "rooms": len(room_map),
        },
    }


def detect_import_format(text: str, filename: str = "") -> str:
    source = str(text or "").lstrip()
    lower_name = str(filename or "").lower()
    if lower_name.endswith(".xml") or source.startswith("<?xml") or re.search(r"<(?:\w+:)?exchange\b", source, re.IGNORECASE):
        return "pct14"
    if "getStates" in source or re.search(r'"vendor"\s*:\s*"eltako"', source, re.IGNORECASE):
        return "minisafe2"
    if re.search(r"(^|\n)\s*eltako\s*:", source):
        return "eedtoy_yaml"
    if source.startswith("{") and ('"devices"' in source or '"system"' in source):
        return "minisafe2"
    return "eedtoy_yaml"
