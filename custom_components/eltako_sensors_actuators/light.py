from __future__ import annotations

import logging
import colorsys
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, LightEntity
try:
    from homeassistant.components.light import ATTR_EFFECT
except Exception:  # pragma: no cover
    ATTR_EFFECT = "effect"
try:
    from homeassistant.components.light import LightEntityFeature
    _EFFECT_FEATURE = LightEntityFeature.EFFECT
except Exception:  # pragma: no cover
    _EFFECT_FEATURE = 0
try:
    from homeassistant.components.light import ATTR_RGBW_COLOR
except Exception:  # pragma: no cover
    ATTR_RGBW_COLOR = "rgbw_color"
try:
    from homeassistant.components.light import ATTR_RGB_COLOR
except Exception:  # pragma: no cover
    ATTR_RGB_COLOR = "rgb_color"
try:
    from homeassistant.components.light import ATTR_HS_COLOR
except Exception:  # pragma: no cover
    ATTR_HS_COLOR = "hs_color"
try:
    from homeassistant.components.light import ATTR_XY_COLOR
except Exception:  # pragma: no cover
    ATTR_XY_COLOR = "xy_color"
try:
    from homeassistant.components.light import ATTR_COLOR_NAME
except Exception:  # pragma: no cover
    ATTR_COLOR_NAME = "color_name"
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.light import ColorMode
    _ONOFF_MODE = ColorMode.ONOFF
    _BRIGHTNESS_MODE = ColorMode.BRIGHTNESS
    _RGB_MODE = ColorMode.RGB
    _RGBW_MODE = ColorMode.RGBW
except Exception:  # pragma: no cover - older HA compatibility
    _ONOFF_MODE = "onoff"
    _BRIGHTNESS_MODE = "brightness"
    _RGB_MODE = "rgb"
    _RGBW_MODE = "rgbw"

from .actuator_feedback import decode_actuator_feedback
from .const import CONF_DEVICES, DOMAIN
from .entity_base import EltakoYamlEntity, normalize_eep, normalize_platform

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    data = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = data.get(CONF_DEVICES) or []
    entities: list[EltakoLight] = []
    seen_rgbw_keys: set[str] = set()

    for device in devices:
        if not isinstance(device, dict) or normalize_platform(device.get("platform")) != "light":
            continue

        # FRGBW14 is one logical RGBW light in Home Assistant. EEDTOY/old YAML
        # exports may still contain multiple channel-like entries. Collapse those
        # to one visible entity so the HA color wheel controls the whole actuator
        # instead of exposing unusable pseudo channels.
        if _is_rgbw_device(device):
            key = _rgbw_group_key(device)
            if key in seen_rgbw_keys:
                continue
            seen_rgbw_keys.add(key)
            device = _normalize_rgbw_device(device)

        entities.append(EltakoLight(gateway, device))
    _LOGGER.info(
        "ELTAKO light setup entry=%s imported_devices=%s light_entities=%s",
        entry.entry_id,
        len(devices) if isinstance(devices, list) else 0,
        len(entities),
    )
    async_add_entities(entities)



def _device_name(device: dict[str, Any]) -> str:
    return str(device.get("name") or "")


def _is_rgbw_device(device: dict[str, Any]) -> bool:
    eep = normalize_eep(device.get("eep"))
    sender_eep = normalize_eep(device.get("sender_eep"))
    name = _device_name(device).upper()
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    raw_text = " ".join(str(raw.get(k) or "") for k in ("name", "device_type", "comment")).upper()
    return (
        eep in {"07-3F-7F"}
        or sender_eep in {"07-3F-7F"}
        or "FRGBW14" in name
        or "FRGBW71" in name
        or "FRGBW14" in raw_text
        or "FRGBW71" in raw_text
    )


def _rgbw_group_key(device: dict[str, Any]) -> str:
    raw = device.get("raw") if isinstance(device.get("raw"), dict) else {}
    gateway = device.get("gateway") if isinstance(device.get("gateway"), dict) else {}
    gateway_key = f"{gateway.get('id') or ''}:{gateway.get('base_id') or ''}"
    for key in ("base_address", "pct14_address", "address", "entry_address"):
        value = raw.get(key)
        if value not in (None, ""):
            return f"{gateway_key}:rgbw:{value}"
    name = _device_name(device).upper()
    # Strip channel suffixes like " (1/6)" / " (2/6)" and address tails.
    import re
    name = re.sub(r"\s*\((?:\d+)\s*/\s*(?:\d+)\)\s*$", "", name)
    return f"{gateway_key}:rgbw:{str(device.get('id') or device.get('sender_id') or name).upper()}"


