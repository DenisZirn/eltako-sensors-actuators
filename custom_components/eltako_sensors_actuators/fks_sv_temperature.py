"""Compatibility wrapper for the first FKS-SV-only v0.1.164 test build.

New code uses room_temperature.py. Keep these imports so an already-running
test installation can reload cleanly while the test series evolves.
"""

from .room_temperature import (
    is_fks_sv_device,
    normalize_enocean_id,
    resolve_room_temperature_config as resolve_fks_sv_temperature_config,
    room_temperature_overrides as fks_sv_overrides,
    select_numeric_room_temperature as select_fks_sv_room_temperature,
    set_room_temperature_override as set_fks_sv_override,
    temperature_to_celsius,
)

__all__ = [
    "fks_sv_overrides",
    "is_fks_sv_device",
    "normalize_enocean_id",
    "resolve_fks_sv_temperature_config",
    "select_fks_sv_room_temperature",
    "set_fks_sv_override",
    "temperature_to_celsius",
]
