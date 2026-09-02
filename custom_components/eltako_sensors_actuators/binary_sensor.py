from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.helpers.event import async_call_later

from .const import CONF_DEVICES, DOMAIN
from .diagnostics import diagnostic_event
from .bus.eep_ffg7b import enrich_ffg7b_decoded
from .entity_base import EltakoBaseEntity, EltakoGatewayEntity, EltakoYamlEntity, _f4usm61b_mode, _futh55ed_mode, _is_f4usm61b_device, _is_futh55ed_device, _is_ffg7b_device, _is_frwb_device, _is_fts14em_device, _fts14em_inverted, normalize_eep, normalize_platform

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = data.get(CONF_DEVICES) or []

    entities: list[BinarySensorEntity] = _gateway_binary_entities(gateway)

    for device in devices:
        if not isinstance(device, dict):
            continue
        platform = normalize_platform(device.get("platform"))
        eep = normalize_eep(device.get("eep"))

        if _is_fts14em_device(device) and eep == "F6-02-01":
            entities.append(EltakoFTS14EMInputBinarySensor(gateway, device))
            continue

        if _is_f4usm61b_device(device):
            mode = _f4usm61b_mode(device)
            if mode == 1 and eep == "F6-02-01":
                # One sender (Base-ID+1), four inputs:
                # E1=0x70, E2=0x50, E3=0x30, E4=0x10, release=0x00.
                entities.extend(
                    _f4usm61b_input_entities(
                        gateway,
                        device,
                        ((1, 0x70), (2, 0x50), (3, 0x30), (4, 0x10)),
                    )
                )
            elif mode == 5 and eep == "F6-02-01":
                # Two senders. Channel 1 represents E1/E2, channel 2 E3/E4.
                channel = _f4usm61b_channel_number(device)
                if channel == 1:
                    inputs = ((1, 0x70), (2, 0x50))
                elif channel == 2:
                    inputs = ((3, 0x70), (4, 0x50))
                else:
                    inputs = ()
                    _LOGGER.warning(
                        "F4USM61B mode 5 channel cannot be determined for id=%s name=%s",
                        device.get("id"),
                        device.get("name"),
                    )
                entities.extend(_f4usm61b_input_entities(gateway, device, inputs))
            elif mode == 2 and eep == "A5-38-08":
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "state",
                        BinarySensorDeviceClass.POWER,
                        suffix="Schaltzustand",
                    )
                )
            elif mode in {3, 6} and eep == "A5-08-01":
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "movement",
                        BinarySensorDeviceClass.MOTION,
                        suffix="Bewegung",
                    )
                )
            elif mode in {4, 7} and eep == "D5-00-01":
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "open",
                        BinarySensorDeviceClass.WINDOW,
                        suffix="Fenster",
                    )
                )
            elif mode == 8 and eep == "A5-07-01":
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "movement",
                        BinarySensorDeviceClass.OCCUPANCY,
                        suffix="Belegung",
                    )
                )
            else:
                _LOGGER.warning(
                    "Unsupported F4USM61B combination mode=%s eep=%s id=%s",
                    mode,
                    eep,
                    device.get("id"),
                )
            continue

        if _is_futh55ed_device(device):
            mode = _futh55ed_mode(device)
            if mode == "two_point" and eep == "A5-38-08":
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "state",
                        None,
                        suffix="Heizanforderung",
                    )
                )
            elif mode == "fhk" and eep == "A5-10-06":
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "frost_protection",
                        None,
                        suffix="Frostschutz",
                    )
                )
            elif mode == "fks_kp" and eep == "A5-20-01":
                entities.append(EltakoYamlBinarySensor(gateway, device, "summer_mode", None, suffix="Sommerbetrieb"))
            continue

        if _is_ffg7b_device(device):
            # Both open and tilted mean the window is not fully closed. The
            # enum sensor on the sensor platform preserves the exact position.
            entities.append(
                EltakoYamlBinarySensor(
                    gateway,
                    device,
                    "open",
                    BinarySensorDeviceClass.WINDOW,
                    suffix="Fenster offen",
                )
            )
            continue

        if eep == "A5-30-03":
            if _is_frwb_device(device):
                # FRWB: DB1 0x0F = Rauchalarm, DB1 0x1F = kein Alarm.
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "smoke_alarm",
                        BinarySensorDeviceClass.SMOKE,
                        suffix="Rauchalarm",
                    )
                )
            else:
                # FSM60B Betriebsart 3: ausschließlich Wasseralarm.
                entities.append(
                    EltakoYamlBinarySensor(
                        gateway,
                        device,
                        "moisture",
                        BinarySensorDeviceClass.MOISTURE,
                        suffix="Wasseralarm",
                    )
                )
        elif eep == "A5-30-01":
            # FSM60B Betriebsart 4: ausschließlich Kontakteingang.
            entities.append(
                EltakoYamlBinarySensor(
                    gateway,
                    device,
                    "open",
                    BinarySensorDeviceClass.OPENING,
                    suffix="Kontakt offen",
                )
            )
        elif eep in ("A5-07-01", "A5-08-01") and platform in ("sensor", "binary_sensor"):
            # FBH/FBHT uses one telegram for the physical movement state in both
            # FBH mode (A5-08-01) and TF mode (A5-07-01). Do not route these
            # profiles through the generic binary-sensor key "pressed".
            entities.append(EltakoYamlBinarySensor(gateway, device, "movement", BinarySensorDeviceClass.MOTION, suffix="Bewegung"))
        elif eep == "F6-01-01" and platform == "binary_sensor":
            # FNSN55EB/FNS65EB: expose the documented proximity state directly.
            # EEDTOY currently exports device_class: presence. Home Assistant
            # versions without a PRESENCE enum fall back to OCCUPANCY.
            presence_class = _device_class_from_yaml(device.get("device_class"))
            if presence_class is None:
                presence_class = getattr(BinarySensorDeviceClass, "PRESENCE", BinarySensorDeviceClass.OCCUPANCY)
            fnsn_entity = EltakoYamlBinarySensor(
                gateway,
                device,
                "presence",
                presence_class,
                suffix="Näherung",
            )
            # Custom state labels override Home Assistant's generic presence
            # wording (Zuhause/Abwesend) for this proximity detector.
            fnsn_entity._attr_translation_key = "fnsn_detection"
            entities.append(fnsn_entity)
        elif platform == "binary_sensor":
            device_class = _device_class_from_yaml(device.get("device_class")) or _device_class_for_eep(eep)
            key = "open" if device_class in (BinarySensorDeviceClass.DOOR, BinarySensorDeviceClass.WINDOW, BinarySensorDeviceClass.OPENING) else "pressed"
            entities.append(EltakoYamlBinarySensor(gateway, device, key, device_class))
            if eep in ("F6-02-01",):
                entities.extend(_rocker_position_entities(gateway, device))
        elif platform == "sensor" and eep == "A5-13-01":
            entities.append(EltakoYamlBinarySensor(gateway, device, "rain", BinarySensorDeviceClass.MOISTURE, suffix="Regen"))
        elif eep == "A5-20-01":
            entities.extend(_a5_20_01_status_entities(gateway, device))

    if not devices and not entities:
        entities.extend(
            [
                EltakoBinaryValueSensor(gateway, "debug", "Last Movement", "movement", BinarySensorDeviceClass.MOTION),
                EltakoBinaryValueSensor(gateway, "debug", "Last Contact", "open", BinarySensorDeviceClass.DOOR),
            ]
        )

    _LOGGER.info(
        "ELTAKO binary_sensor setup entry=%s imported_devices=%s binary_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)



def _a5_20_01_status_entities(gateway, device: dict[str, Any]) -> list[BinarySensorEntity]:
    return [
        EltakoYamlBinarySensor(gateway, device, "battery_low", BinarySensorDeviceClass.BATTERY, suffix="Batterie niedrig"),
        EltakoYamlBinarySensor(gateway, device, "window_open", BinarySensorDeviceClass.WINDOW, suffix="Fenster offen"),
        EltakoYamlBinarySensor(gateway, device, "contact_open", BinarySensorDeviceClass.OPENING, suffix="Kontakt offen"),
        EltakoYamlBinarySensor(gateway, device, "actuator_obstructed", BinarySensorDeviceClass.PROBLEM, suffix="Ventil blockiert"),
        EltakoYamlBinarySensor(gateway, device, "temperature_sensor_failure", BinarySensorDeviceClass.PROBLEM, suffix="Temperaturfehler"),
    ]

def _gateway_binary_entities(gateway) -> list[BinarySensorEntity]:
    return [
        EltakoGatewayBinarySensor(gateway, "Connected", "connected", BinarySensorDeviceClass.CONNECTIVITY),
        EltakoGatewayBinarySensor(gateway, "Auto Connect Enabled", "auto_connect_enabled", None),
    ]


class EltakoGatewayBinarySensor(EltakoGatewayEntity, BinarySensorEntity):
    def __init__(self, gateway, name: str, key: str, device_class: BinarySensorDeviceClass | None) -> None:
        super().__init__(gateway, name, key)
        self.key = key
        self._attr_device_class = device_class
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        if self.key == "connected":
            return self.gateway.is_connected
        if self.key == "auto_connect_enabled":
            return bool(getattr(self.gateway, "auto_connect_enabled", True))
        return None

    def _handle_telegram(self, telegram) -> None:
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()



ROCKER_POSITION_LABELS = {
    "left_top": "Taste oben links",
    "right_top": "Taste oben rechts",
    "left_bottom": "Taste unten links",
    "right_bottom": "Taste unten rechts",
}

ROCKER_ACTIVE_TIME_SECONDS = 0.7


def _f4usm61b_channel_number(device: dict[str, Any]) -> int | None:
    """Return the EEDTOY channel number for a F4USM61B YAML row."""
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    for key in ("channel", "channel_number", "channel_index"):
        value = device.get(key, raw.get(key))
        try:
            channel = int(value)
        except (TypeError, ValueError):
            continue
        if channel in {1, 2}:
            return channel

    text = " ".join(str(value or "") for value in (device.get("name"), raw.get("name"))).lower()
    if "kanal 1" in text or "channel 1" in text:
        return 1
    if "kanal 2" in text or "channel 2" in text:
        return 2
    return None


def _f4usm61b_input_entities(
    gateway,
    device: dict[str, Any],
    inputs: tuple[tuple[int, int], ...],
) -> list[BinarySensorEntity]:
    return [
        EltakoF4USM61BInputBinarySensor(gateway, device, input_number, telegram_code)
        for input_number, telegram_code in inputs
    ]


def _rocker_position_entities(gateway, device: dict[str, Any]) -> list[BinarySensorEntity]:
    return [
        EltakoRockerPositionBinarySensor(gateway, device, position, label)
        for position, label in ROCKER_POSITION_LABELS.items()
    ]

def _device_class_from_yaml(value: Any) -> BinarySensorDeviceClass | None:
    """Return a Home Assistant binary-sensor device class from YAML.

    EEDTOY can export device_class for manually added devices.  Prefer the
    explicit YAML value over the EEP fallback so FTK/FTKE can be window/door
    as selected and special profiles such as FSM60B BA3 can be moisture.
    """
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    try:
        return BinarySensorDeviceClass(text)
    except ValueError:
        return getattr(BinarySensorDeviceClass, text.upper(), None)


def _device_class_for_eep(eep: str) -> BinarySensorDeviceClass | None:
    if eep == "F6-10-00":
        return BinarySensorDeviceClass.DOOR
    if eep == "D5-00-01":
        return BinarySensorDeviceClass.DOOR
    if eep == "F6-01-01":
        return getattr(BinarySensorDeviceClass, "PRESENCE", BinarySensorDeviceClass.OCCUPANCY)
    if eep in ("F6-02-01",):
        return None
    return None



class EltakoFTS14EMInputBinarySensor(EltakoYamlEntity, BinarySensorEntity):
    """One binary entity for one FTS14EM bus ID/input."""

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        input_number = device.get("input_number")
        if input_number is None and isinstance(device.get("raw"), dict):
            input_number = device["raw"].get("input_number")
        try:
            entity_name = f"E{int(input_number)}"
        except (TypeError, ValueError):
            entity_name = str(device.get("name") or "Eingang")
        super().__init__(gateway, device, name=entity_name)
        self._state = None
        self._inverted = _fts14em_inverted(device)
        self._attr_device_class = _device_class_from_yaml(device.get("device_class"))
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        return self._state

    @property
    def extra_state_attributes(self):
        attrs = dict(super().extra_state_attributes or {})
        raw = self.device_config.get("raw") if isinstance(self.device_config.get("raw"), dict) else {}
        attrs.update({
            "input_number": self.device_config.get("input_number", raw.get("input_number")),
            "operating_mode": self.device_config.get("operating_mode", raw.get("operating_mode", "UT")),
            "id_range": self.device_config.get("id_range", raw.get("id_range")),
            "base_id": self.device_config.get("base_id", raw.get("base_id")),
            "inverted": self._inverted,
        })
        return attrs

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return
        if "pressed" not in telegram.decoded:
            return
        active = bool(telegram.decoded["pressed"])
        self._state = not active if self._inverted else active
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()

class EltakoYamlBinarySensor(EltakoYamlEntity, BinarySensorEntity):
    def __init__(
        self,
        gateway,
        device: dict[str, Any],
        key: str,
        device_class: BinarySensorDeviceClass | None,
        suffix: str | None = None,
        inverted: bool = False,
    ) -> None:
        super().__init__(gateway, device, suffix=suffix)
        self.key = key
        self._inverted = bool(inverted)
        self._state = None
        self._attr_device_class = device_class
        self._mode8_reset_task: asyncio.Task | None = None
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        return self._state

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return

        # F4USM61B mode 8 (A5-07-01) sends while E1/E3 is occupied but no
        # separate clear telegram. Each channel entity owns an independent
        # watchdog. A new matching telegram restarts only that entity's timer.
        if (
            _is_f4usm61b_device(self.device_config)
            and _f4usm61b_mode(self.device_config) == 8
            and self.key == "movement"
        ):
            self._state = True
            self.async_write_ha_state()

            if self._mode8_reset_task is not None and not self._mode8_reset_task.done():
                self._mode8_reset_task.cancel()
                event_type = "occupancy_reset_restarted"
            else:
                event_type = "occupancy_reset_scheduled"

            diagnostic_event(
                self.hass,
                event_type,
                level="debug",
                gateway=getattr(self.gateway, "gateway_type", None),
                device_id=self.device_config.get("id"),
                device_name=self.device_config.get("name"),
                operating_mode=8,
                delay_seconds=65,
            )

            async def _reset_mode8() -> None:
                try:
                    await asyncio.sleep(65)
                except asyncio.CancelledError:
                    return
                self._mode8_reset_task = None
                self._state = False
                self.async_write_ha_state()
                diagnostic_event(
                    self.hass,
                    "occupancy_reset_completed",
                    level="info",
                    gateway=getattr(self.gateway, "gateway_type", None),
                    device_id=self.device_config.get("id"),
                    device_name=self.device_config.get("name"),
                    operating_mode=8,
                    state="frei",
                )

            self._mode8_reset_task = self.hass.async_create_task(
                _reset_mode8(),
                name=f"eltako_f4usm61b_mode8_reset_{self.device_config.get('id', 'unknown')}",
            )
            return

        if _is_ffg7b_device(self.device_config):
            enrich_ffg7b_decoded(telegram.decoded)
        if self.key not in telegram.decoded:
            return
        state = bool(telegram.decoded[self.key])

        # F4USM61B modes 3, 4, 6 and 7 are decoded exclusively from
        # operating_mode and the measured telegram values.  A generic
        # ``inverted`` flag is intentionally ignored for this device family.
        if _is_f4usm61b_device(self.device_config):
            mode = _f4usm61b_mode(self.device_config)

            if mode in {3, 6} and self.key == "movement":
                raw_state = telegram.decoded.get("motion_raw")
                try:
                    if isinstance(raw_state, str):
                        raw_state = int(raw_state, 16)
                    elif raw_state is not None:
                        raw_state = int(raw_state)
                except (TypeError, ValueError):
                    raw_state = None

                if raw_state == 0x0D:
                    # The F4USM61B already inverts the transmitted telegram in
                    # mode 6. Therefore both mode 3 and mode 6 use the same raw
                    # EEP mapping: 0x0D means movement, 0x0F means no movement.
                    state = True
                elif raw_state == 0x0F:
                    state = False
                else:
                    _LOGGER.debug(
                        "Ignoring unsupported F4USM61B motion value mode=%s raw=%r id=%s",
                        mode,
                        raw_state,
                        self.device_config.get("id"),
                    )
                    return

            elif mode in {4, 7} and self.key == "open":
                raw_state = telegram.decoded.get("contact_raw")
                try:
                    if isinstance(raw_state, str):
                        raw_state = int(raw_state, 16)
                    elif raw_state is not None:
                        raw_state = int(raw_state)
                except (TypeError, ValueError):
                    raw_state = None

                if raw_state == 0x08:
                    # Mode 4: input idle = open. Mode 7: input active = open.
                    # Both produce the HA state "open" for telegram 0x08.
                    state = True
                elif raw_state == 0x09:
                    # Mode 4: input active = closed. Mode 7: input idle = closed.
                    state = False
                else:
                    _LOGGER.debug(
                        "Ignoring unsupported F4USM61B contact value mode=%s raw=%r id=%s",
                        mode,
                        raw_state,
                        self.device_config.get("id"),
                    )
                    return
        elif self._inverted:
            state = not state

        self._state = state
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._mode8_reset_task is not None and not self._mode8_reset_task.done():
            self._mode8_reset_task.cancel()
            self._mode8_reset_task = None
        if self._remove_listener:
            self._remove_listener()


class EltakoBinaryValueSensor(EltakoBaseEntity, BinarySensorEntity):
    def __init__(self, gateway, sender_id: str, name: str, key: str, device_class: BinarySensorDeviceClass | None) -> None:
        super().__init__(gateway, sender_id, name)
        self.key = key
        self._state = None
        self._attr_device_class = device_class
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        return self._state

    def _handle_telegram(self, telegram) -> None:
        if self.key not in telegram.decoded:
            return
        self._state = bool(telegram.decoded[self.key])
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()


class EltakoF4USM61BInputBinarySensor(EltakoYamlEntity, BinarySensorEntity):
    """Momentary input entity for F4USM61B operating modes 1 and 5."""

    def __init__(
        self,
        gateway,
        device: dict[str, Any],
        input_number: int,
        telegram_code: int,
    ) -> None:
        super().__init__(gateway, device, suffix=f"Eingang E{input_number}")
        self._telegram_code = int(telegram_code)
        self._state = False
        self._attr_device_class = None
        self._attr_icon = "mdi:gesture-tap-button"
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        return self._state

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return
        value = telegram.decoded.get("button_action")
        if value is None:
            return
        try:
            value = int(value)
        except (TypeError, ValueError):
            return

        if value == 0x00:
            new_state = False
        elif value == self._telegram_code:
            new_state = True
        else:
            # A different input of the same sender was pressed.
            new_state = False

        if new_state == self._state:
            return
        self._state = new_state
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()


class EltakoRockerPositionBinarySensor(EltakoYamlEntity, BinarySensorEntity):
    """Momentary binary sensor for one physical position of an ELTAKO rocker button."""

    def __init__(self, gateway, device: dict[str, Any], position: str, label: str) -> None:
        super().__init__(gateway, device, suffix=label)
        self.position = position
        self._state = False
        self._reset_handle = None
        self._attr_device_class = None
        self._attr_icon = "mdi:gesture-tap-button"
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        return self._state

    def _handle_telegram(self, telegram) -> None:
        if str(telegram.sender_id).upper() != str(self.device_config.get("id")).upper():
            return

        position = telegram.decoded.get("button_position")
        if not position:
            return

        if position == self.position and bool(telegram.decoded.get("pressed", False)):
            self._state = True
            self.schedule_update_ha_state()
            self._schedule_reset()
            return

        # A different button on the same rocker was pressed. Clear this one
        # immediately so the visual state is unambiguous.
        if position in ROCKER_POSITION_LABELS and self._state:
            self._cancel_reset()
            self._state = False
            self.schedule_update_ha_state()

    def _schedule_reset(self) -> None:
        self._cancel_reset()

        def _reset(_now) -> None:
            self._reset_handle = None
            if self._state:
                self._state = False
                self.schedule_update_ha_state()

        self._reset_handle = async_call_later(self.hass, ROCKER_ACTIVE_TIME_SECONDS, _reset)

    def _cancel_reset(self) -> None:
        if self._reset_handle is not None:
            self._reset_handle()
            self._reset_handle = None

    async def async_will_remove_from_hass(self) -> None:
        self._cancel_reset()
        if self._remove_listener:
            self._remove_listener()
