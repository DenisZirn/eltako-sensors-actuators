"""Independent priority control for learned-sensor A5-10-06 heaters."""
from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers import entity_registry as er

from .const import CONF_DEVICES, DOMAIN, SIGNAL_ROOM_TEMPERATURE_UPDATED
from .entity_base import EltakoYamlEntity, device_key
from .heating_priority import (
    PRIORITY_BYTES, PRIORITY_OPTIONS, SIGNAL_HEATING_PRIORITY_TX,
    heating_control_mode, is_fhk61_priority_device, priority_mode, set_priority_mode, supports_heating_priority,
)

_LOGGER = logging.getLogger(__name__)


def _should_create_priority_select(device: dict[str, Any], options: dict[str, Any]) -> bool:
    """Do not register an unusable select for Series-14 ha_external controllers.

    The FHK61-230V uses a separate radio-priority mode and retains its select.
    No changes to the actuator's heating commands or source assignment.
    """
    return supports_heating_priority(device) and (
        is_fhk61_priority_device(device)
        or heating_control_mode(device, options) == "learned_sensor"
    )


def _priority_unique_id(entry_id: str, device: dict[str, Any]) -> str:
    """Mirror EltakoYamlEntity(..., suffix='Priorität') exactly."""
    base = f"{device_key(device)}_Priorität".lower().replace(" ", "_").replace("/", "_")
    return f"{DOMAIN}_{entry_id}_{base}"


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    config = {**entry.data, **entry.options}
    gateway = hass.data[DOMAIN][entry.entry_id]
    devices = config.get(CONF_DEVICES) or []
    options = dict(entry.options)

    active_devices = []
    obsolete_unique_ids = set()
    for device in devices:
        if not isinstance(device, dict) or not supports_heating_priority(device):
            continue
        if _should_create_priority_select(device, options):
            active_devices.append(device)
        else:
            # Previously-created unavailable selects remain in HA's entity
            # registry unless they are explicitly removed on config reload.
            obsolete_unique_ids.add(_priority_unique_id(entry.entry_id, device))

    if obsolete_unique_ids:
        registry = er.async_get(hass)
        for existing in er.async_entries_for_config_entry(registry, entry.entry_id):
            if (
                existing.domain == "select"
                and existing.platform == DOMAIN
                and existing.unique_id in obsolete_unique_ids
            ):
                _LOGGER.info(
                    "Removing obsolete ELTAKO heating priority select %s (ha_external)",
                    existing.entity_id,
                )
                registry.async_remove(existing.entity_id)

    async_add_entities([
        EltakoHeatingPrioritySelect(gateway, device)
        for device in active_devices
    ])


class EltakoHeatingPrioritySelect(EltakoYamlEntity, SelectEntity):
    """Desired controller priority; not a confirmed relay/actuator state."""

    _attr_icon = "mdi:priority-high"
    _attr_options = list(PRIORITY_OPTIONS.values())

    def __init__(self, gateway, device: dict[str, Any]) -> None:
        super().__init__(gateway, device, suffix="Priorität")
        self._attr_current_option = PRIORITY_OPTIONS[priority_mode(device, self._entry_options())]
        self._last_telegram: str | None = None
        self._last_sender: str | None = None
        self._last_tx: str | None = None
        self._last_success: bool | None = None
        self._last_error: str | None = None
        self._remove_options_listener = None

    def _entry_options(self) -> dict[str, Any]:
        entry = self.gateway.hass.config_entries.async_get_entry(self.gateway.entry_id)
        return dict(entry.options) if entry is not None else {}

    @property
    def available(self) -> bool:
        return bool(
            getattr(self.gateway, "hass", None)
            and (
                is_fhk61_priority_device(self.device_config)
                or heating_control_mode(self.device_config, self._entry_options()) == "learned_sensor"
            )
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attrs = dict(super().extra_state_attributes or {})
        attrs.update({
            "heating_control_mode": heating_control_mode(self.device_config, self._entry_options()),
            "controller_sender_id": self.device_config.get("sender_id"),
            "last_priority_telegram": self._last_telegram,
            "last_priority_byte": (f"0x{PRIORITY_BYTES[mode]:02X}" if (mode := priority_mode(self.device_config, self._entry_options())) in PRIORITY_BYTES else "Freigabe"),
            "last_sender_id": self._last_sender,
            "last_transmission": self._last_tx,
            "last_send_success": self._last_success,
            "last_send_error": self._last_error,
            "actor_confirmed_priority": False,
        })
        return attrs

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._remove_options_listener = async_dispatcher_connect(
            self.hass, SIGNAL_ROOM_TEMPERATURE_UPDATED, self._handle_options_changed,
        )

    def _handle_options_changed(self, entry_id: str) -> None:
        if entry_id != self.gateway.entry_id:
            return
        self._attr_current_option = PRIORITY_OPTIONS[
            priority_mode(self.device_config, self._entry_options())
        ]
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        reverse = {label: key for key, label in PRIORITY_OPTIONS.items()}
        mode = reverse.get(option)
        if mode is None:
            raise HomeAssistantError("Ungültige Heizungspriorität")
        if not self.available:
            raise HomeAssistantError(
                "Priorität ist für diese Gerätekonfiguration nicht verfügbar"
            )
        self._last_sender = self.device_config.get("sender_id")
        self._last_error = None
        if mode == "manual":
            # M is a one-shot release, not a normal priority value.
            # MiniSafe2 FHK61-230V manual mode transmits 00-00-00-08.
            # Reuse the existing FHK61 A5-10-06 setpoint encoder; Series-14
            # continues to use its independently verified manual release.
            raw = self.device_config.get("raw") if isinstance(self.device_config.get("raw"), dict) else {}
            model = str(self.device_config.get("device_type") or raw.get("device_type") or self.device_config.get("name") or "").upper().replace(" ", "")
            is_fhk61 = model.startswith("FHK61-230V")
            self._last_telegram = "00-00-00-08" if is_fhk61 else "00-00-00-0E"
            if is_fhk61:
                ok = await self.gateway.async_send_actuator_command(
                    self.device_config, "set_temperature", temperature=0,
                    current_temperature=None, controller_priority="ha",
                )
            else:
                ok = await self.gateway.async_send_actuator_command(
                    self.device_config, "release_heating_priority",
                )
            self._last_tx = datetime.now(timezone.utc).isoformat()
            self._last_success = bool(ok)
            if not ok:
                self._last_error = self.gateway.last_send_error or "Übertragung fehlgeschlagen"
                self.async_write_ha_state()
                raise HomeAssistantError(self._last_error)
        else:
            self._last_telegram = f"DB0=0x{PRIORITY_BYTES[mode]:02X}"
            # Dispatch triggers the existing Climate current target/room path.
            # The TX result is available in Climate diagnostics.
            self._last_success = None
        set_priority_mode(self.hass, self.gateway.entry_id, self.device_config, mode)
        self._attr_current_option = option
        self.async_write_ha_state()
        if mode != "manual":
            async_dispatcher_send(
                self.hass, SIGNAL_HEATING_PRIORITY_TX,
                self.gateway.entry_id, str(self.device_config.get("id") or ""),
            )

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_options_listener is not None:
            self._remove_options_listener()
            self._remove_options_listener = None
        await super().async_will_remove_from_hass()
