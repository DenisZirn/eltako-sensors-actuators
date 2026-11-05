"""Adapt serialx port metadata to the integration's stable USB gateway resolver.

Used by the serialx transport. All other gateway matching rules remain
unchanged, including FAM-USB interface if01 and FTDI FT232R detection.
"""
from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import serialx

_LOGGER = logging.getLogger(__name__)


def _as_legacy_port(info):
    device = str(getattr(info, "device", "") or "")
    manufacturer = str(getattr(info, "manufacturer", "") or "")
    product = str(getattr(info, "product", "") or "")
    serial_number = getattr(info, "serial_number", None)
    iface_desc = str(getattr(info, "interface_description", "") or "")
    iface_num = getattr(info, "interface_num", None)
    if iface_num is not None:
        interface = f"Interface {int(iface_num):02d} {iface_desc}".strip()
    else:
        interface = iface_desc
    vid = getattr(info, "vid", None)
    pid = getattr(info, "pid", None)
    vid_pid = f"{int(vid):04X}:{int(pid):04X}" if vid is not None and pid is not None else ""
    description = " ".join(x for x in (product, interface) if x).strip()
    if not description:
        description = str(getattr(info, "description", "") or manufacturer or Path(device).name)
    hwid = " ".join(x for x in (
        f"USB VID:PID={vid_pid}" if vid_pid else "",
        f"SER={serial_number}" if serial_number else "",
        manufacturer, product, interface, device,
    ) if x)
    return SimpleNamespace(
        device=device, name=Path(device).name, description=description,
        hwid=hwid, interface=interface, location="",
        vid=vid, pid=pid, manufacturer=manufacturer, product=product,
        serial_number=serial_number,
    )


class list_ports:
    """Provide the limited old comports() shape used by this integration."""

    @staticmethod
    def comports(*, include_links: bool = False):
        # serialx on Linux already prioritizes /dev/serial/by-id/ links.
        try:
            return [_as_legacy_port(info) for info in serialx.list_serial_ports()]
        except Exception as exc:
            # Keep existing config_flow fallback scanning /dev/serial/by-id.
            _LOGGER.warning("serialx port enumeration unavailable: %s", exc)
            return []
