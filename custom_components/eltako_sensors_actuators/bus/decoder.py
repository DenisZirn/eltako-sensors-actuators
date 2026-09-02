from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
import re

from .esp2 import ESP2Message, ORG_1BS, ORG_4BS, ORG_RPS
from .ids import format_address
from .eep_a5_20_01 import (
    decode_a5_20_01_actuator_status,
    decode_a5_20_01_controller_telegram,
)
from .eep_a5_04 import decode_a5_04
from .eep_a5_09_04 import decode_a5_09_04
from .eep_a5_10_12 import decode_a5_10_12
from .eep_a5_20_04 import decode_a5_20_04_controller_telegram
from .eep_ffg7b import decode_ffg7b_a5, decode_ffg7b_rps


def decode_esp2_message(
    message: ESP2Message,
    eep: str | None = None,
    *,
    direction: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Return sender address and decoded payload for a received ESP2 message."""
    body = message.body
    org = body[1]
    sender_id = format_address(body[6:10])
    data = body[2:6]
    eep_text = str(eep or "").upper().strip()
    eep_match = re.search(r"(?:^|[^0-9A-F])([A-F0-9]{2}-[A-F0-9]{2}-[A-F0-9]{2})(?:$|[^0-9A-F])", eep_text)
    normalized_eep = eep_match.group(1) if eep_match else eep_text

    decoded: dict[str, Any] = {
        "raw": message.serialize().hex("-"),
        "data_hex": data.hex("-"),
        "org": f"0x{org:02X}",
        "physical_sender_id": sender_id,
        "last_seen": datetime.now(timezone.utc).isoformat(),
    }

    if org == ORG_RPS:
        decoded.update(_decode_rps(body[2], normalized_eep))
        return sender_id, decoded

    if org == ORG_1BS:
        decoded.update(_decode_1bs(body[2], normalized_eep))
        return sender_id, decoded

    if org == ORG_4BS:
        if normalized_eep == "A5-20-01":
            if str(direction or "").lower() in {"controller", "to_actuator", "tx"}:
                decoded.update(decode_a5_20_01_controller_telegram(data))
            else:
                decoded.update(decode_a5_20_01_actuator_status(data))
        elif normalized_eep == "A5-20-04" and str(direction or "").lower() in {"controller", "to_actuator", "tx"}:
            decoded.update(decode_a5_20_04_controller_telegram(data))
        elif normalized_eep == "A5-10-12":
            decoded.update(decode_a5_10_12(data))
        else:
            decoded.update(_decode_4bs(data, normalized_eep))
        return sender_id, decoded

    decoded["value"] = data.hex("-")
    return sender_id, decoded



def _decode_1bs(data_byte: int, eep: str) -> dict[str, Any]:
    if eep == "D5-00-01":
        # ELTAKO FTKB / D5-00-01 uses 1BS frames for the contact state.
        # The ELTAKO manual names the data byte as Data_byte3:
        #   0x09 = contact closed, 0x08 = contact open.
        # Some generic D5-00-01 implementations only look at bit 0; keep the
        # explicit ELTAKO values first and fall back to the bit interpretation.
        if data_byte == 0x09:
            is_open = False
        elif data_byte == 0x08:
            is_open = True
        else:
            is_open = not bool(data_byte & 0x01)
        return {
            "open": is_open,
            "closed": not is_open,
            "contact_raw": data_byte,
            "learn": data_byte == 0x00 or not bool(data_byte & 0x08),
            "value": data_byte,
        }
    return {"value": data_byte}

def _decode_rps(data_byte: int, eep: str) -> dict[str, Any]:
    if eep == "F6-10-00":
        # FFG7B three-state window handle. The helper keeps the exact
        # closed/open/tilted semantics in one place.
        result = decode_ffg7b_rps(data_byte)
        result["button_action"] = data_byte
        return result
    if eep == "D5-00-01":
        # FTKE and other contact variants keep the known 0x50/0x70 and
        # 0x10/0x30 mappings.
        state_map = {
            0x70: "geschlossen",
            0x50: "offen",
            0x30: "geschlossen",
            0x10: "offen",
        }
        window_state = state_map.get(data_byte)
        if window_state is None:
            is_open = bool(data_byte & 0x10)
        else:
            is_open = window_state != "geschlossen"
        result = {
            "open": is_open,
            "closed": not is_open,
            "tilted": False,
            "value": data_byte,
            "button_action": data_byte,
        }
        if window_state is not None:
            result["window_state"] = window_state
        return result
    if eep == "F6-01-01":
        # ELTAKO FNSN55EB / FNS65EB proximity switch (EEP F6-01-01):
        #   DB3 = 0x10 -> hand in detection area
        #   DB3 = 0x00 -> hand removed
        # Other values are not documented for the device and are deliberately
        # left without a state key so Home Assistant keeps the previous state.
        if data_byte == 0x10:
            return {
                "presence": True,
                "pressed": True,
                "proximity_raw": data_byte,
                "value": data_byte,
            }
        if data_byte == 0x00:
            return {
                "presence": False,
                "pressed": False,
                "proximity_raw": data_byte,
                "value": data_byte,
            }
        return {"proximity_raw": data_byte, "value": data_byte}
    if eep == "F6-02-01":
        pressed = data_byte != 0x00

        # ELTAKO 4-way rocker mapping used by F2T55/FT55 style buttons.
        # The signal codes are commonly shown as 10/30/50/70 in ELTAKO tools;
        # on the wire these are the byte values 0x10/0x30/0x50/0x70.
        position_map = {
            0x30: ("left_top", "Left Top", "Oben links"),
            0x70: ("right_top", "Right Top", "Oben rechts"),
            0x10: ("left_bottom", "Left Bottom", "Unten links"),
            0x50: ("right_bottom", "Right Bottom", "Unten rechts"),
            0x00: ("released", "Released", "Losgelassen"),
        }
        position, label_en, label_de = position_map.get(
            data_byte,
            ("unknown", f"0x{data_byte:02X}", f"0x{data_byte:02X}"),
        )

        heating_mode_map = {
            0x70: ("normal", "Normalbetrieb", 0),
            0x50: ("night_reduction", "Nachtabsenkung", -4),
            0x30: ("reduced", "Absenkbetrieb", -2),
            0x10: ("frost_protection", "Aus / Frostschutz", None),
        }
        heating_mode, heating_mode_label, temperature_reduction = heating_mode_map.get(
            data_byte, ("unknown", f"0x{data_byte:02X}", None)
        )

        return {
            "pressed": pressed,
            "button_action": data_byte,
            "heating_mode": heating_mode,
            "heating_mode_label": heating_mode_label,
            "temperature_reduction": temperature_reduction,
            "frost_protection": data_byte == 0x10,
            "signal_code": f"{data_byte:02X}",
            "signal_code_decimal": data_byte,
            "button_position": position,
            "pushed_buttons": label_en,
            "button_label": label_en,
            "button_label_de": label_de,
            "last_action": label_de,
            "value": data_byte,
        }
    return {"value": data_byte, "button_action": data_byte}


def _decode_4bs(data: bytes, eep: str) -> dict[str, Any]:
    db3, db2, db1, db0 = data

    # FSM60B can be changed between BA3 and BA4 without changing its EnOcean ID.
    # Detect the active operating mode from the actual field telegram instead of
    # trusting a possibly stale YAML EEP.
    if eep in ("A5-30-01", "A5-30-03"):
        if data in (
            bytes((0x00, 0x90, 0x00, 0x0E)),
            bytes((0x00, 0x90, 0xFF, 0x0E)),
        ):
            eep = "A5-30-01"
        elif data in (
            bytes((0x00, 0x00, 0x0F, 0x08)),
            bytes((0x00, 0x00, 0x1F, 0x08)),
        ):
            eep = "A5-30-03"

    if eep == "A5-30-03":
        # FRWB and FSM60B BA3 share EEP A5-30-03.
        # Confirmed data telegrams:
        #   DB1 0x0F = alarm, DB1 0x1F = no alarm, DB0 0x08 = data.
        # FRWB additionally carries inverted 0..40 °C temperature in DB2.
        learn = not bool(db0 & 0x08)
        common = {
            "learn": learn,
            "learn_telegram": learn,
            "data_telegram": not learn,
            "value": data.hex("-"),
        }
        if learn:
            common["telegram_type"] = "a5_30_03_teach_in"
            return common

        if db0 != 0x08 or db1 not in (0x0F, 0x1F):
            common.update({
                "telegram_type": "a5_30_03_unrecognized",
                "ignored": True,
            })
            return common

        alarm = db1 == 0x0F
        temperature = (255 - db2) * 40.0 / 255.0
        common.update({
            # FRWB entities
            "smoke_alarm": alarm,
            "temperature": round(temperature, 1),
            # FSM60B BA3 entities
            "moisture": alarm,
            "wet": alarm,
            "water_alarm": alarm,
            # shared diagnostics
            "alarm": alarm,
            "pressed": alarm,
            "open": not alarm,
            "closed": alarm,
            "temperature_raw": int(db2),
            "telegram_type": "a5_30_03_alarm_temperature",
        })
        return common

    if eep == "A5-30-01":
        # ELTAKO FSM60B operating mode 4, measured telegrams:
        #   00-8F-00-0E = input/contact active (pressed)
        #   00-8F-FF-0E = input/contact inactive (released)
        #
        # The contact state is carried in DB1, while the battery status is
        # carried independently in the lower nibble of DB2.  Keeping these
        # fields separate prevents a contact change from incorrectly setting
        # the battery entity to 0 percent.
        learn = not bool(db0 & 0x08)
        contact_closed = db1 == 0x00
        contact_open = not contact_closed
        battery_raw = int(db2 & 0x0F)
        battery_percentage = round(battery_raw / 15.0 * 100.0)
        return {
            "open": contact_open,
            "closed": contact_closed,
            "contact_open": contact_open,
            "contact_closed": contact_closed,
            "pressed": contact_closed,
            "learn": learn,
            "learn_telegram": learn,
            "data_telegram": not learn,
            "battery_raw": battery_raw,
            "battery_percentage": battery_percentage,
            "battery_low": battery_raw <= 2,
            "value": data.hex("-"),
            "telegram_type": "fsm60b_ba4_contact_battery",
        }

    if eep == "A5-14-09":
        return decode_ffg7b_a5(data)

    if eep == "D5-00-01":
        # ELTAKO FTKB also sends a 4BS voltage telegram with the same ID:
        # DB0 = 0x08, DB1 = 0x00, DB2 = battery voltage 0..5 V,
        # DB3 = energy storage 0..5 V. Accept DB0 bit3 set as well, because
        # field captures may show 0x09 while still carrying the same voltage
        # payload family.
        if db1 == 0x00 and (db0 & 0x08):
            battery_voltage = round(db2 / 255.0 * 5.0, 2)
            energy_storage_voltage = round(db3 / 255.0 * 5.0, 2)
            return {
                "battery_voltage": battery_voltage,
                "energy_storage_voltage": energy_storage_voltage,
                "value": data.hex("-"),
                "telegram_type": "ftkb_voltage",
            }
        return {"value": data.hex("-"), "telegram_type": "d5_00_01_4bs_unknown"}

    if eep in {"A5-04-01", "A5-04-02", "A5-04-03"}:
        return decode_a5_04(data, eep)

    if eep == "A5-09-04":
        return decode_a5_09_04(data)

    if eep == "A5-09-0C":
        # FLGTF / A5-09-0C air quality. Keep the byte layout compatible
        # with the established decoder behavior:
        #   DB3..DB2 = concentration base value,
        #   DB1      = VOC substance type (0 = VOCT Total used by FLGTF),
        #   DB0 bit3 = LRN bit, bit2 = unit, bit1..0 = scale multiplier.
        #
        # The previous decoder assumed DB0 to be a fixed 0x0A and ignored the
        # scale bits. That can leave TVOC unknown or numerically wrong for real
        # A5-09-0C telegrams.
        concentration_base = (db3 << 8) | db2
        scale_code = db0 & 0x03
        multiplier = 0.01 * (10 ** scale_code)
        concentration = concentration_base * multiplier
        voc_type = int(db1)
        unit_code = (db0 & 0x04) >> 2
        # Home Assistant entity for FLGTF exposes VOCT Total as ppb. If another
        # A5-09-0C substance type ever appears, keep the raw concentration too.
        tvoc = round(concentration, 2) if voc_type == 0 else None
        result = {
            "air_quality_concentration": round(concentration, 2),
            "voc_type_index": voc_type,
            "voc_unit": "ppb" if unit_code == 0 else "ug/m3",
            "learn": (db0 & 0x08) >> 3 == 0,
            "value": data.hex("-"),
            "telegram_type": "flgtf_tvoc",
        }
        if tvoc is not None:
            result["tvoc"] = tvoc
            result["volatile_organic_compounds"] = tvoc
        return result

    # FBH55ESB/FBHT55ESB can be configured in two mutually exclusive
    # operating modes. Detect the actually received mode from the ELTAKO byte
    # patterns as a safeguard against stale YAML profiles after switching mode.
    if eep in ("A5-07-01", "A5-08-01"):
        if data == bytes((0x20, 0x08, 0x0D, 0x85)) or db0 in (0x0D, 0x0F):
            eep = "A5-08-01"
        elif data == bytes((0x1C, 0x08, 0x0D, 0x80)) or (db0 == 0x08 and db1 in (0x00, 0xC8, 0xFF)):
            eep = "A5-07-01"

    if eep == "A5-08-01":
        # ELTAKO FBH mode (FBH55ESB / FBHT55ESB):
        #   DB3 = supply voltage 0..5.1 V
        #   DB2 = brightness 0..510 lx
        #   DB1 = unused
        #   DB0 = 0x0D movement, 0x0F no movement
        #   teach-in example = 20-08-0D-85 (LRN bit in DB0 is clear)
        learn = not bool(db0 & 0x08)
        base = {
            "learn": learn,
            "learn_telegram": learn,
            "data_telegram": not learn,
            "value": data.hex("-"),
            "telegram_type": "fbh_teach_in" if learn else "fbh_motion_brightness",
            "detected_eep": "A5-08-01",
        }
        if learn:
            base["teach_in_query_data"] = bytes(data)
            return base
        if db0 == 0x0D:
            movement = True
        elif db0 == 0x0F:
            movement = False
        else:
            movement = bool(db0 & 0x02)
        base.update(
            {
                "voltage": round(db3 / 255.0 * 5.1, 2),
                "brightness": round(db2 / 255.0 * 510.0, 1),
                "brightness_raw": int(db2),
                "movement": movement,
                "motion": movement,
                "motion_raw": int(db0),
            }
        )
        return base

    if eep == "A5-07-01":
        # ELTAKO TF mode (FBH55ESB / FBHT55ESB):
        #   DB1 = 0xC8 half-automatic movement, 0xFF full-automatic
        #         movement, 0x00 no movement
        #   DB0 = 0x08 for a normal data telegram
        #   teach-in example = 1C-08-0D-80 (LRN bit in DB0 is clear)
        learn = not bool(db0 & 0x08)
        result = {
            "learn": learn,
            "learn_telegram": learn,
            "data_telegram": not learn,
            "value": data.hex("-"),
            "telegram_type": "tf_teach_in" if learn else "tf_motion",
            "detected_eep": "A5-07-01",
        }
        if learn:
            result["teach_in_query_data"] = bytes(data)
            return result
        if db1 == 0xC8:
            movement = True
            detection_mode = "halbautomatisch"
        elif db1 == 0xFF:
            movement = True
            detection_mode = "vollautomatisch"
        elif db1 == 0x00:
            movement = False
            detection_mode = "keine Bewegung"
        else:
            movement = bool(db1)
            detection_mode = f"0x{db1:02X}"
        supply_voltage = round(db3 / 255.0 * 5.1, 2)
        result.update(
            {
                "movement": movement,
                "movement_detection_mode": detection_mode,
                "movement_raw": int(db1),
                "motion_raw": int(db1),
                "voltage": supply_voltage,
                "battery_voltage": supply_voltage,
                "battery_raw": int(db3),
            }
        )
        return result

    if eep == "A5-10-06":
        # Heating/cooling controller and actuator response.  DB3 contains the
        # ELTAKO operating mode; DB0 contains controller priority (0x08/0x0A/
        # 0x0E) or 0x0F for an actuator response.  DB1 is inverted.
        target_temperature = round((db2 / 255.0) * 40.0, 1)
        current_temperature = round(((255 - db1) / 255.0) * 40.0, 1)
        mode_names = {
            0x70: "normal",
            0x50: "night_setback",
            0x30: "setback",
            0x10: "off",
            0x00: "unknown",
        }
        priority_names = {
            0x08: "home_automation",
            0x0A: "limited_thermostat",
            0x0E: "auto",
            0x0F: "actuator_response",
        }
        mode_name = mode_names.get(db3, f"0x{db3:02X}")
        priority_name = priority_names.get(db0, f"0x{db0:02X}")
        frost_protection = abs(target_temperature - 8.0) <= 0.2
        return {
            "target_temperature": target_temperature,
            "temperature": current_temperature,
            "hvac_mode": "off" if db3 == 0x10 else "heat",
            "heater_mode": mode_name,
            "heater_mode_code": db3,
            "controller_priority": priority_name,
            "controller_priority_code": db0,
            "actuator_response": db0 == 0x0F,
            "frost_protection": frost_protection,
            "setpoint_in_adjustable_range": 12.0 <= target_temperature <= 28.0,
            "value": data.hex("-"),
        }



    if eep == "A5-12-01":
        # EEP A5-12-01 Automated Meter Reading - Electricity.
        #
        # Byte layout according to the eltako14bus/EnOcean AMR model:
        #   DB3..DB1  = 24-bit meter reading
        #   DB0[7:4]  = measurement channel / tariff information
        #   DB0[3]    = learn flag
        #   DB0[2]    = data type; 0 = meter value, 1 = identification / non-meter telegram
        #   DB0[1:0]  = decimal divisor code, value / 10**divisor_code
        #
        # Earlier builds used DB0 & 0x0F as divisor. That was wrong because it
        # included learn/type bits and produced spikes such as 7,340,032 kWh.
        # Only data_type == 0 is accepted as a real kWh reading. Identification
        # telegrams update raw/last_seen only and never overwrite the meter value.
        counter = (db3 << 16) | (db2 << 8) | db1
        measurement_channel = (db0 >> 4) & 0x0F
        learn_flag = (db0 & 0x08) >> 3
        data_type = (db0 & 0x04) >> 2
        divisor_code = db0 & 0x03

        result = {
            "value": data.hex("-"),
            "meter_raw_counter": counter,
            "measurement_channel": measurement_channel,
            "learn_flag": learn_flag,
            "data_type": data_type,
            "divisor_code": divisor_code,
            "is_meter_reading": data_type == 0,
        }

        # ELTAKO special A5-12-01 telegram coding used by FWZ12/FWZ14/DSZ14/F3Z14D,
        # FWZ14, FWZ12, F3Z14D, DSZ14DRS, DSZ14WDRS, WSZ14DRS and WSZ14DRSE:
        # DB0 is a fixed telegram type. DB3..DB1 is a 24-bit value.
        if db0 in (0x09, 0x19):
            result.update(
                {
                    "counter": counter,
                    "energy_total": round(counter / 10.0, 1),
                    "is_meter_reading": True,
                    "telegram_type_code": f"0x{db0:02X}",
                    "telegram_type": "energy_normal" if db0 == 0x09 else "energy_night",
                    "tariff": "normal" if db0 == 0x09 else "night",
                }
            )
        elif db0 in (0x0C, 0x1C):
            result.update(
                {
                    "current_power": counter,
                    "is_power_reading": True,
                    "telegram_type_code": f"0x{db0:02X}",
                    "telegram_type": "power_normal" if db0 == 0x0C else "power_night",
                    "tariff": "normal" if db0 == 0x0C else "night",
                }
            )
        elif data_type == 0:
            energy_total = counter / float(10 ** divisor_code)
            result.update(
                {
                    "counter": counter,
                    "energy_total": round(energy_total, 3),
                }
            )
        elif data_type == 1 and learn_flag == 0:
            # Current electricity value in W. Keep learn telegrams out of the
            # power sensor because they may carry zero/identifier data.
            current_power = counter / float(10 ** divisor_code)
            result.update(
                {
                    "current_power": round(current_power, 3),
                    "is_power_reading": True,
                }
            )

        return result

    if eep == "A5-13-01":
        # Weather station / FWS61 / FWG14MS. This EEP uses two telegram
        # families distinguished by DB0 high nibble. the established decoder exposes
        # exactly this split: identifier 0x01 for dawn/temperature/wind/rain
        # and identifier 0x02 for sun west/south/east.
        #
        # Old builds decoded the wrong bytes (temperature from DB1 instead of
        # DB2, wind from DB3 instead of DB1) and missed the identifier. That is
        # why values such as -40 C appeared although the telegram stream was
        # valid.
        if data == bytes((0x00, 0x00, 0xFF, 0x1A)):
            return {
                "value": data.hex("-"),
                "telegram_type": "weather_alarm_placeholder",
                "ignored": True,
            }

        identifier = (db0 & 0xF0) >> 4
        learn_button = (db0 & 0x08) >> 3
        result = {
            "identifier": identifier,
            "learn_button": learn_button,
            "learn": learn_button == 0,
            "value": data.hex("-"),
            "telegram_type": "weather_station",
        }

        if identifier == 0x01:
            dawn_sensor = (db3 / 255.0) * 999.0
            temperature = -40.0 + (db2 / 255.0 * 120.0)
            wind_speed = ((db1 / 255.0) * 70.0) * 3.6
            day_night = (db0 & 0x04) >> 2
            rain_indication = (db0 & 0x02) >> 1
            result.update(
                {
                    "dawn_sensor": round(dawn_sensor, 0),
                    "temperature": round(temperature, 1),
                    "wind_speed": round(wind_speed, 2),
                    "day_night": day_night,
                    "rain_indication": bool(rain_indication),
                    "rain": bool(rain_indication),
                }
            )
        elif identifier == 0x02:
            sun_west = (db3 / 255.0) * 150000.0
            sun_south = (db2 / 255.0) * 150000.0
            sun_east = (db1 / 255.0) * 150000.0
            hemisphere = (db0 & 0x04) >> 2
            result.update(
                {
                    "sun_west": round(sun_west, 0),
                    "sun_south": round(sun_south, 0),
                    "sun_east": round(sun_east, 0),
                    "hemisphere": hemisphere,
                }
            )
        else:
            result["unsupported_weather_identifier"] = identifier

        return result

    if eep == "A5-38-08":
        if db3 == 0x02:
            percent = max(0, min(100, int(db2)))
            state = bool(db0 & 0x01) and percent > 0
            return {
                "brightness": round(percent / 100.0 * 255),
                "dimmer_percent": percent,
                "dimming_speed": int(db1),
                "dimming_value_blocked": bool(db0 & 0x04),
                "state": state,
                "on": state,
                "value": data.hex("-"),
            }
        return {"state": bool(db0 & 0x01), "on": bool(db0 & 0x01), "value": data.hex("-")}

    if eep == "M5-38-08":
        return {"state": bool(db0 & 0x01), "value": data.hex("-")}

    if eep in {"07-3F-7F"}:
        # FRGBW14 / FRGBW71L sends and accepts ELTAKO FUNC=38 command 2
        # dimmer telegrams for normal control/status:
        #   DB3 = 0x02, DB2 = dim value 0..100 %, DB1 = speed,
        #   DB0 bit3 = 1 data telegram, DB0 bit0 = on/off.
        # Decode those first, otherwise HA never sees the actuator state.
        if db3 == 0x02 and (db0 & 0x08):
            percent = max(0, min(100, int(db2)))
            return {
                "brightness": round(percent / 100.0 * 255),
                "dimmer_percent": percent,
                "dimming_speed": db1,
                "state": bool(db0 & 0x01) and percent > 0,
                "on": bool(db0 & 0x01) and percent > 0,
                "value": data.hex("-"),
                "telegram_type": "frgbw_dimmer_status",
            }

        # ELTAKO 07-3F-7F controller telegrams use DB0=0x0F and DB1 as the
        # component command. DB3/DB2 hold a 10-bit dim value. Expose the single
        # component so the light entity can update partial color feedback.
        if db0 == 0x0F:
            raw_10bit = ((db3 & 0x03) << 8) | (db2 & 0xFF)
            value_255 = round(max(0, min(1023, raw_10bit)) / 1023.0 * 255)
            component_map = {0x10: "red", 0x11: "green", 0x12: "blue", 0x13: "white"}
            component = component_map.get(db1, f"command_0x{db1:02X}")
            return {
                "component": component,
                "component_value": value_255,
                "value": data.hex("-"),
                "telegram_type": "frgbw_controller",
            }

        if db0 == 0x0E:
            raw_10bit = ((db3 & 0x03) << 8) | (db2 & 0xFF)
            value_255 = round(max(0, min(1023, raw_10bit)) / 1023.0 * 255)
            component_map = {0x10: "red", 0x11: "green", 0x12: "blue", 0x13: "white"}
            component = component_map.get(db1, f"command_0x{db1:02X}")
            return {
                "component": component,
                "component_value": value_255,
                "value": data.hex("-"),
                "telegram_type": "frgbw_confirmation",
                "confirmation": True,
            }

        return {"value": data.hex("-"), "telegram_type": "frgbw_unknown"}

    return {"value": data.hex("-")}
