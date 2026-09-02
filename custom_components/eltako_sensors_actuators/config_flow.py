from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import persistent_notification
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

try:
    from homeassistant.helpers import selector
except Exception:  # pragma: no cover - HA version dependent
    selector = None

from .const import (
    CONF_CONNECTION_KIND,
    CONF_DIAGNOSTICS_ENABLED,
    CONF_DEVICES,
    CONF_GATEWAY_TYPE,
    CONF_PORT,
    CONF_RELOAD_AFTER_SAVE,
    CONF_SELECTED_YAML_GATEWAY,
    CONF_SELECTED_YAML_GATEWAY_KEY,
    CONF_YAML_CONFIG,
    CONF_YAML_FILE_PATH,
    CONNECTION_KIND_ENOCEAN_USB,
    CONNECTION_KIND_RS485_BUS,
    CONNECTION_KIND_UNKNOWN,
    DOMAIN,
    GATEWAY_TYPE_AUTO,
    GATEWAY_TYPE_FAM_USB,
)
from .yaml_config import EltakoYamlError, list_eedtoy_yaml_gateways, parse_eedtoy_yaml

_LOGGER = logging.getLogger(__name__)
DEFAULT_NAME = "ELTAKO Sensors & Actuators"
MANUAL_PORT = "manual"

_TTYS_RE = re.compile(r"^/dev/ttyS\d+$")


def _is_noise_serial_port(device: str, description: str | None, hwid: str | None) -> bool:
    """Filter built-in Linux serial ports that are not USB gateways."""
    return bool(_TTYS_RE.match(device))


def _normalize_usb_text(device: str, description: str | None, hwid: str | None) -> str:
    return " ".join([device or "", description or "", hwid or ""]).lower()


def _infer_connection_kind(device: str, description: str | None, hwid: str | None) -> str:
    """Infer the physical connection family from stable USB descriptors."""
    text = _normalize_usb_text(device, description, hwid)

    if "ftdi_ft232r_usb_uart" in text or "ft232r" in text or "ftdi" in text:
        return CONNECTION_KIND_RS485_BUS

    if "enocean_gmbh_enocean_programmer" in text or "enocean programmer" in text:
        return CONNECTION_KIND_ENOCEAN_USB

    if "enocean" in text:
        return CONNECTION_KIND_ENOCEAN_USB

    return CONNECTION_KIND_UNKNOWN


def _dedupe_group_key(port: Any) -> str:
    """Group multiple Linux interface nodes of the same physical USB device."""
    vid = getattr(port, "vid", None)
    pid = getattr(port, "pid", None)
    serial_number = getattr(port, "serial_number", None)
    device = str(getattr(port, "device", ""))
    description = getattr(port, "description", None)
    hwid = getattr(port, "hwid", None)
    kind = _infer_connection_kind(device, description, hwid)

    if kind == CONNECTION_KIND_ENOCEAN_USB and vid and pid and serial_number:
        return f"enocean:{vid}:{pid}:{serial_number}"

    return f"device:{device}"


def _interface_rank(port: Any) -> tuple[int, int, str]:
    """Return deterministic preference for multi-interface USB devices.

    FAM-USB / EnOcean Programmer V3.2 exposes two Linux interfaces. The
    usable ESP2 interface is if01; if00 is present but does not transmit the
    radio telegrams reliably. For this device family we must therefore always
    prefer the if01 node and, if available, the stable /dev/serial/by-id path.
    """
    device = str(getattr(port, "device", ""))
    description = getattr(port, "description", None)
    hwid = getattr(port, "hwid", None)
    text = " ".join([
        device,
        str(getattr(port, "name", "") or ""),
        str(description or ""),
        str(hwid or ""),
        str(getattr(port, "interface", "") or ""),
        str(getattr(port, "location", "") or ""),
    ]).lower()
    kind = _infer_connection_kind(device, description, hwid)
    by_id_rank = 0 if "/dev/serial/by-id/" in device.lower() else 1

    if kind == CONNECTION_KIND_ENOCEAN_USB:
        if "if01" in text or "interface 01" in text or "interface 1" in text:
            return (0, by_id_rank, device)
        if "if00" in text or "interface 00" in text or "interface 0" in text:
            return (5, by_id_rank, device)

    else:
        if "if00" in text or "interface 00" in text or "interface 0" in text:
            return (0, by_id_rank, device)
        if "if01" in text or "interface 01" in text or "interface 1" in text:
            return (1, by_id_rank, device)

    tty_match = re.search(r"ttyusb(\d+)$", device.lower())
    if tty_match:
        return (10 + int(tty_match.group(1)), by_id_rank, device)

    return (99, by_id_rank, device)


