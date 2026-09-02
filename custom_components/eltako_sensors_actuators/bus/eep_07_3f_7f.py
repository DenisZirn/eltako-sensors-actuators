from __future__ import annotations

from .esp2 import ESP2Message, build_regular_4bs
from .esp3 import build_esp3_radio_erp1_4bs_direct
from .ids import parse_address


# ELTAKO free profile 07-3F-7F for FRGBW14 / FRGBW71L.
# 4BS data bytes in this code are ordered as DB3, DB2, DB1, DB0.
# According to the ELTAKO telegram description:
#   DB0 = 0x0F controller telegram
#   DB1 = command: 0x10 red, 0x11 green, 0x12 blue, 0x13 white
#   DB3..DB2 = dimmer value in 10 bit
# This module intentionally sends one telegram per color component. That mirrors
# the actuator profile better than the earlier guessed single RGB telegram.

COMMAND_RED = 0x10
COMMAND_GREEN = 0x11
COMMAND_BLUE = 0x12
COMMAND_WHITE = 0x13
CONTROLLER_TELEGRAM = 0x0F


def _scale_byte(value: int | None, default: int = 255) -> int:
    if value is None:
        return default
    return max(0, min(255, int(value)))


def _to_10bit(value_0_255: int) -> int:
    value_0_255 = _scale_byte(value_0_255, 0)
    if value_0_255 <= 0:
        return 0
    if value_0_255 >= 255:
        return 1023
    # GFA/FRGBW14 sniffer reference (2026-08-07) confirms a linear 8-bit
    # Home Assistant value to the full 10-bit 07-3F-7F range.  The payload is
    # transmitted DB3=high byte, DB2=low byte, e.g. 100% = 03-FF and an
    # observed ~50% white value = 01-FD.
    return max(0, min(1023, int(round(value_0_255 * 1023.0 / 255.0))))


def _encode_10bit(value_0_255: int) -> tuple[int, int]:
    value = _to_10bit(value_0_255)
    # v0.1.76: GFA5 reference telegrams prove that the FRGBW71L expects
    # DB3..DB2 in network/document order, not the earlier low-byte-first guess:
    #   0%   = 0x000 -> DB3=0x00, DB2=0x00
    #   50%  ~=0x200 -> DB3=0x02, DB2=0x00
    #   100% = 0x3FF -> DB3=0x03, DB2=0xFF
    db3 = (value >> 8) & 0x03
    db2 = value & 0xFF
    return db3, db2


def build_07_3f_7f_component(
    sender_id: str,
    command: int,
    value: int,
    *,
    status: int = 0x00,
    outgoing: bool = True,
) -> ESP2Message:
    address = parse_address(sender_id)
    db3, db2 = _encode_10bit(value)
    data = bytes([db3, db2, command & 0xFF, CONTROLLER_TELEGRAM])
    return build_regular_4bs(address, data, status=status, outgoing=outgoing)


def build_07_3f_7f_component_direct(sender_id: str, command: int, value: int, *, destination_id: str, status: int = 0x80) -> bytes:
    address = parse_address(sender_id)
    destination = parse_address(destination_id)
    db3, db2 = _encode_10bit(value)
    data = bytes([db3, db2, command & 0xFF, CONTROLLER_TELEGRAM])
    return build_esp3_radio_erp1_4bs_direct(address, data, status=status, destination=destination, subtelegram_count=3)


def build_07_3f_7f_component_messages(
    sender_id: str,
    command: int,
    value: int,
    *,
    status: int = 0x81,
    destination_id: str | None = None,
    outgoing: bool = True,
) -> list[ESP2Message | bytes]:
    """Build one GFA5-compatible 07-3F-7F controller telegram.

    If destination_id is passed, this emits an ESP3 directed RF packet.
    FRGBW14 on FAM14/FGW14-USB must normally NOT pass destination_id because
    Home Assistant writes onto the Series-14 RS485 bus, which is not visible
    as a radio DestinationID in the RF sniffer. FRGBW71L/FAM-USB also uses
    the proven ESP2 path without optional destination.
    """
    if destination_id:
        return [build_07_3f_7f_component_direct(sender_id, command, value, destination_id=destination_id, status=status)]
    return [
        build_07_3f_7f_component(
            sender_id,
            command,
            value,
            status=status,
            outgoing=outgoing,
        )
    ]



def build_07_3f_7f_confirmation_request(sender_id: str, *, status: int = 0x00) -> ESP2Message:
    """Request a FRGBW71L confirmation telegram.

    ELTAKO 07-3F-7F documents DB1=0x02 as "Bestaetigungstelegramm
    anfordern" with DB0=0x0F for the controller/master telegram. This is a
    diagnostic command: if the actuator has learned this sender in the free
    07-3F-7F profile, it should answer with a 0x0E confirmation telegram.
    """
    address = parse_address(sender_id)
    data = bytes([0x00, 0x00, 0x02, CONTROLLER_TELEGRAM])
    return build_regular_4bs(address, data, status=status, outgoing=True)


