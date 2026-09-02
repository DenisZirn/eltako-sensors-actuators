from __future__ import annotations

"""ELTAKO Series-14 direct bus command helpers.

FMS14 and the related multi-channel Series-14 switching actuators use a
PTM200/RPS telegram for direct switching.  Each actuator channel is addressed
with its configured controller/channel sender id.
"""

from .esp2 import ESP2Message, build_rps
from .ids import parse_address


def build_series14_switch_command(sender_id: str, state: bool) -> ESP2Message:
    """Build the Series-14 PTM200/RPS switch telegram.

    ORG = 0x05
    DB3/data byte:
      ON  = 0x70
      OFF = 0x50
    status = 0x30

    ``sender_id`` is the controller/channel address configured for the actor,
    e.g. 00-00-B0-0A.
    """
    return build_rps(
        parse_address(sender_id),
        0x70 if state else 0x50,
        status=0x30,
        outgoing=True,
    )