def _normalize_rgbw_device(device: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(device)
    raw = normalized.get("raw") if isinstance(normalized.get("raw"), dict) else {}
    name = str(normalized.get("name") or "FRGBW14")
    import re
    name = re.sub(r"\s*\((?:\d+)\s*/\s*(?:\d+)\)\s*$", "", name)
    normalized["name"] = name
    normalized["eep"] = "07-3F-7F"
    # Older generated YAML may still have sender.eep A5-38-08 for older configurations
    # compatibility. For this integration the FRGBW command builder uses the
    # sender address but generates the vendor RGBW profile internally.
    normalized["sender_eep"] = "07-3F-7F"
    raw = dict(raw)
    raw["logical_channels"] = 1
    raw["ha_color_control"] = "rgbw"
    normalized["raw"] = raw
    return normalized


FRGBW_EFFECTS: dict[str, tuple[int, int, int, int]] = {
    "Rot": (255, 0, 0, 0),
    "Gruen": (0, 255, 0, 0),
    "Blau": (0, 0, 255, 0),
    "Weiss": (255, 255, 255, 0),
    "Warmweiss": (255, 180, 80, 80),
    "Gelb": (255, 190, 0, 0),
    "Cyan": (0, 180, 255, 0),
    "Magenta": (255, 0, 180, 0),
}


def _hs_to_rgb_tuple(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        h = float(value[0]) % 360.0
        s = max(0.0, min(100.0, float(value[1]))) / 100.0
        r, g, b = colorsys.hsv_to_rgb(h / 360.0, s, 1.0)
        return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))
    except Exception:
        return None


def _xy_to_rgb_tuple(value: Any) -> tuple[int, int, int] | None:
    """Convert Home Assistant CIE xy color to 8-bit RGB.

    Several HA frontend color actions, especially direct color-picker clicks,
    may call light.turn_on with xy_color instead of rgb_color/rgbw_color.
    The FRGBW71L command path needs an explicit RGBW target, so xy_color must
    be normalized before telegram generation.
    """
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        x = float(value[0])
        y = float(value[1])
        if y <= 0.0:
            return None

        # Use a fixed luminance for the chromaticity conversion. HA brightness
        # is applied separately later, so this conversion deliberately computes
        # the full-intensity base color.
        Y = 1.0
        X = (Y / y) * x
        Z = (Y / y) * (1.0 - x - y)

        # sRGB D65 conversion matrix.
        r = X * 3.2406 + Y * -1.5372 + Z * -0.4986
        g = X * -0.9689 + Y * 1.8758 + Z * 0.0415
        b = X * 0.0557 + Y * -0.2040 + Z * 1.0570

        def gamma(channel: float) -> float:
            channel = max(0.0, channel)
            if channel <= 0.0031308:
                return 12.92 * channel
            return 1.055 * (channel ** (1.0 / 2.4)) - 0.055

        rgb = [gamma(r), gamma(g), gamma(b)]
        max_channel = max(rgb)
        if max_channel <= 0.0:
            return None
        # Normalize because the separate HA brightness controls intensity.
        rgb = [channel / max_channel for channel in rgb]
        return tuple(max(0, min(255, int(round(channel * 255)))) for channel in rgb)  # type: ignore[return-value]
    except Exception:
        return None


_COLOR_NAME_RGB: dict[str, tuple[int, int, int]] = {
    "red": (255, 0, 0),
    "rot": (255, 0, 0),
    "green": (0, 255, 0),
    "gruen": (0, 255, 0),
    "grün": (0, 255, 0),
    "blue": (0, 0, 255),
    "blau": (0, 0, 255),
    "white": (255, 255, 255),
    "weiss": (255, 255, 255),
    "weiß": (255, 255, 255),
    "yellow": (255, 255, 0),
    "gelb": (255, 255, 0),
    "cyan": (0, 255, 255),
    "magenta": (255, 0, 255),
    "purple": (128, 0, 255),
    "violet": (128, 0, 255),
    "orange": (255, 128, 0),
}