def build_07_3f_7f_color_learn_messages(sender_id: str, *, destination_id: str | None = None) -> list[ESP2Message | bytes]:
    """Send the practical FRGBW71L color-controller learn/first-use sequence.

    In the real installation the documented FF-F8-0D-87 free-profile learn
    telegram was not accepted, while GFA5/MiniSafe controls the actuator by
    sending ordinary 07-3F-7F color component telegrams from its controller
    sender id. This helper mirrors that behavior for the Home Assistant sender
    id: it sends a complete red target (R=100%, G=0%, B=0%) with status 0x80.

    Use this while the FRGBW71L is in mode 9 / MiniSafe color-controller learn
    mode. The actuator should answer every component with DB0=0x0E if it has
    accepted the sender as color controller.
    """
    messages: list[ESP2Message] = []
    for command, value in (
        (COMMAND_RED, 255),
        (COMMAND_GREEN, 0),
        (COMMAND_BLUE, 0),
    ):
        messages.extend(build_07_3f_7f_component_messages(sender_id, command, value, status=0x80, destination_id=destination_id))
    return messages


def build_07_3f_7f_confirmation_request_messages(sender_id: str, *, repeat: int = 1) -> list[ESP2Message]:
    return [build_07_3f_7f_confirmation_request(sender_id, status=0x00) for _ in range(max(1, int(repeat)))]

def build_07_3f_7f_rgbw_messages(
    sender_id: str,
    *,
    destination_id: str | None = None,
    r: int = 255,
    g: int = 255,
    b: int = 255,
    w: int = 0,
    brightness: int = 255,
    state: bool = True,
    status: int = 0x81,
    include_white: bool = False,
    outgoing: bool = True,
) -> list[ESP2Message | bytes]:
    brightness = _scale_byte(brightness, 255 if state else 0)
    if not state or brightness <= 0:
        r = g = b = w = 0
    else:
        # Home Assistant provides color channel values at full brightness plus a
        # separate brightness. Scale every component by brightness so the ELTAKO
        # actuator receives absolute 10-bit channel dim values.
        factor = brightness / 255.0
        r = int(round(_scale_byte(r) * factor))
        g = int(round(_scale_byte(g) * factor))
        b = int(round(_scale_byte(b) * factor))
        w = int(round(_scale_byte(w, 0) * factor))

    messages: list[ESP2Message | bytes] = []
    # Send the RGB channels in the exact order observed from the working GFA5
    # controller. Its FRGBW14 colour command is one compact three-frame burst:
    # red (0x10), green (0x11), blue (0x12). A white HA component is folded
    # into RGB unless a caller explicitly requests a separate 0x13 channel.
    components = [
        (COMMAND_RED, r),
        (COMMAND_GREEN, g),
        (COMMAND_BLUE, b),
    ]
    if include_white:
        components.append((COMMAND_WHITE, w))
    elif w > 0:
        # Preserve the proven FRGBW71L behavior: represent white through RGB.
        components = [
            (COMMAND_RED, max(r, w)),
            (COMMAND_GREEN, max(g, w)),
            (COMMAND_BLUE, max(b, w)),
        ]

    for command, value in components:
        messages.extend(
            build_07_3f_7f_component_messages(
                sender_id,
                command,
                value,
                status=status,
                destination_id=destination_id,
                outgoing=outgoing,
            )
        )

    return messages


def build_07_3f_7f_rgbw(sender_id: str, **kwargs) -> ESP2Message:
    # Backwards-compatible helper for old callers. The gateway now uses the list
    # variant so all color components are transmitted.
    return build_07_3f_7f_rgbw_messages(sender_id, **kwargs)[0]


def build_07_3f_7f_off_messages(
    sender_id: str,
    *,
    destination_id: str | None = None,
    include_white_zero: bool = False,
    status: int = 0x81,
    outgoing: bool = True,
) -> list[ESP2Message | bytes]:
    messages = build_07_3f_7f_rgbw_messages(
        sender_id,
        destination_id=destination_id,
        r=0,
        g=0,
        b=0,
        w=0,
        brightness=0,
        state=False,
        status=status,
        outgoing=outgoing,
    )
    if include_white_zero:
        messages.extend(
            build_07_3f_7f_component_messages(
                sender_id,
                COMMAND_WHITE,
                0,
                status=status,
                destination_id=destination_id,
                outgoing=outgoing,
            )
        )
    return messages


def build_07_3f_7f_off(sender_id: str) -> ESP2Message:
    return build_07_3f_7f_off_messages(sender_id)[0]
