"""
Write Home Assistant sender IDs into ELTAKO Series-14 bus actuators.

This mirrors the relevant write path of Philipp Grimm's EnOcean Device Manager:
connect to the FAM14/FGW14 bus, lock it, address only the devices referenced by
the PCT14 sender map and program the requested controller sender IDs.
"""
import asyncio
from typing import Any, Dict, List, Optional, Set


def log(*parts: Any) -> None:
    """Lightweight hook retained from EEDTOY; HA callers consume structured events."""
    return None


def norm_id(value: str) -> str:
    raw = str(value or "").strip().upper().replace(":", "-").replace(" ", "-")
    parts = [p for p in raw.split("-") if p]
    if len(parts) == 4 and all(len(p) <= 2 for p in parts):
        return "-".join(p.zfill(2) for p in parts)
    clean = raw.replace("-", "")
    if len(clean) == 8:
        return "-".join(clean[i:i+2] for i in range(0, 8, 2))
    return raw


def _id_to_int(value: str) -> Optional[int]:
    clean = norm_id(value).replace("-", "")
    if len(clean) != 8:
        return None
    try:
        return int(clean, 16)
    except ValueError:
        return None


def build_sender_map(entries: list[dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    result: Dict[str, List[Dict[str, Any]]] = {}
    seen: Set[tuple[str, str, str]] = set()
    for item in entries:
        device_id = norm_id(item.get("device_id") or item.get("id") or "")
        sender_id = norm_id(item.get("sender_id") or "")
        sender_eep = str(item.get("sender_eep") or item.get("eep") or "").strip().upper()
        name = str(item.get("name") or "")
        if not device_id or not sender_id or not sender_eep:
            continue
        key = (device_id, sender_id, sender_eep)
        if key in seen:
            continue
        seen.add(key)
        result.setdefault(device_id, []).append({
            "sender": {"id": sender_id, "eep": sender_eep},
            "name": name,
            "device_eep": str(item.get("device_eep") or item.get("device_eep_out") or "").strip().upper(),
            "device_type": str(item.get("device_type") or "").strip(),
            "platform": str(item.get("platform") or "").strip(),
            "expected_bus_base_id": norm_id(item.get("expected_bus_base_id") or ""),
            "source_gateway_type": str(item.get("source_gateway_type") or "").strip(),
            "source_gateway_base_id": norm_id(item.get("source_gateway_base_id") or ""),
            "f2l14_mode": str(item.get("f2l14_mode") or "exclusive").strip().lower(),
        })
    return result


def target_bus_addresses(fam14_base_id_int: int, sender_map: Dict[str, Any]) -> List[int]:
    """Return only the Series-14 addresses referenced by the sender map.

    PCT14 entries use the FAM14 base ID plus the physical bus address/channel
    offset. Multi-channel devices are contiguous; after discovering their first
    address, enumerate_target_devices skips the remaining covered addresses.
    """
    result: Set[int] = set()
    for device_id in sender_map:
        value = _id_to_int(device_id)
        if value is None:
            continue
        offset = value - fam14_base_id_int
        if 1 <= offset <= 254:
            result.add(offset)
        else:
            log("ignore sender-map device outside FAM14 range", device_id, "offset", offset)
    return sorted(result)


async def enumerate_target_devices(bus: Any, target_addresses: List[int]):
    """Discover only devices needed for the requested sender IDs."""
    from eltakobus.device import create_busobject

    pending: Set[int] = set(target_addresses)
    while pending:
        address = min(pending)
        pending.discard(address)
        try:
            bus_object = await create_busobject(bus=bus, id=address)
            if bus_object is None:
                log("No device response at target address", address)
                continue
            start = int(getattr(bus_object, "address", address) or address)
            size = max(1, int(getattr(bus_object, "size", 1) or 1))
            for covered in range(start, min(255, start + size)):
                pending.discard(covered)
            log("target device", type(bus_object).__name__, "address", start, "size", size)
            yield bus_object
        except TimeoutError:
            log("Timeout detecting target device at address", address)
        except Exception as e:
            log("Cannot detect target device at address", address, repr(e))


def _sender_bytes_from_id(sender_id: str) -> bytes:
    clean = norm_id(sender_id).replace("-", "")
    if len(clean) != 8:
        raise ValueError(f"ungültige Sender-ID: {sender_id}")
    return bytes(int(clean[i:i+2], 16) for i in range(0, 8, 2))


def _clean_label(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() in {"none", "null", "undefined"}:
        return ""
    return text


def _entry_device_type(entry: Dict[str, Any]) -> str:
    candidates = [entry.get("device_type"), entry.get("model"), entry.get("eltako")]
    name = _clean_label(entry.get("name"))
    if name:
        candidates.append(name.split()[0])
    for candidate in candidates:
        label = _clean_label(candidate)
        if label and label != "BusObject":
            return label
    return "Gerät"


def _device_display_name(entry: Dict[str, Any], fallback_type: str, device_ext_id: str) -> str:
    device_type = _entry_device_type(entry)
    name = _clean_label(entry.get("name"))
    if name and name != device_type and name != device_ext_id:
        return f"{name} ({device_type} {device_ext_id})"
    if device_type and device_type != "Gerät":
        return f"{device_type} {device_ext_id}"
    fallback = _clean_label(fallback_type)
    if fallback and fallback != "BusObject":
        return f"{fallback} {device_ext_id}"
    return f"Unbekanntes Gerät {device_ext_id}"


async def _find_or_write_free_line(dev: Any, expected_line: bytes, start_line: int) -> Optional[bool]:
    memory_size = int(getattr(dev, "memory_size", 0) or 0)
    if memory_size <= start_line or not hasattr(dev, "read_mem_line") or not hasattr(dev, "write_mem_line"):
        return None

    first_empty = None
    for memory_id in range(start_line, memory_size):
        line = await dev.read_mem_line(memory_id)
        if line == expected_line:
            return False
        if not any(line) and first_empty is None:
            first_empty = memory_id

    if first_empty is None:
        raise RuntimeError("Kein freier Speicherplatz zum Einlernen des Controller-Senders gefunden")
    await _write_mem_line_with_readback(dev, first_empty, expected_line)
    return True


async def _read_back_mem_line(dev: Any, row: int) -> Optional[bytes]:
    """Force one row to be read from the actuator instead of its local cache."""
    memory = getattr(dev, "memory", None)
    previous = None
    can_invalidate = isinstance(memory, list) and 0 <= row < len(memory)
    if can_invalidate:
        previous = memory[row]
        memory[row] = None
    try:
        actual = await dev.read_mem_line(row)
    except Exception:
        if can_invalidate and memory[row] is None:
            memory[row] = previous
        return None
    if actual is None and can_invalidate:
        memory[row] = previous
        return None
    return actual


async def _write_mem_line_with_readback(dev: Any, row: int, value: bytes) -> None:
    """Accept a write whose acknowledgement was lost when read-back confirms it."""
    try:
        await dev.write_mem_line(row, value)
    except Exception:
        await asyncio.sleep(0.08)
        if await _read_back_mem_line(dev, row) == value:
            return
        raise


async def _ensure_programmed_controller_profile(dev: Any, sender_id: str, channel: int = 0) -> Optional[bool]:
    """Program the FRGBW controller profile in a free controller slot."""
    sender = _sender_bytes_from_id(sender_id)
    subchannel = max(1, int(channel or 0) + 1)
    expected_line = sender + bytes((0, 32, subchannel, 0))
    return await _find_or_write_free_line(dev, expected_line, 12)


async def _ensure_programmed_fsr14ssr(dev: Any, sender_id: str, channel: int = 0) -> Optional[bool]:
    """Use the standard FSR14 function-group-2 layout for FSR14SSR."""
    sender = _sender_bytes_from_id(sender_id)
    if channel < 0 or channel > 7:
        raise ValueError(f"Ungültiger FSR14SSR-Kanal: {channel + 1}")
    expected_line = sender + bytes((0, 51, 1 << channel, 0))
    return await _find_or_write_free_line(dev, expected_line, 12)


async def _ensure_programmed_fms14(dev: Any, sender_id: str, channel: int = 0) -> Optional[bool]:
    """Program one FMS14 channel as PCT14 ``State from Controller``.

    FMS14 is not represented by a dedicated eltakobus device class. Its
    programmable table starts at memory line 8. PCT14 key function 51
    (0x33) is ``State from Controller``; key 0 selects the controller
    telegram instead of a physical RPS rocker. Earlier v1.0.97 builds wrote
    key 6/function 3, so replace that exact legacy row in place when found.
    """
    sender = _sender_bytes_from_id(sender_id)
    if channel < 0 or channel > 1:
        raise ValueError(f"Ungültiger FMS14-Kanal: {channel + 1}")
    channel_mask = 1 << channel
    expected_line = sender + bytes((0, 51, channel_mask, 0))
    legacy_line = sender + bytes((6, 3, channel_mask, 0))
    memory_size = int(getattr(dev, "memory_size", 0) or 0)
    if memory_size <= 8 or not hasattr(dev, "read_mem_line") or not hasattr(dev, "write_mem_line"):
        return None

    first_empty = None
    legacy_memory_id = None
    for memory_id in range(8, memory_size):
        line = await dev.read_mem_line(memory_id)
        if line == expected_line:
            return False
        if line == legacy_line and legacy_memory_id is None:
            legacy_memory_id = memory_id
        if not any(line) and first_empty is None:
            first_empty = memory_id

    target_memory_id = legacy_memory_id if legacy_memory_id is not None else first_empty
    if target_memory_id is None:
        raise RuntimeError("Kein freier Speicherplatz zum Einlernen des FMS14-Controller-Senders gefunden")
    await _write_mem_line_with_readback(dev, target_memory_id, expected_line)
    return True


async def _ensure_programmed_f2l14(dev: Any, sender_id: str, mode: str = "exclusive") -> Optional[bool]:
    """Program the F2L14 virtual double rocker for the selected stage mode.

    A real PCT14 export from F2L14 manual v4 / software 65 confirms the
    eight-byte entry layout: sender + button 7 + function 56 + channel mask 3
    PCT14 references confirm value 0 for rotary position 1 (exclusive) and
    value 1 for position 2 (additive). Entry 1 maps to memory row 8.
    """
    sender = _sender_bytes_from_id(sender_id)
    normalized_mode = str(mode or "exclusive").strip().lower()
    if normalized_mode not in {"exclusive", "additive"}:
        raise ValueError(f"Ungültige F2L14-Betriebsart: {mode}")
    assignment = sender + bytes((7, 56, 3))
    expected_line = assignment + bytes((1 if normalized_mode == "additive" else 0,))
    memory_size = int(getattr(dev, "memory_size", 0) or 0)
    if memory_size <= 8 or not hasattr(dev, "read_mem_line") or not hasattr(dev, "write_mem_line"):
        return None

    first_empty = None
    matching_rows = []
    exact_rows = []
    for memory_id in range(8, memory_size):
        line = await dev.read_mem_line(memory_id)
        if line == expected_line:
            exact_rows.append(memory_id)
        if line[:7] == assignment:
            matching_rows.append(memory_id)
        if not any(line) and first_empty is None:
            first_empty = memory_id

    # One HA sender must occupy exactly one F2L14 entry.  A mode change only
    # changes the final PCT14 value byte, so replace the existing row in place
    # instead of consuming a second row.  Also repair duplicates written by
    # earlier test builds while leaving entries from physical pushbuttons alone.
    if matching_rows:
        target_row = exact_rows[0] if exact_rows else matching_rows[0]
        changed = False
        if not exact_rows:
            await _write_mem_line_with_readback(dev, target_row, expected_line)
            changed = True
        for duplicate_row in matching_rows:
            if duplicate_row == target_row:
                continue
            await _write_mem_line_with_readback(dev, duplicate_row, bytes(8))
            changed = True
        return changed

    if first_empty is None:
        raise RuntimeError("Kein freier Speicherplatz zum Einlernen des F2L14-Controller-Senders gefunden")
    await _write_mem_line_with_readback(dev, first_empty, expected_line)
    return True


async def _ensure_programmed_fhk_controller(
    dev: Any,
    sender_id: str,
    channel: int,
    device_type: str,
) -> Optional[bool]:
    """Program the single Function Group 3 controller sender for FHK devices."""
    sender = _sender_bytes_from_id(sender_id)
    upper_type = str(device_type or "").upper()
    is_single_channel_fhk14 = "FHK14" in upper_type and "F4HK14" not in upper_type
    start_line = 10 if is_single_channel_fhk14 else (16 if "F4HK14" in upper_type else 12)
    preferred_line = start_line + int(channel or 0)
    memory_size = int(getattr(dev, "memory_size", 0) or 0)
    if preferred_line >= memory_size or not hasattr(dev, "read_mem_line") or not hasattr(dev, "write_mem_line"):
        return None

    expected_line = sender + bytes((0, 65, 1 << int(channel or 0), 0))

    preferred_current = await dev.read_mem_line(preferred_line)
    changed = preferred_current != expected_line
    if changed:
        # Function Group 3 has exactly one controller slot. A changed gateway ID
        # therefore replaces that slot and must never spill into Function Group 4.
        if is_single_channel_fhk14:
            await _write_fhk_mem_line(dev, preferred_line, expected_line)
        else:
            await _write_mem_line_with_readback(dev, preferred_line, expected_line)
    if is_single_channel_fhk14:
        # Older v1.0.97 builds wrote Function 65 into Group 4 (entries 5/6).
        # Remove only those invalid controller rows; preserve all other entries.
        for legacy_line in (12, 13):
            if legacy_line >= memory_size:
                continue
            legacy_value = await dev.read_mem_line(legacy_line)
            if legacy_value[4:] == bytes((0, 65, 1, 0)):
                await _write_fhk_mem_line(dev, legacy_line, bytes(8))
                changed = True
    return changed


async def _write_fhk_mem_line(dev: Any, row: int, value: bytes) -> None:
    """Write an FHK14 row without mistaking a delayed F2 reply for the F4 ACK."""
    bus = getattr(dev, "bus", None)
    if bus is None or not hasattr(bus, "exchange"):
        await dev.write_mem_line(row, value)
        return

    from eltakobus.error import WriteError
    from eltakobus.message import EltakoMessage

    select_response = await bus.exchange(EltakoMessage(0xF2, dev.address))
    if select_response is None or getattr(select_response, "org", None) != 0xF2:
        raise WriteError(f"Device selection failed; expected 0xf2, got {select_response!r}")

    # Some FHK14 units send the F2 selection reply twice. Let the second reply
    # leave the exchange hook before sending F4. If it still races with F4,
    # repeat only the idempotent row write without selecting the device again.
    await asyncio.sleep(0.08)
    write_response = None
    for attempt in range(3):
        write_response = await bus.exchange(EltakoMessage(0xF4, row, value))
        if write_response is not None and getattr(write_response, "org", None) == 0xF4:
            dev.memory[row] = value
            return
        if write_response is not None and getattr(write_response, "org", None) == 0xF2:
            await asyncio.sleep(0.08)
            if await _read_back_mem_line(dev, row) == value:
                return
            continue
        raise WriteError(f"Write failed; expected 0xf4, got {write_response!r}")

    raise WriteError(f"Write failed; expected 0xf4, got {write_response!r}")




def _is_fd2g14_entry(entry: Dict[str, Any]) -> bool:
    label = f"{_entry_device_type(entry)} {_clean_label(entry.get('name'))}".upper()
    return "FD2G14" in label


def _fd2g14_targets(fam14_base_id_int: int, sender_map: Dict[str, List[Dict[str, Any]]]) -> Dict[int, Dict[int, Dict[str, Any]]]:
    """Group the 16 logical FD2G14 YAML channels by their PCT14 base address."""
    items = []
    for device_id, entries in sender_map.items():
        value = _id_to_int(device_id)
        if value is None:
            continue
        offset = value - fam14_base_id_int
        if not (1 <= offset <= 254):
            continue
        for entry in entries:
            if _is_fd2g14_entry(entry):
                items.append((offset, device_id, entry))
    if not items:
        return {}

    by_offset = {offset: (device_id, entry) for offset, device_id, entry in items}
    remaining = set(by_offset)
    result: Dict[int, Dict[int, Dict[str, Any]]] = {}
    while remaining:
        base = min(remaining)
        channels: Dict[int, Dict[str, Any]] = {}
        for channel in range(16):
            offset = base + channel
            item = by_offset.get(offset)
            if item is None:
                continue
            device_id, entry = item
            channels[channel] = {"device_id": device_id, "entry": entry}
            remaining.discard(offset)
        result[base] = channels
    return result


async def enumerate_bus_grimm(bus: Any):
    """Enumerate Series-14 devices exactly like Grimm's eltakotool.

    A multi-channel device is discovered once at its physical base address and
    its complete address range is skipped afterwards. This is important for the
    FD2G14/FDG14 family, which reports size=16 and can have an additional
    compatibility response inside that range.
    """
    from eltakobus.device import create_busobject

    skip_until = 0
    for address in range(1, 255):
        if address <= skip_until:
            continue
        try:
            dev = await create_busobject(bus=bus, id=address)
            if dev is None:
                continue
            size = max(1, int(getattr(dev, "size", 1) or 1))
            skip_until = address + size - 1
            yield dev
        except TimeoutError:
            continue
        except Exception as exc:
            log("Grimm bus scan failed", address, repr(exc))


def _is_real_fd2g14(dev: Any) -> bool:
    """Return True only for a real FD2G14 discovery object."""
    if type(dev).__name__.upper() == "FD2G14":
        return True
    response = getattr(dev, "discovery_response", None)
    model = bytes(getattr(response, "model", b"") or b"")
    size = int(getattr(dev, "size", 0) or 0)
    return model[:2] == bytes((0x04, 0x82)) and size == 16


def _prepare_fd2g14_memory_access(dev: Any) -> None:
    """Guard only FD2G14 memory replies; retain its library programming layout."""
    if not _is_real_fd2g14(dev) or getattr(dev, "_eedtoy_memory_guard", False):
        return
    from eltakobus.message import EltakoMemoryRequest, EltakoMemoryResponse
    original_write = dev.write_mem_line

    async def read_row(row):
        cached = dev.memory[row]
        if cached is not None:
            return cached
        for attempt in range(3):
            try:
                response = await dev.bus.exchange(
                    EltakoMemoryRequest(dev.address, row), EltakoMemoryResponse,
                    retries=1, timeout=1.0)
                if (isinstance(response, EltakoMemoryResponse)
                        and response.row == row
                        and isinstance(response.value, (bytes, bytearray))
                        and len(response.value) == 8):
                    dev.memory[row] = bytes(response.value)
                    return dev.memory[row]
            except TimeoutError:
                pass
            if attempt < 2:
                await asyncio.sleep(0.1)
        raise TimeoutError(f"FD2G14 Basisadresse {dev.address}: keine gültige Speicherantwort für Zeile {row} nach 3 Versuchen; Schreiben abgebrochen.")

    async def write_row(row, value):
        try:
            await original_write(row, value)
        except Exception:
            # A lost ACK may follow a successful write. Confirm the real memory
            # before reporting failure; never accept the library's cache alone.
            dev.memory[row] = None
            if await read_row(row) == value:
                return
            raise

    dev.read_mem_line = read_row
    dev.write_mem_line = write_row
    dev._eedtoy_memory_guard = True


async def ensure_fd2g14_from_yaml(
    bus: Any,
    fam14_base_id_int: int,
    sender_map: Dict[str, List[Dict[str, Any]]],
    processed_ids: Set[str],
) -> List[Dict[str, Any]]:
    """Program FD2G14 through Grimm's real FD2G14/FDG14 BusObject path.

    The sixteen YAML IDs describe the logical DALI groups. They are *not* used
    as raw memory-access addresses. We discover the physical FD2G14 on the bus,
    then call its DimmerStyle.ensure_programmed() for channels 0..15. Grimm's
    implementation writes A5-38-08 as sender + 00 + function 32 + group + 00.
    """
    from eltakobus.eep import EEP
    try:
        from eltakobus import AddressExpression
    except Exception:
        from eltakobus.util import AddressExpression

    events: List[Dict[str, Any]] = []
    targets = _fd2g14_targets(fam14_base_id_int, sender_map)
    if not targets:
        return events

    pending_bases = {base for base, channels in targets.items()
                     if any(item["device_id"] not in processed_ids for item in channels.values())}
    if not pending_bases:
        return events

    from eltakobus.device import create_busobject
    discovered: List[Any] = []
    for address in sorted(pending_bases):
        for attempt in range(3):
            try:
                dev = await create_busobject(bus=bus, id=address)
                if dev is not None and int(getattr(dev, "address", -1)) == address and _is_real_fd2g14(dev):
                    discovered.append(dev)
                    break
            except Exception as exc:
                log("FD2G14 discovery retry", address, attempt + 1, repr(exc))
            if attempt < 2:
                await asyncio.sleep(0.15)

    missing_bases = pending_bases - {int(d.address) for d in discovered}
    if missing_bases:
        async for dev in enumerate_bus_grimm(bus):
            if _is_real_fd2g14(dev) and int(getattr(dev, "address", -1)) in missing_bases:
                discovered.append(dev)
                missing_bases.discard(int(dev.address))
                if not missing_bases:
                    break

    used_devices: Set[int] = set()
    for yaml_base, channels in sorted(targets.items()):
        pending = {ch: item for ch, item in channels.items() if item["device_id"] not in processed_ids}
        if not pending:
            continue

        # Both the physical PCT14 address and FD2G14 identity must match.
        dev = next((d for d in discovered if int(getattr(d, "address", -1)) == yaml_base and id(d) not in used_devices), None)
        if dev is None:
            for channel in sorted(pending):
                item = pending[channel]
                entry = item["entry"]
                device_id = item["device_id"]
                sender_id = norm_id(entry.get("sender", {}).get("id", ""))
                msg = (
                    f"FD2G14 {device_id}: beim vollständigen Series-14-Bus-Scan wurde "
                    "kein FD2G14 mit Discovery-Modell 04-82 und Größe 16 gefunden."
                )
                events.append({"status": "error", "device_id": device_id, "device_type": "FD2G14", "sender_id": sender_id, "sender_eep": "A5-38-08", "message": msg})
                processed_ids.add(device_id)
            continue

        _prepare_fd2g14_memory_access(dev)
        used_devices.add(id(dev))
        real_address = int(getattr(dev, "address", 0) or 0)
        log("FD2G14 matched", "yaml-base", yaml_base, "physical-base", real_address, "size", getattr(dev, "size", "?"))

        for channel in sorted(pending):
            item = pending[channel]
            device_id = item["device_id"]
            entry = item["entry"]
            sender_id = norm_id(entry.get("sender", {}).get("id", ""))
            sender_eep = str(entry.get("sender", {}).get("eep", "")).strip().upper()
            display_name = _device_display_name(entry, "FD2G14", device_id)
            if not sender_id or sender_eep != "A5-38-08":
                continue

            try:
                sender_address = AddressExpression.parse(sender_id)
                profile = EEP.find("A5-38-08")
                changed = await dev.ensure_programmed(channel, sender_address, profile)
                await asyncio.sleep(0.05)
                if changed:
                    status = "updated"
                    message = (
                        f"Home-Assistant Sender-ID {sender_id} für EEP {sender_eep} in {display_name} "
                        f"über FD2G14-Basisadresse {real_address} geschrieben."
                    )
                else:
                    status = "exists"
                    message = f"Sender-ID {sender_id} für EEP {sender_eep} in {display_name} existiert bereits."
            except Exception as exc:
                status = "error"
                message = (
                    f"Fehler beim Schreiben von {sender_id} ({sender_eep}) in {display_name} "
                    f"über FD2G14-Basisadresse {real_address}: {type(exc).__name__}: {exc}"
                )

            events.append({"status": status, "device_id": device_id, "device_type": "FD2G14", "sender_id": sender_id, "sender_eep": sender_eep, "message": message})
            processed_ids.add(device_id)
            log(message)

    return events


async def ensure_programmed_for_device(fam14_base_id_int: int, dev: Any, sender_map: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    from eltakobus.device import DimmerStyle, HasProgrammableRPS
    from eltakobus.eep import EEP
    from eltakobus.util import b2s
    from eltakobus.error import WriteError
    try:
        from eltakobus import AddressExpression
    except Exception:
        from eltakobus.util import AddressExpression

    events: List[Dict[str, Any]] = []
    size = int(getattr(dev, "size", 1) or 1)
    address = int(getattr(dev, "address", 0) or 0)
    dev_type = type(dev).__name__
    _prepare_fd2g14_memory_access(dev)

    for channel in range(size):
        device_ext_id = b2s((fam14_base_id_int + address + channel).to_bytes(4, "big"))
        entries = sender_map.get(device_ext_id) or []
        for entry in entries:
            sender_id = norm_id(entry.get("sender", {}).get("id", ""))
            sender_eep = str(entry.get("sender", {}).get("eep", "")).strip().upper()
            device_eep = str(entry.get("device_eep") or "").strip().upper()
            entry_name = str(entry.get("name") or "")
            entry_type = _entry_device_type(entry)
            combined_label = f"{entry_type} {entry_name}"
            display_name = _device_display_name(entry, dev_type, device_ext_id)
            is_frgbw = sender_eep == "07-37-F7" or device_eep == "07-37-F7" or "FRGBW" in combined_label.upper()
            is_fsr14ssr = "FSR14SSR" in combined_label.upper()
            is_fms14 = "FMS14" in combined_label.upper()
            is_f2l14 = "F2L14" in combined_label.upper()
            is_fhk = any(token in combined_label.upper() for token in ("FHK14", "F4HK14", "FAE14SSR", "FAE14LPR"))
            if not sender_id or not sender_eep:
                continue
            retry = 3
            last_exception: Optional[Exception] = None
            update_result = None
            while retry > 0:
                try:
                    if is_frgbw:
                        update_result = await _ensure_programmed_controller_profile(dev, sender_id, channel)
                    elif is_fsr14ssr:
                        update_result = await _ensure_programmed_fsr14ssr(dev, sender_id, channel)
                    elif is_fms14 and sender_eep == "A5-38-08":
                        update_result = await _ensure_programmed_fms14(dev, sender_id, channel)
                    elif is_f2l14 and sender_eep == "F6-02-01":
                        update_result = await _ensure_programmed_f2l14(dev, sender_id, entry.get("f2l14_mode", "exclusive"))
                    elif is_fhk and sender_eep == "A5-10-06":
                        update_result = await _ensure_programmed_fhk_controller(dev, sender_id, channel, entry_type)
                    elif isinstance(dev, HasProgrammableRPS) or isinstance(dev, DimmerStyle) or hasattr(dev, "ensure_programmed"):
                        sender_address = AddressExpression.parse(sender_id)
                        eep_profile = EEP.find(sender_eep)
                        update_result = await dev.ensure_programmed(channel, sender_address, eep_profile)
                    else:
                        update_result = None
                    last_exception = None
                    await asyncio.sleep(0.05)
                    break
                except (WriteError, TimeoutError, Exception) as e:
                    last_exception = e
                    retry -= 1
                    log("retry", 3 - retry, "failed", dev_type, device_ext_id, sender_id, sender_eep, repr(e))
                    await asyncio.sleep(0.15)
            if last_exception is not None:
                events.append({"status": "error", "device_id": device_ext_id, "device_type": entry_type, "sender_id": sender_id, "sender_eep": sender_eep, "message": f"Fehler beim Schreiben von {sender_id} ({sender_eep}) in {display_name}: {type(last_exception).__name__}: {last_exception}"})
                continue
            if update_result is None:
                status = "unsupported"
                message = f"Update für Gerät {display_name} nicht unterstützt."
            elif update_result is True:
                status = "updated"
                message = f"Home-Assistant Sender-ID {sender_id} für EEP {sender_eep} in {display_name} geschrieben."
            else:
                status = "exists"
                message = f"Sender-ID {sender_id} für EEP {sender_eep} in {display_name} existiert bereits."
            events.append({"status": status, "device_id": device_ext_id, "device_type": entry_type, "sender_id": sender_id, "sender_eep": sender_eep, "message": message})
            log(message)
    return events

def _format_fam14_base_id(value: Any) -> str:
    """Format FAM14 Base-ID exactly like the EEDTOY detector."""
    if value is None:
        return ""
    if isinstance(value, str):
        return norm_id(value)
    if isinstance(value, int):
        raw = value.to_bytes(4, "big", signed=False)
        return "-".join(f"{byte:02X}" for byte in raw)
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value[:4])
        if len(raw) == 4:
            return "-".join(f"{byte:02X}" for byte in raw)
    if isinstance(value, list) and len(value) >= 4:
        return "-".join(f"{int(byte) & 0xFF:02X}" for byte in value[:4])
    return norm_id(str(value))


async def _best_effort_bus_unlock(bus: Any) -> None:
    """Release the Series-14 bus without waiting for an acknowledgement.

    EEDTOY's explicit "Gateway trennen" path sends the raw bus-unlock frame
    and closes the port without requiring a reply. This is important after a
    lock request whose acknowledgement was lost: the FAM14 may already have
    taken control of the bus even though lock_bus() did not return LOCKED.
    """
    try:
        from eltakobus.message import EltakoBusUnlock

        base_exchange = getattr(bus, "base_exchange", None)
        if callable(base_exchange):
            await base_exchange(EltakoBusUnlock())
            await asyncio.sleep(0.25)
            return

        sender = getattr(bus, "_send", None)
        if callable(sender):
            sender(EltakoBusUnlock())
            await asyncio.sleep(0.25)
    except Exception:
        return


async def read_fam14_bus_base_id(
    port: str,
    baud_rate: int | None = None,
) -> Dict[str, Any]:
    """Detect a directly connected FAM14 and read its real bus Base-ID.

    Match EEDTOY's write path: 57600 first, then 9600, require FAM14 echo
    behaviour, try to lock the bus, but do not treat a missing lock ACK as a
    fatal error. A FAM14 can already have taken the bus even when the ACK is
    lost. The authoritative check is whether memory row 1 at address 255 can
    actually be read.
    """
    from eltakobus import locking
    from eltakobus.message import EltakoMemoryRequest, EltakoMemoryResponse
    from eltakobus.serial import RS485SerialInterfaceV2

    candidates = [int(baud_rate)] if baud_rate else [57600, 9600]
    attempts: list[dict[str, Any]] = []

    for candidate_baud in candidates:
        bus = None
        lock_state = ""
        try:
            bus = RS485SerialInterfaceV2(
                port,
                baud_rate=candidate_baud,
                delay_message=0.001 if candidate_baud == 57600 else 0.2,
                auto_reconnect=False,
            )
            bus.start()
            bus.is_serial_connected.wait(timeout=2)

            if not bus.is_active():
                attempts.append(
                    {
                        "baud_rate": candidate_baud,
                        "stage": "open",
                        "error": "RS485Interface nicht aktiv",
                    }
                )
                continue

            suppress_echo = bool(getattr(bus, "suppress_echo", False))
            if not suppress_echo:
                attempts.append(
                    {
                        "baud_rate": candidate_baud,
                        "stage": "identify",
                        "suppress_echo": False,
                        "error": "Kein direkt angeschlossener FAM14 (suppress_echo=False)",
                    }
                )
                continue

            try:
                bus.set_callback(None)
            except Exception:
                pass

            # Recover from a previous interrupted/half-acknowledged lock first.
            await _best_effort_bus_unlock(bus)

            try:
                lock_result = await asyncio.wait_for(
                    locking.lock_bus(bus),
                    timeout=8.0,
                )
                lock_state = str(lock_result)
            except asyncio.TimeoutError:
                # Do not abort here. The FAM14 can visibly take over the bus
                # while the lock acknowledgement is lost. EEDTOY's writer also
                # continues when lock_bus() did not return LOCKED.
                lock_state = "timeout_no_ack"

            # Read the FAM14 Base-ID exactly from memory row 1 at address 255.
            # This is the authoritative proof that the direct FAM14 bus access
            # is actually working.
            try:
                response = await bus.exchange(
                    EltakoMemoryRequest(255, 1),
                    EltakoMemoryResponse,
                    retries=3,
                    timeout=1.5,
                )
            except Exception as err:
                attempts.append(
                    {
                        "baud_rate": candidate_baud,
                        "stage": "memory_row_1",
                        "suppress_echo": True,
                        "lock_state": lock_state,
                        "error": f"{type(err).__name__}: {err}",
                    }
                )
                continue

            value = bytes(getattr(response, "value", b"") or b"")
            base_id = _format_fam14_base_id(value[:4])
            if not base_id or base_id == "00-00-00-00":
                attempts.append(
                    {
                        "baud_rate": candidate_baud,
                        "stage": "memory_row_1",
                        "suppress_echo": True,
                        "lock_state": lock_state,
                        "error": "FAM14 Speicherzeile 1 enthält keine gültige Base-ID",
                    }
                )
                continue

            return {
                "ok": True,
                "fam14_base_id": base_id,
                "baud_rate": candidate_baud,
                "suppress_echo": True,
                "lock_state": lock_state,
                "attempts": attempts,
            }
        except Exception as err:
            attempts.append(
                {
                    "baud_rate": candidate_baud,
                    "stage": "exception",
                    "lock_state": lock_state,
                    "error": f"{type(err).__name__}: {err}",
                }
            )
        finally:
            if bus is not None:
                # Always release the bus, even when the lock acknowledgement
                # was lost or the probe was cancelled halfway through.
                try:
                    await _best_effort_bus_unlock(bus)
                except Exception:
                    pass
                try:
                    bus.stop()
                    bus.join(0.8)
                except Exception:
                    pass

    details = "; ".join(
        f"{item.get('baud_rate')} Baud/{item.get('stage')}: {item.get('error')}"
        + (f" [lock={item.get('lock_state')}]" if item.get("lock_state") else "")
        for item in attempts
    )
    return {
        "ok": False,
        "stage": "detect_fam14",
        "attempts": attempts,
        "error": (
            "Direkt angeschlossener FAM14 konnte nicht verifiziert werden. "
            + (details or "Keine gültige Antwort.")
        ),
    }


async def write_sender_entries(port: str, entries: list[dict[str, Any]], baud_rate: int = 57600, gateway_type: str = "fam14") -> Dict[str, Any]:
    from eltakobus import locking
    from eltakobus.device import FAM14, create_busobject
    from eltakobus.serial import RS485SerialInterfaceV2
    from eltakobus.util import b2s

    sender_map = build_sender_map(entries)
    if not sender_map:
        return {"ok": False, "error": "Keine Sender-IDs zum Schreiben vorhanden.", "events": []}

    bus = None
    locked = False
    events: List[Dict[str, Any]] = []
    try:
        delay_message = 0.001 if baud_rate == 57600 else 0.2
        log("connect", port, baud_rate, gateway_type, "sender entries", sum(len(entries) for entries in sender_map.values()))
        bus = RS485SerialInterfaceV2(port, baud_rate=baud_rate, delay_message=delay_message, auto_reconnect=False)
        bus.start()
        bus.is_serial_connected.wait(timeout=2)
        if not bus.is_active():
            return {"ok": False, "error": f"Port {port} geöffnet, aber Bus ist nicht aktiv.", "events": []}

        try:
            bus.set_callback(None)
        except Exception:
            pass

        await _best_effort_bus_unlock(bus)
        locked = (await locking.lock_bus(bus)) == locking.LOCKED
        log("bus locked", locked)

        fam14: FAM14 = await create_busobject(bus=bus, id=255)
        fam14_base_id_int = await fam14.get_base_id_in_int()
        fam14_base_id = b2s(await fam14.get_base_id_in_bytes())
        log("fam14 base", fam14_base_id)

        expected_bases = {entry["expected_bus_base_id"] for entries in sender_map.values()
                          for entry in entries if entry.get("expected_bus_base_id")}
        if expected_bases and expected_bases != {norm_id(fam14_base_id)}:
            return {"ok": False, "events": [], "error":
                    f"Falsches Bussystem angeschlossen: FAM14 {fam14_base_id}; erwartet: {', '.join(sorted(expected_bases))}. Es wurde nichts geschrieben."}

        target_addresses = target_bus_addresses(fam14_base_id_int, sender_map)
        log("target bus addresses", ",".join(str(a) for a in target_addresses))
        processed_ids: Set[str] = set()

        async for dev in enumerate_target_devices(bus, target_addresses):
            device_events = await ensure_programmed_for_device(fam14_base_id_int, dev, sender_map)
            events.extend(device_events)
            processed_ids.update(e.get("device_id", "") for e in device_events)

        fd2g_events = await ensure_fd2g14_from_yaml(bus, fam14_base_id_int, sender_map, processed_ids)
        events.extend(fd2g_events)

        for device_id, entries in sender_map.items():
            if device_id in processed_ids:
                continue
            for entry in entries:
                sender_id = norm_id(entry.get("sender", {}).get("id", ""))
                sender_eep = str(entry.get("sender", {}).get("eep", "")).strip().upper()
                display_name = _device_display_name(entry, "BusObject", device_id)
                events.append({
                    "status": "error",
                    "device_id": device_id,
                    "device_type": _entry_device_type(entry),
                    "sender_id": sender_id,
                    "sender_eep": sender_eep,
                    "message": f"Busgerät {display_name} wurde an der erwarteten Series-14-Adresse nicht gefunden.",
                })

        counts: Dict[str, int] = {}
        for event in events:
            counts[event.get("status", "unknown")] = counts.get(event.get("status", "unknown"), 0) + 1

        return {
            "ok": True,
            "fam14_base_id": fam14_base_id,
            "target_addresses": target_addresses,
            "scanned_devices": len({e.get("device_id") for e in events if e.get("device_id")}),
            "events": events,
            "counts": counts,
            "message": f"Sender-ID Schreiben beendet. Aktualisiert: {counts.get('updated', 0)}, bereits vorhanden: {counts.get('exists', 0)}, nicht unterstützt: {counts.get('unsupported', 0)}, Fehler: {counts.get('error', 0)}.",
        }
    finally:
        if bus is not None:
            try:
                await _best_effort_bus_unlock(bus)
                log("bus unlocked")
            except Exception as e:
                log("unlock failed", repr(e))
            try:
                bus.stop()
                bus.join(0.8)
            except Exception:
                pass