def _color_name_to_rgb_tuple(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    return _COLOR_NAME_RGB.get(value.strip().lower())


def _clamp_u8(value: Any, default: int = 0) -> int:
    try:
        return max(0, min(255, int(round(float(value)))))
    except Exception:
        return default


def _rgbw_from_kwargs(kwargs: dict[str, Any]) -> tuple[int, int, int, int] | None:
    """Return an unscaled RGBW target from HA turn_on kwargs.

    Home Assistant sends the chosen color and brightness as separate concepts.
    FRGBW71L must therefore keep an internal base color and only apply
    brightness at the final telegram-building step. This avoids carrying old
    channel values over when changing from e.g. red to green.
    """
    rgbw = kwargs.get(ATTR_RGBW_COLOR)
    if isinstance(rgbw, (list, tuple)) and len(rgbw) >= 4:
        return tuple(_clamp_u8(x) for x in rgbw[:4])  # type: ignore[return-value]

    rgb = kwargs.get(ATTR_RGB_COLOR)
    if isinstance(rgb, (list, tuple)) and len(rgb) >= 3:
        return (_clamp_u8(rgb[0]), _clamp_u8(rgb[1]), _clamp_u8(rgb[2]), 0)

    converted = _hs_to_rgb_tuple(kwargs.get(ATTR_HS_COLOR))
    if converted is not None:
        return (converted[0], converted[1], converted[2], 0)

    converted = _xy_to_rgb_tuple(kwargs.get(ATTR_XY_COLOR))
    if converted is not None:
        return (converted[0], converted[1], converted[2], 0)

    converted = _color_name_to_rgb_tuple(kwargs.get(ATTR_COLOR_NAME))
    if converted is not None:
        return (converted[0], converted[1], converted[2], 0)

    return None


def _apply_brightness_to_rgbw(rgbw: tuple[int, int, int, int], brightness: int) -> tuple[int, int, int, int]:
    factor = _clamp_u8(brightness, 255) / 255.0
    return tuple(_clamp_u8(channel * factor) for channel in rgbw)  # type: ignore[return-value]


class EltakoLight(EltakoYamlEntity, LightEntity):
    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device)
        self._is_on = None
        self._brightness = None
        # Last visible/scaled color reported to Home Assistant.
        self._rgbw_color = None
        # FRGBW71L base color at 100% brightness. Kept separate from
        # brightness so brightness-only calls do not create new colors and
        # color changes always replace all four channels.
        self._frgbw_base_rgbw: tuple[int, int, int, int] | None = None
        self._effect = None
        eep = normalize_eep(device.get("eep"))
        if _is_rgbw_device(device):
            # v0.1.86: FRGBW14 and FRGBW71L share the 07-3F-7F runtime color
            # path. FRGBW71L learns by free-profile radio teach-in; FRGBW14
            # uses the sender.id from YAML/PCT14 on the Series-14 bus. Home Assistant is exposed as RGB
            # light because GFA5 represents white as R=G=B=100%, not as command
            # 0x13.
            self._attr_supported_color_modes = {_RGB_MODE}
            self._attr_color_mode = _RGB_MODE
        elif eep == "A5-38-08":
            self._attr_supported_color_modes = {_BRIGHTNESS_MODE}
            self._attr_color_mode = _BRIGHTNESS_MODE
        else:
            self._attr_supported_color_modes = {_ONOFF_MODE}
            self._attr_color_mode = _ONOFF_MODE
        self._remove_listener = gateway.register_listener(self._handle_telegram)

    @property
    def is_on(self):
        return self._is_on

    @property
    def brightness(self):
        return self._brightness

    @property
    def rgbw_color(self):
        return self._rgbw_color

    @property
    def rgb_color(self):
        if self._rgbw_color is None:
            return None
        return tuple(self._rgbw_color[:3])

    @property
    def effect(self):
        return self._effect

    def _handle_telegram(self, telegram) -> None:
        feedback = decode_actuator_feedback(
            self.device_config, telegram.decoded, telegram.sender_id
        )
        if feedback is None:
            return
        if "rgbw_color" in feedback:
            self._rgbw_color = tuple(feedback["rgbw_color"])
        if "component" in feedback and "component_value" in feedback:
            r, g, b, w = self._rgbw_color or (0, 0, 0, 0)
            component = feedback.get("component")
            value = int(feedback.get("component_value") or 0)
            if component == "red":
                r = value
            elif component == "green":
                g = value
            elif component == "blue":
                b = value
            elif component == "white":
                w = value
            self._rgbw_color = (r, g, b, w)
            if _is_rgbw_device(self.device_config):
                max_channel = max(r, g, b, w)
                self._is_on = max_channel > 0
                self._brightness = max_channel if self._is_on else 0
                self.schedule_update_ha_state()
                return
        if "brightness" in feedback:
            self._brightness = int(feedback["brightness"])
            self._is_on = bool(self._brightness)
        elif "state" in feedback:
            self._is_on = bool(feedback["state"])
        elif "on" in feedback:
            self._is_on = bool(feedback["on"])
        else:
            return
        self.schedule_update_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_send_or_raise("turn_on", **kwargs)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_send_or_raise("turn_off", **kwargs)

    async def _async_send_or_raise(self, command: str, **kwargs: Any) -> None:
        frgbw_target_base: tuple[int, int, int, int] | None = None
        frgbw_target_visible: tuple[int, int, int, int] | None = None

        if command == "turn_on" and _is_rgbw_device(self.device_config):
            self._effect = None
            explicit_color = _rgbw_from_kwargs(kwargs)
            brightness = _clamp_u8(kwargs.get(ATTR_BRIGHTNESS), self._brightness if self._brightness is not None else 255)

            if explicit_color is not None:
                frgbw_target_base = explicit_color
                self._frgbw_base_rgbw = frgbw_target_base
            elif ATTR_BRIGHTNESS in kwargs and self._frgbw_base_rgbw is not None:
                frgbw_target_base = self._frgbw_base_rgbw
            elif ATTR_BRIGHTNESS in kwargs and self._rgbw_color is not None:
                # Reconstruct an approximate full-brightness base from the last
                # visible color, then apply the new brightness. This keeps a
                # brightness-only service call from becoming an A5-38-08 dim
                # command, which was shown to alter color.
                current_brightness = max(1, self._brightness or max(self._rgbw_color[:3]) or 255)
                factor = 255.0 / current_brightness
                frgbw_target_base = tuple(_clamp_u8(channel * factor) for channel in self._rgbw_color)  # type: ignore[assignment]
                self._frgbw_base_rgbw = frgbw_target_base
            else:
                frgbw_target_base = None

            if frgbw_target_base is not None:
                frgbw_target_visible = _apply_brightness_to_rgbw(frgbw_target_base, brightness)
                kwargs = {ATTR_RGBW_COLOR: frgbw_target_base, ATTR_BRIGHTNESS: brightness}
            else:
                # Plain ON without color/brightness remains the verified A5 ON
                # command. Color clicks and brightness changes use the GFA5 RGB
                # path instead.
                kwargs = {}

        ok = await self.gateway.async_send_actuator_command(self.device_config, command, **kwargs)
        if not ok:
            detail = getattr(self.gateway, "last_send_error", None)
            suffix = f" Technischer Fehler: {detail}" if detail else ""
            raise HomeAssistantError(
                "ELTAKO-Telegramm konnte nicht gesendet werden. Pruefe Gateway-Port, sender.id/sender.eep im YAML und ob der Aktor die Sender-ID angelernt hat."
                + suffix
            )
        if command == "turn_on":
            self._is_on = True
            if _is_rgbw_device(self.device_config):
                if ATTR_BRIGHTNESS in kwargs:
                    self._brightness = _clamp_u8(kwargs[ATTR_BRIGHTNESS], 255)
                elif self._brightness is None:
                    self._brightness = 255
            elif ATTR_BRIGHTNESS in kwargs:
                self._brightness = _clamp_u8(kwargs[ATTR_BRIGHTNESS], 255)
            elif self._brightness is None and self._attr_color_mode in (_BRIGHTNESS_MODE, _RGBW_MODE):
                self._brightness = 255

            if frgbw_target_base is not None:
                self._frgbw_base_rgbw = frgbw_target_base
                self._rgbw_color = frgbw_target_visible or _apply_brightness_to_rgbw(
                    frgbw_target_base, self._brightness if self._brightness is not None else 255
                )
            elif ATTR_RGBW_COLOR in kwargs:
                self._rgbw_color = tuple(kwargs[ATTR_RGBW_COLOR])
            elif ATTR_RGB_COLOR in kwargs:
                rgb = tuple(kwargs[ATTR_RGB_COLOR])
                self._rgbw_color = (rgb[0], rgb[1], rgb[2], 0)
            elif ATTR_HS_COLOR in kwargs:
                rgb = _hs_to_rgb_tuple(kwargs.get(ATTR_HS_COLOR))
                if rgb is not None:
                    self._rgbw_color = (rgb[0], rgb[1], rgb[2], 0)
            elif ATTR_XY_COLOR in kwargs:
                rgb = _xy_to_rgb_tuple(kwargs.get(ATTR_XY_COLOR))
                if rgb is not None:
                    self._rgbw_color = (rgb[0], rgb[1], rgb[2], 0)
            elif ATTR_COLOR_NAME in kwargs:
                rgb = _color_name_to_rgb_tuple(kwargs.get(ATTR_COLOR_NAME))
                if rgb is not None:
                    self._rgbw_color = (rgb[0], rgb[1], rgb[2], 0)
        elif command == "turn_off":
            self._is_on = False
            if _is_rgbw_device(self.device_config):
                self._brightness = 0
            elif self._attr_color_mode in (_BRIGHTNESS_MODE, _RGB_MODE, _RGBW_MODE):
                self._brightness = 0
        self.schedule_update_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener:
            self._remove_listener()
