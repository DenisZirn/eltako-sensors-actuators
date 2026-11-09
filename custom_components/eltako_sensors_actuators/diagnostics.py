from __future__ import annotations

from collections import deque
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import CONF_DIAGNOSTICS_ENABLED, DOMAIN

_LOGGER = logging.getLogger(__name__)

DATA_DIAGNOSTICS = f"{DOMAIN}_diagnostics"
PANEL_URL_PATH = "eltako-diagnostics"
PANEL_NAME = "eltako-diagnostics-panel"
# Register the *directory*, not a fake versioned filename: this guarantees
# that an actual frontend/diagnostics-panel.js is served from a stable path.
# Cache-bust only the browser's ES module request via the query string.
STATIC_BASE_URL = "/eltako_sensors_actuators_static"
STATIC_URL = f"{STATIC_BASE_URL}/diagnostics-panel.js"
PANEL_MODULE_URL = f"{STATIC_URL}?v=0.1.166"
MAX_EVENTS = 1000


class DiagnosticStore:
    """Bounded in-memory diagnostic event store."""

    def __init__(self, max_events: int = MAX_EVENTS) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._sequence = 0

    def add(self, event_type: str, *, level: str = "info", **data: Any) -> dict[str, Any]:
        self._sequence += 1
        event = {
            "sequence": self._sequence,
            "timestamp": dt_util.now().isoformat(timespec="milliseconds"),
            "type": str(event_type),
            "level": str(level),
            **{key: _json_value(value) for key, value in data.items()},
        }
        self._events.append(event)
        return event

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return value.hex("-").upper()
    if isinstance(value, dict):
        return {str(k): _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(v) for v in value]
    return str(value)


def get_store(hass: HomeAssistant) -> DiagnosticStore:
    domain_data = hass.data.setdefault(DATA_DIAGNOSTICS, {})
    store = domain_data.get("store")
    if not isinstance(store, DiagnosticStore):
        store = DiagnosticStore()
        domain_data["store"] = store
    return store


def diagnostics_enabled(hass: HomeAssistant) -> bool:
    domain_data = hass.data.setdefault(DATA_DIAGNOSTICS, {})
    return bool(domain_data.get("enabled", False))


def diagnostic_event(hass: HomeAssistant, event_type: str, *, level: str = "info", **data: Any) -> None:
    if not diagnostics_enabled(hass):
        return
    if event_type == "telegram_received" and isinstance(data.get("decoded"), dict):
        data["decoded"] = _diagnostic_decoded(data["decoded"])
    get_store(hass).add(event_type, level=level, **data)


def _diagnostic_decoded(decoded: dict[str, Any]) -> dict[str, Any]:
    """Return a compact, ordered decoded payload for the panel."""
    preferred = (
        "device_name", "telegram_type", "state", "data_hex", "value", "org",
        "physical_sender_id", "logical_sender_id", "detected_eep",
        "learn", "learn_telegram", "data_telegram",
        "open", "closed", "tilted", "window_state",
        "movement", "movement_detection_mode",
        "moisture", "wet", "water_alarm", "smoke_alarm", "alarm",
        "temperature", "target_temperature", "humidity", "brightness",
        "voltage", "battery_voltage", "battery_percentage", "battery_low",
        "rain", "wind_speed", "dawn", "sun_west", "sun_south", "sun_east",
        "energy_total", "current_power", "tariff", "measurement_channel",
        "valve_position", "service_on", "window_open", "actuator_obstructed",
        "error", "ignored",
    )
    result: dict[str, Any] = {}
    for key in preferred:
        if key in decoded:
            result[key] = decoded[key]
    for key, value in decoded.items():
        if key not in result and key not in {"raw", "last_seen", "pressed", "button_action", "signal_code_decimal"}:
            result[key] = value
    return result


