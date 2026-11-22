"""Model-specific FHK61 family RPS confirmation decoding.

FHK61-230V and temperature-mode FHK61SSR-230V report operating modes, not relay
contacts. FHK61U-230V uses the same RPS codes for physical relay feedback.
Do not infer relay state from an FHK61 mode acknowledgement.
"""
from __future__ import annotations


_FHK61_MODE_CODES = {
    0x70: ("normal", "Normalbetrieb"),
    0x50: ("night_setback", "Nachtabsenkung (-4 K)"),
    0x30: ("setback", "Absenkbetrieb (-2 K)"),
    0x10: ("off", "Aus / Frostschutz"),
}


def decode_fhk61_rps_feedback(
    data: bytes,
    device_type: str | None,
    *,
    control_mode: str = "temperature",
) -> dict[str, object]:
    """Decode physical RPS feedback, keeping PWM and temperature modes apart.

    FHK61SSR direct PWM uses 0x70/0x50 for the 230V dewpoint input, whereas
    temperature mode uses these values for normal/night-setback.  The same
    RPS code has different meaning depending on the *learned* control mode.
    """
    if len(data) != 4 or data[1:] != b"\x00\x00\x00":
        return {}
    model = str(device_type or "").strip().upper().replace("-", "").replace("_", "").replace(" ", "")
    code = data[0]
    if model.startswith("FHK61SSR") and control_mode == "direct_pwm":
        if code not in (0x70, 0x50):
            return {}
        return {
            "fhk61_feedback_type": "dewpoint_input",
            "fhk61_dewpoint_input_active": code == 0x70,
            "fhk61_dewpoint_code": f"0x{code:02X}",
        }
    if model.startswith("FHK61U"):
        if code in (0x70, 0x50):
            return {
                "fhk61_feedback_type": "relay",
                "fhk61_relay_on": code == 0x70,
                "fhk61_relay_code": f"0x{code:02X}",
            }
        return {}
    if model.startswith("FHK61"):
        mode = _FHK61_MODE_CODES.get(code)
        if mode is not None:
            return {
                "fhk61_feedback_type": "operating_mode",
                "fhk61_mode": mode[0],
                "fhk61_mode_label": mode[1],
                "fhk61_mode_code": f"0x{code:02X}",
            }
    return {}
