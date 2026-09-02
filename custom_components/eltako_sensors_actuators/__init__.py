from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import device_registry as dr

from .const import (
    CONF_GATEWAY_TYPE,
    CONF_PORT,
    CONF_RELOAD_AFTER_SAVE,
    CONF_SELECTED_YAML_GATEWAY,
    DOMAIN,
    PLATFORMS,
    SERVICE_DUMP_GATEWAY_STATE,
    SERVICE_PROBE_GATEWAY,
    SERVICE_RELOAD_CONFIG,
)
from .gateway import EltakoGateway
from .entity_base import gateway_device_name, gateway_model
from .diagnostics import async_set_diagnostics_enabled, async_setup_diagnostics, diagnostic_event

_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up integration-wide services that must not block gateway entries."""
    try:
        await async_setup_diagnostics(hass)
    except Exception:
        _LOGGER.exception(
            "ELTAKO diagnostics panel setup failed; continuing without the panel"
        )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = {**entry.data, **entry.options}

    devices = data.get("devices") or []
    _LOGGER.info(
        "Setting up ELTAKO Sensors & Actuators entry=%s port=%s gateway_type=%s imported_devices=%s",
        entry.entry_id,
        data.get(CONF_PORT),
        data.get(CONF_GATEWAY_TYPE),
        len(devices) if isinstance(devices, list) else 0,
    )

    gateway = EltakoGateway(
        hass=hass,
        entry_id=entry.entry_id,
        port=data[CONF_PORT],
        gateway_type=data[CONF_GATEWAY_TYPE],
        devices=devices if isinstance(devices, list) else [],
        selected_gateway=data.get(CONF_SELECTED_YAML_GATEWAY) if isinstance(data.get(CONF_SELECTED_YAML_GATEWAY), dict) else None,
    )

    diagnostic_event(hass, "config_entry_setup", entry_id=entry.entry_id, gateway_type=data.get(CONF_GATEWAY_TYPE), port=data.get(CONF_PORT))
    await gateway.async_start()
    _async_ensure_gateway_device(hass, entry, gateway)

    # YAML imports set a one-shot reload flag. The listener clears it before
    # reloading so options updates cannot create a reload loop.
    entry.async_on_unload(entry.add_update_listener(_async_options_update_listener))

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = gateway

    # Normal options changes do not reload. Only the one-shot flag written by
    # a successful YAML import or connection update triggers a reload.
    _async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def _async_options_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Apply global diagnostics changes and honor only explicit reload requests."""
    from .const import CONF_DIAGNOSTICS_ENABLED

    enabled = any(
        bool(current.options.get(CONF_DIAGNOSTICS_ENABLED, True))
        for current in hass.config_entries.async_entries(DOMAIN)
    )
    await async_set_diagnostics_enabled(hass, enabled)

    if not entry.options.get(CONF_RELOAD_AFTER_SAVE):
        _LOGGER.debug("ELTAKO options updated without reload request for entry %s", entry.entry_id)
        return

    options = dict(entry.options)
    options.pop(CONF_RELOAD_AFTER_SAVE, None)
    hass.config_entries.async_update_entry(entry, options=options)

    _LOGGER.info("Reloading ELTAKO Sensors & Actuators after YAML import: entry=%s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    gateway: EltakoGateway | None = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if gateway is not None:
        diagnostic_event(hass, "config_entry_unload", entry_id=entry.entry_id, gateway_type=gateway.gateway_type, port=gateway.port)
        await gateway.async_stop()

    return unload_ok


def _async_ensure_gateway_device(hass: HomeAssistant, entry: ConfigEntry, gateway: EltakoGateway) -> None:
    """Create the parent hub device before child entities reference it.

    All imported YAML devices use via_device=(DOMAIN, entry.entry_id). Home
    Assistant requires that parent device to exist in the device registry before
    any child device is registered. Without this, HA logs warnings and future
    versions will reject the device relationship.
    """
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        manufacturer="ELTAKO",
        name=gateway_device_name(gateway),
        model=gateway_model(gateway),
    )


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_DUMP_GATEWAY_STATE):
        return

    async def _dump_gateway_state(call: ServiceCall) -> None:
        for entry_id, gateway in hass.data.get(DOMAIN, {}).items():
            _LOGGER.info(
                "ELTAKO gateway state entry_id=%s port=%s configured_type=%s detected_type=%s base_id=%s probe=%s last_telegram=%s",
                entry_id,
                gateway.port,
                gateway.configured_gateway_type,
                gateway.gateway_type,
                gateway.base_id,
                gateway.probe_result,
                gateway.last_telegram,
            )

    async def _probe_gateway(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        gateways = hass.data.get(DOMAIN, {})
        selected = {entry_id: gateways.get(entry_id)} if entry_id else gateways

        for current_entry_id, gateway in selected.items():
            if gateway is None:
                continue
            result = await gateway.async_probe()
            _LOGGER.info(
                "ELTAKO gateway probe entry_id=%s port=%s detected_type=%s base_id=%s ok=%s message=%s",
                current_entry_id,
                gateway.port,
                result.detected_gateway_type,
                result.base_id,
                result.ok,
                result.message,
            )

    async def _reload_config(call: ServiceCall) -> None:
        entry_id = call.data.get("entry_id")
        entries = hass.config_entries.async_entries(DOMAIN)
        for entry in entries:
            if entry_id and entry.entry_id != entry_id:
                continue
            _LOGGER.info("Reloading ELTAKO Sensors & Actuators config entry %s", entry.entry_id)
            await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, SERVICE_DUMP_GATEWAY_STATE, _dump_gateway_state)
    hass.services.async_register(
        DOMAIN,
        SERVICE_PROBE_GATEWAY,
        _probe_gateway,
        schema=vol.Schema({vol.Optional("entry_id"): str}),
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RELOAD_CONFIG,
        _reload_config,
        schema=vol.Schema({vol.Optional("entry_id"): str}),
    )