def _serial_gateway_hint(device: str, description: str | None, hwid: str | None) -> str:
    kind = _infer_connection_kind(device, description, hwid)

    if kind == CONNECTION_KIND_RS485_BUS:
        return "FAM14 / FGW14-USB RS485-Bus"

    if kind == CONNECTION_KIND_ENOCEAN_USB:
        return "FAM-USB / EnOcean USB-Gateway"

    return "ELTAKO Gateway"


def _friendly_serial_label(device: str, description: str | None, hwid: str | None) -> str:
    hint = _serial_gateway_hint(device, description, hwid)
    return f"{hint} - {device}"


def _list_serial_ports() -> dict[str, dict[str, str]]:
    """Return clean serial port metadata for the config/options flow."""
    choices: dict[str, dict[str, str]] = {}
    try:
        from serial.tools import list_ports
    except Exception as err:  # pragma: no cover - depends on HA runtime
        _LOGGER.warning("pyserial list_ports unavailable: %s", err)
        return choices

    grouped: dict[str, list[Any]] = {}

    for port in list_ports.comports(include_links=True):
        device = str(port.device)
        description = getattr(port, "description", None)
        hwid = getattr(port, "hwid", None)

        if _is_noise_serial_port(device, description, hwid):
            continue

        if _infer_connection_kind(device, description, hwid) == CONNECTION_KIND_UNKNOWN:
            continue

        grouped.setdefault(_dedupe_group_key(port), []).append(port)

    for ports in grouped.values():
        port = sorted(ports, key=_interface_rank)[0]
        device = str(port.device)
        description = getattr(port, "description", None)
        hwid = getattr(port, "hwid", None)
        choices[device] = {
            "label": _friendly_serial_label(device, description, hwid),
            "connection_kind": _infer_connection_kind(device, description, hwid),
        }

    # HA OS systems sometimes expose /dev/serial/by-id links even when
    # pyserial's include_links result is incomplete.  Add these links
    # explicitly and prefer them over volatile /dev/ttyUSB* entries pointing to
    # the same target.
    try:
        by_id_dir = Path("/dev/serial/by-id")
        if by_id_dir.exists():
            for link in sorted(by_id_dir.iterdir(), key=lambda x: str(x)):
                link_path = str(link)
                text = link_path.lower()
                kind = _infer_connection_kind(link_path, link.name, link_path)
                if kind == CONNECTION_KIND_UNKNOWN:
                    continue
                # For FAM-USB expose only if01 as the selectable stable port.
                if kind == CONNECTION_KIND_ENOCEAN_USB and "if01" not in text:
                    continue
                try:
                    target = link.resolve()
                    for existing in list(choices):
                        if "/dev/serial/by-id/" in existing:
                            continue
                        try:
                            if Path(existing).resolve() == target:
                                choices.pop(existing, None)
                        except Exception:
                            pass
                except Exception:
                    pass
                choices[link_path] = {
                    "label": _friendly_serial_label(link_path, link.name, link_path),
                    "connection_kind": kind,
                }
    except Exception as err:
        _LOGGER.debug("ELTAKO by-id serial scan failed: %s", err)

    # If a stable EnOcean Programmer if01 by-id entry is available, hide all
    # volatile /dev/ttyUSB* entries for the FAM-USB from the UI.  Linux may
    # renumber these nodes on every reboot, and showing them next to the stable
    # if01 symlink invites users to select an unstable port.  Keep /dev/ttyUSB*
    # only as an internal runtime fallback on systems that do not expose
    # /dev/serial/by-id.
    has_stable_enocean_if01 = any(
        key.startswith("/dev/serial/by-id/")
        and meta.get("connection_kind") == CONNECTION_KIND_ENOCEAN_USB
        and "if01" in key.lower()
        for key, meta in choices.items()
    )
    if has_stable_enocean_if01:
        for existing, meta in list(choices.items()):
            if existing.startswith("/dev/ttyUSB") and meta.get("connection_kind") == CONNECTION_KIND_ENOCEAN_USB:
                choices.pop(existing, None)

    return dict(sorted(choices.items(), key=lambda item: item[1]["label"]))


def _gateway_type_for_connection_kind(connection_kind: str) -> str:
    if connection_kind == CONNECTION_KIND_ENOCEAN_USB:
        return GATEWAY_TYPE_FAM_USB
    return GATEWAY_TYPE_AUTO