@websocket_api.websocket_command({vol.Required("type"): "eltako_sensors_actuators/diagnostics/get"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_get_diagnostics(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    connection.send_result(msg["id"], {"events": get_store(hass).snapshot(), "max_events": MAX_EVENTS})


@websocket_api.websocket_command({vol.Required("type"): "eltako_sensors_actuators/diagnostics/clear"})
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_clear_diagnostics(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    get_store(hass).clear()
    diagnostic_event(hass, "diagnostics_cleared", level="info")
    connection.send_result(msg["id"], {"cleared": True})


async def _async_ensure_diagnostics_static_path(hass: HomeAssistant) -> bool:
    """Serve frontend assets as a directory via the documented HA HTTP API.

    Keep the static URL independent from offline build versions. A version is
    attached only to the panel module request so browsers refresh the module.
    The method is idempotent for repeated options-flow/reload calls.
    """
    domain_data = hass.data.setdefault(DATA_DIAGNOSTICS, {})
    if domain_data.get("static_path_registered"):
        return True

    frontend_dir = Path(__file__).parent / "frontend"
    panel_file = frontend_dir / "diagnostics-panel.js"
    if not panel_file.is_file():
        _LOGGER.error(
            "ELTAKO diagnostics panel not registered: missing asset %s. "
            "Please copy the complete frontend/ subfolder from the test ZIP.",
            panel_file,
        )
        return False

    try:
        await hass.http.async_register_static_paths([
            StaticPathConfig(STATIC_BASE_URL, str(frontend_dir), False),
        ])
    except Exception:
        _LOGGER.exception(
            "ELTAKO diagnostics static directory registration failed: url=%s dir=%s",
            STATIC_BASE_URL,
            frontend_dir,
        )
        return False

    domain_data["static_path_registered"] = True
    _LOGGER.info("ELTAKO diagnostics panel JS served at %s from %s", STATIC_URL, panel_file)
    return True


async def async_setup_diagnostics(hass: HomeAssistant) -> None:
    """Prepare diagnostics infrastructure and apply the persisted setting."""
    domain_data = hass.data.setdefault(DATA_DIAGNOSTICS, {})
    get_store(hass)

    if not domain_data.get("websocket_registered"):
        websocket_api.async_register_command(hass, websocket_get_diagnostics)
        websocket_api.async_register_command(hass, websocket_clear_diagnostics)
        domain_data["websocket_registered"] = True

    if not await _async_ensure_diagnostics_static_path(hass):
        return

    entries = hass.config_entries.async_entries(DOMAIN)
    enabled = any(bool(entry.options.get(CONF_DIAGNOSTICS_ENABLED, True)) for entry in entries)
    await async_set_diagnostics_enabled(hass, enabled)


async def async_set_diagnostics_enabled(hass: HomeAssistant, enabled: bool) -> None:
    """Enable or disable collection and the sidebar panel dynamically."""
    domain_data = hass.data.setdefault(DATA_DIAGNOSTICS, {})
    domain_data["enabled"] = bool(enabled)

    if enabled:
        # The options flow may enable diagnostics after a transient setup
        # error. Never advertise a sidebar panel whose JS cannot be served.
        if not await _async_ensure_diagnostics_static_path(hass):
            _LOGGER.error("ELTAKO diagnostics cannot be enabled until panel JS is installed")
            return
        if not domain_data.get("panel_registered"):
            try:
                # An already-existing stale panel can still reference an older
                # offline build's JS filename. Replace it, keeping its URL.
                if frontend.async_panel_exists(hass, PANEL_URL_PATH):
                    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
                await panel_custom.async_register_panel(
                    hass,
                    frontend_url_path=PANEL_URL_PATH,
                    webcomponent_name=PANEL_NAME,
                    sidebar_title="Funk / Bus Diagnose",
                    sidebar_icon="mdi:access-point-network",
                    module_url=PANEL_MODULE_URL,
                    require_admin=True,
                )
                domain_data["panel_registered"] = True
            except ValueError:
                # A stale panel from an earlier test version can still exist.
                if frontend.async_panel_exists(hass, PANEL_URL_PATH):
                    domain_data["panel_registered"] = True
                else:
                    _LOGGER.exception("ELTAKO diagnostics panel registration failed")
                    return
            except Exception:
                _LOGGER.exception("ELTAKO diagnostics panel registration failed")
                return
        diagnostic_event(hass, "diagnostics_enabled", panel=PANEL_URL_PATH)
        _LOGGER.info("ELTAKO diagnostics enabled at /%s", PANEL_URL_PATH)
        return

    if domain_data.get("panel_registered") or frontend.async_panel_exists(hass, PANEL_URL_PATH):
        frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
    domain_data["panel_registered"] = False
    get_store(hass).clear()
    _LOGGER.info("ELTAKO diagnostics disabled")