def _default_entry_name(port: str, serial_ports: dict[str, dict[str, str]]) -> str:
    meta = serial_ports.get(port)
    if meta:
        return meta["label"]
    if port and port != MANUAL_PORT:
        return f"ELTAKO Gateway - {port}"
    return DEFAULT_NAME


def _manual_port_default(current_port: str, port_choices: dict[str, str]) -> str:
    return "" if current_port in port_choices else current_port


def _yaml_field() -> Any:
    if selector is not None:
        try:
            return selector.TextSelector(
                selector.TextSelectorConfig(multiline=True, type=selector.TextSelectorType.TEXT)
            )
        except Exception:
            pass
    return str


def _gateway_choice_map(gateways) -> dict[str, str]:
    return {gateway.key: gateway.label for gateway in gateways}


def _normalize_yaml_input(value: Any) -> str:
    """Normalize pasted/file YAML without changing meaningful indentation.

    Some copy/paste paths and older EEDTOY exports contain blank lines made
    only from tabs. PyYAML rejects those lines even though they carry no data.
    Remove whitespace from otherwise empty lines and keep all non-empty lines
    unchanged apart from trailing whitespace.
    """
    raw = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = ["" if not line.strip() else line.rstrip() for line in raw.split("\n")]
    return "\n".join(lines).strip()


def _yaml_error_key(err: Exception) -> str:
    """Return a precise UI error key for common EEDTOY YAML failures."""
    message = str(err).lower()
    if (
        "sender.id" in message
        or "controller-id-kollision" in message
        or "controller-id " in message and "bereits" in message
    ):
        return "sender_id_collision"
    if "\\t" in message or "tab" in message:
        return "invalid_yaml_tabs"
    return "invalid_yaml"


def _read_text_file(path: str, config_dir: str) -> str:
    """Read a YAML file below Home Assistant's actual config directory.

    Users can enter either a relative filename or the common UI aliases
    /config/... and /homeassistant/.... Both aliases are mapped to the config
    directory reported by Home Assistant before the containment check.
    """
    raw_text = str(path or "").strip()
    if not raw_text:
        raise ValueError("empty path")

    config_root = Path(config_dir).expanduser().resolve()
    raw_path = Path(raw_text).expanduser()

    if raw_path.is_absolute():
        parts = raw_path.parts
        alias_root = parts[1].lower() if len(parts) >= 2 else ""
        if alias_root in {"config", "homeassistant"}:
            relative = Path(*parts[2:]) if len(parts) > 2 else Path()
            candidate = (config_root / relative).resolve()
        else:
            candidate = raw_path.resolve()
    else:
        candidate = (config_root / raw_path).resolve()

    try:
        candidate.relative_to(config_root)
    except ValueError as err:
        raise ValueError("path outside config directory") from err

    if candidate == config_root or not candidate.exists() or not candidate.is_file():
        raise FileNotFoundError(str(candidate))

    return candidate.read_text(encoding="utf-8-sig")


class EltakoSensorsActuatorsConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for ELTAKO Sensors & Actuators."""

    VERSION = 8

    def __init__(self) -> None:
        self._pending_port: str | None = None
        self._pending_connection_kind: str = CONNECTION_KIND_UNKNOWN
        self._pending_gateway_type: str = GATEWAY_TYPE_AUTO
        self._pending_default_name: str = DEFAULT_NAME
        self._pending_unique_id: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 1: select the physical gateway/port only."""
        errors: dict[str, str] = {}
        serial_ports = await self.hass.async_add_executor_job(_list_serial_ports)
        port_choices = {port: meta["label"] for port, meta in serial_ports.items()}
        port_choices[MANUAL_PORT] = "Manuell eingeben / Netzwerkpfad"
        default_port = next(iter(serial_ports), MANUAL_PORT)

        if user_input is not None:
            selected_port = str(user_input[CONF_PORT])
            manual_port = str(user_input.get("manual_port", "")).strip()
            port = manual_port if selected_port == MANUAL_PORT else selected_port.strip()

            if not port:
                errors[CONF_PORT] = "missing_port"
            else:
                connection_kind = serial_ports.get(selected_port, {}).get(
                    "connection_kind", CONNECTION_KIND_UNKNOWN
                )
                gateway_type = _gateway_type_for_connection_kind(connection_kind)

                self._pending_port = port
                self._pending_connection_kind = connection_kind
                self._pending_gateway_type = gateway_type
                self._pending_default_name = _default_entry_name(selected_port, serial_ports)
                self._pending_unique_id = f"{connection_kind}:{port}"

                return await self.async_step_name()

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=default_port): vol.In(port_choices),
                vol.Optional("manual_port", default=""): str,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"port_count": str(len(serial_ports))},
        )

    async def async_step_name(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Step 2: allow editing the auto-generated name."""
        if self._pending_port is None:
            return await self.async_step_user()

        errors: dict[str, str] = {}

        if user_input is not None:
            title = str(user_input.get(CONF_NAME, "")).strip() or self._pending_default_name
            await self.async_set_unique_id(self._pending_unique_id)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=title,
                data={
                    CONF_NAME: title,
                    CONF_GATEWAY_TYPE: self._pending_gateway_type,
                    CONF_CONNECTION_KIND: self._pending_connection_kind,
                    CONF_PORT: self._pending_port,
                    CONF_YAML_CONFIG: "",
                    CONF_YAML_FILE_PATH: "",
                    CONF_DEVICES: [],
                    CONF_SELECTED_YAML_GATEWAY: None,
                    CONF_SELECTED_YAML_GATEWAY_KEY: "",
                },
            )

        schema = vol.Schema({vol.Optional(CONF_NAME, default=self._pending_default_name): str})
        return self.async_show_form(step_id="name", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return EltakoSensorsActuatorsOptionsFlow()


class EltakoSensorsActuatorsOptionsFlow(config_entries.OptionsFlow):
    """Options flow for connection and EEDTOY YAML import."""

    def __init__(self) -> None:
        self._pending_yaml_text: str | None = None
        self._pending_yaml_path: str = ""
        self._pending_gateway_choices: dict[str, str] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options=["connection", "yaml", "diagnostics"],
        )

    def _current_data(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    def _merged_options(self, updates: dict[str, Any]) -> dict[str, Any]:
        current_options = dict(self.config_entry.options)
        current_options.update(updates)
        return current_options

    def _notify_saved(self, device_count: int, gateway_label: str | None = None) -> None:
        gateway_line = f"\n\nAusgewaehlter Gateway-Block: {gateway_label}" if gateway_label else ""
        suffix = "Geraet" if device_count == 1 else "Geraete"
        persistent_notification.async_create(
            self.hass,
            (
                f"EEDTOY YAML wurde gespeichert. Importiert: {device_count} {suffix}."
                f"{gateway_line}\n\n"
                "Die Integration wird jetzt automatisch neu geladen; neue oder geaenderte Entities erscheinen direkt."
            ),
            title="ELTAKO Sensors & Actuators",
            notification_id=f"{DOMAIN}_yaml_saved_{self.config_entry.entry_id}",
        )


    async def async_step_diagnostics(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure the global diagnostics sidebar panel."""
        current_enabled = bool(self._current_data().get(CONF_DIAGNOSTICS_ENABLED, True))

        if user_input is not None:
            enabled = bool(user_input.get(CONF_DIAGNOSTICS_ENABLED, False))
            # Keep this setting global across all configured ELTAKO gateways.
            for entry in self.hass.config_entries.async_entries(DOMAIN):
                options = dict(entry.options)
                options[CONF_DIAGNOSTICS_ENABLED] = enabled
                self.hass.config_entries.async_update_entry(entry, options=options)

            from .diagnostics import async_set_diagnostics_enabled
            await async_set_diagnostics_enabled(self.hass, enabled)
            return self.async_create_entry(
                title="",
                data=self._merged_options({CONF_DIAGNOSTICS_ENABLED: enabled}),
            )

        schema = vol.Schema(
            {vol.Required(CONF_DIAGNOSTICS_ENABLED, default=current_enabled): bool}
        )
        return self.async_show_form(step_id="diagnostics", data_schema=schema)

    async def async_step_connection(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        serial_ports = await self.hass.async_add_executor_job(_list_serial_ports)
        port_choices = {port: meta["label"] for port, meta in serial_ports.items()}
        port_choices[MANUAL_PORT] = "Manuell eingeben / Netzwerkpfad"

        data = self._current_data()
        current_port = str(data.get(CONF_PORT, MANUAL_PORT))
        default_port = current_port if current_port in port_choices else MANUAL_PORT
        default_manual = _manual_port_default(current_port, port_choices)

        if user_input is not None:
            selected_port = str(user_input[CONF_PORT])
            manual_port = str(user_input.get("manual_port", "")).strip()
            port = manual_port if selected_port == MANUAL_PORT else selected_port.strip()

            if not port:
                errors[CONF_PORT] = "missing_port"
            else:
                connection_kind = serial_ports.get(selected_port, {}).get(
                    "connection_kind", CONNECTION_KIND_UNKNOWN
                )
                gateway_type = _gateway_type_for_connection_kind(connection_kind)

                yaml_text = str(data.get(CONF_YAML_CONFIG, "") or "")
                selected_gateway_key = str(data.get(CONF_SELECTED_YAML_GATEWAY_KEY, "") or "")
                try:
                    parsed = parse_eedtoy_yaml(
                        yaml_text,
                        connection_kind=connection_kind,
                        gateway_type=gateway_type,
                        selected_gateway_key=selected_gateway_key,
                    )
                except EltakoYamlError as err:
                    _LOGGER.warning("EEDTOY YAML reparse after connection change failed: %s", err)
                    errors["base"] = _yaml_error_key(err)
                else:
                    return self.async_create_entry(
                        title="",
                        data=self._merged_options(
                            {
                                CONF_PORT: port,
                                CONF_CONNECTION_KIND: connection_kind,
                                CONF_GATEWAY_TYPE: gateway_type,
                                CONF_DEVICES: parsed.devices,
                                CONF_SELECTED_YAML_GATEWAY: parsed.selected_gateway,
                                CONF_RELOAD_AFTER_SAVE: True,
                            }
                        ),
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=default_port): vol.In(port_choices),
                vol.Optional("manual_port", default=default_manual): str,
            }
        )

        return self.async_show_form(
            step_id="connection",
            data_schema=schema,
            errors=errors,
            description_placeholders={"port_count": str(len(serial_ports))},
        )

    async def _process_yaml_submission(
        self,
        yaml_text: str,
        yaml_path: str,
        *,
        error_field: str,
        connection_kind: str,
        gateway_type: str,
    ) -> tuple[FlowResult | None, dict[str, str]]:
        """Validate and store a YAML source selected by an explicit flow."""
        errors: dict[str, str] = {}
        normalized_text = _normalize_yaml_input(yaml_text)
        if not normalized_text:
            errors[error_field] = "yaml_source_required"
            return None, errors

        try:
            gateways = list_eedtoy_yaml_gateways(normalized_text)
        except EltakoYamlError as err:
            _LOGGER.warning("EEDTOY YAML import failed: %s", err)
            errors[error_field] = _yaml_error_key(err)
            return None, errors

        if not gateways:
            errors[error_field] = "no_devices_found"
            return None, errors

        if len(gateways) == 1:
            try:
                parsed = parse_eedtoy_yaml(
                    normalized_text,
                    connection_kind=connection_kind,
                    gateway_type=gateway_type,
                    selected_gateway_key=gateways[0].key,
                )
            except EltakoYamlError as err:
                _LOGGER.warning("EEDTOY YAML import failed: %s", err)
                errors[error_field] = _yaml_error_key(err)
                return None, errors

            self._notify_saved(len(parsed.devices), gateways[0].label)
            return (
                self.async_create_entry(
                    title="",
                    data=self._merged_options(
                        {
                            CONF_YAML_CONFIG: normalized_text,
                            CONF_YAML_FILE_PATH: yaml_path,
                            CONF_DEVICES: parsed.devices,
                            CONF_SELECTED_YAML_GATEWAY: parsed.selected_gateway,
                            CONF_RELOAD_AFTER_SAVE: True,
                            CONF_SELECTED_YAML_GATEWAY_KEY: gateways[0].key,
                        }
                    ),
                ),
                errors,
            )

        self._pending_yaml_text = normalized_text
        self._pending_yaml_path = yaml_path
        self._pending_gateway_choices = _gateway_choice_map(gateways)
        return await self.async_step_yaml_gateway(), errors

    async def async_step_yaml(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose one unambiguous YAML import source."""
        return self.async_show_menu(
            step_id="yaml",
            menu_options=["yaml_text", "yaml_file"],
        )

    async def async_step_yaml_text(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Import YAML exclusively from the multiline text field."""
        data = self._current_data()
        current_yaml = str(data.get(CONF_YAML_CONFIG, "") or "")
        connection_kind = str(data.get(CONF_CONNECTION_KIND, CONNECTION_KIND_UNKNOWN))
        gateway_type = str(data.get(CONF_GATEWAY_TYPE, GATEWAY_TYPE_AUTO))
        errors: dict[str, str] = {}

        if user_input is not None:
            yaml_text = str(user_input.get(CONF_YAML_CONFIG, "") or "")
            result, errors = await self._process_yaml_submission(
                yaml_text,
                "",
                error_field=CONF_YAML_CONFIG,
                connection_kind=connection_kind,
                gateway_type=gateway_type,
            )
            if result is not None:
                return result

        schema = vol.Schema(
            {vol.Optional(CONF_YAML_CONFIG, default=current_yaml): _yaml_field()}
        )
        return self.async_show_form(step_id="yaml_text", data_schema=schema, errors=errors)

    async def async_step_yaml_file(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Import YAML exclusively from a file inside the HA config folder."""
        data = self._current_data()
        current_path = str(data.get(CONF_YAML_FILE_PATH, "") or "")
        connection_kind = str(data.get(CONF_CONNECTION_KIND, CONNECTION_KIND_UNKNOWN))
        gateway_type = str(data.get(CONF_GATEWAY_TYPE, GATEWAY_TYPE_AUTO))
        errors: dict[str, str] = {}

        if user_input is not None:
            yaml_path = str(user_input.get(CONF_YAML_FILE_PATH, "") or "").strip()
            if not yaml_path:
                errors[CONF_YAML_FILE_PATH] = "yaml_file_required"
            else:
                try:
                    yaml_text = await self.hass.async_add_executor_job(
                        _read_text_file,
                        yaml_path,
                        self.hass.config.path(),
                    )
                except FileNotFoundError:
                    errors[CONF_YAML_FILE_PATH] = "file_not_found"
                except ValueError:
                    errors[CONF_YAML_FILE_PATH] = "file_not_allowed"
                else:
                    result, errors = await self._process_yaml_submission(
                        yaml_text,
                        yaml_path,
                        error_field=CONF_YAML_FILE_PATH,
                        connection_kind=connection_kind,
                        gateway_type=gateway_type,
                    )
                    if result is not None:
                        return result

        schema = vol.Schema(
            {vol.Optional(CONF_YAML_FILE_PATH, default=current_path): str}
        )
        return self.async_show_form(step_id="yaml_file", data_schema=schema, errors=errors)

    async def async_step_yaml_gateway(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Select the gateway block when the imported YAML contains multiple gateways."""
        errors: dict[str, str] = {}
        data = self._current_data()
        current_key = str(data.get(CONF_SELECTED_YAML_GATEWAY_KEY, "") or "")
        default_key = current_key if current_key in self._pending_gateway_choices else next(iter(self._pending_gateway_choices), "")

        if not self._pending_yaml_text or not self._pending_gateway_choices:
            return await self.async_step_yaml()

        if user_input is not None:
            selected_key = str(user_input.get(CONF_SELECTED_YAML_GATEWAY_KEY, "") or "")
            if selected_key not in self._pending_gateway_choices:
                errors[CONF_SELECTED_YAML_GATEWAY_KEY] = "missing_gateway"
            else:
                try:
                    parsed = parse_eedtoy_yaml(
                        self._pending_yaml_text,
                        connection_kind=str(data.get(CONF_CONNECTION_KIND, CONNECTION_KIND_UNKNOWN)),
                        gateway_type=str(data.get(CONF_GATEWAY_TYPE, GATEWAY_TYPE_AUTO)),
                        selected_gateway_key=selected_key,
                    )
                except EltakoYamlError as err:
                    _LOGGER.warning("EEDTOY YAML gateway selection failed: %s", err)
                    errors["base"] = _yaml_error_key(err)
                else:
                    self._notify_saved(len(parsed.devices), self._pending_gateway_choices.get(selected_key))
                    return self.async_create_entry(
                        title="",
                        data=self._merged_options(
                            {
                                CONF_YAML_CONFIG: self._pending_yaml_text,
                                CONF_YAML_FILE_PATH: self._pending_yaml_path,
                                CONF_DEVICES: parsed.devices,
                                CONF_SELECTED_YAML_GATEWAY: parsed.selected_gateway,
                                CONF_RELOAD_AFTER_SAVE: True,
                                CONF_SELECTED_YAML_GATEWAY_KEY: selected_key,
                            }
                        ),
                    )

        schema = vol.Schema(
            {
                vol.Required(CONF_SELECTED_YAML_GATEWAY_KEY, default=default_key): vol.In(self._pending_gateway_choices),
            }
        )
        return self.async_show_form(step_id="yaml_gateway", data_schema=schema, errors=errors)
