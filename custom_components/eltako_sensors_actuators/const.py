from __future__ import annotations

DOMAIN = "eltako_sensors_actuators"

CONF_GATEWAY_TYPE = "gateway_type"
CONF_PORT = "port"
CONF_DEVICES = "devices"
CONF_CONNECTION_KIND = "connection_kind"
CONF_YAML_CONFIG = "yaml_config"
CONF_SELECTED_YAML_GATEWAY = "selected_yaml_gateway"
CONF_SELECTED_YAML_GATEWAY_KEY = "selected_yaml_gateway_key"
CONF_YAML_FILE_PATH = "yaml_file_path"

CONNECTION_KIND_RS485_BUS = "rs485_bus"
CONNECTION_KIND_ENOCEAN_USB = "enocean_usb"
CONNECTION_KIND_UNKNOWN = "unknown"

GATEWAY_TYPE_AUTO = "auto"
GATEWAY_TYPE_FAM14 = "fam14"
GATEWAY_TYPE_FGW14USB = "fgw14usb"
GATEWAY_TYPE_FAM_USB = "fam-usb"

SUPPORTED_GATEWAY_TYPES = [
    GATEWAY_TYPE_AUTO,
    GATEWAY_TYPE_FAM14,
    GATEWAY_TYPE_FGW14USB,
    GATEWAY_TYPE_FAM_USB,
]

GATEWAY_TYPE_LABELS = {
    GATEWAY_TYPE_AUTO: "Automatisch erkennen",
    GATEWAY_TYPE_FAM14: "FAM14",
    GATEWAY_TYPE_FGW14USB: "FGW14-USB",
    GATEWAY_TYPE_FAM_USB: "FAM-USB",
}

PLATFORMS = [
    "sensor",
    "binary_sensor",
    "light",
    "switch",
    "cover",
    "climate",
    "button",
    "fan",
]

SIGNAL_TELEGRAM = "eltako_sensors_actuators_telegram"
SERVICE_DUMP_GATEWAY_STATE = "dump_gateway_state"
SERVICE_PROBE_GATEWAY = "probe_gateway"

SERVICE_RELOAD_CONFIG = "reload_config"

CONF_RELOAD_AFTER_SAVE = "reload_after_save"

CONF_DIAGNOSTICS_ENABLED = "diagnostics_enabled"

# Persistent per-FKS-SV room-temperature source overrides. The top-level map
# lives in ConfigEntry.options and is keyed by normalized physical EnOcean ID.
CONF_FKS_SV_ROOM_TEMPERATURE_OVERRIDES = "fks_sv_room_temperature_overrides"
CONF_FKS_SV_DEVICE_ID = "fks_sv_device_id"
CONF_FKS_SV_TEMPERATURE_SOURCE = "fks_sv_temperature_source"
CONF_FKS_SV_EXTERNAL_TEMPERATURE_ENTITY = "fks_sv_external_temperature_entity"

FKS_SV_TEMPERATURE_SOURCE_INTERNAL = "internal"
FKS_SV_TEMPERATURE_SOURCE_EXTERNAL = "external"

SIGNAL_FKS_SV_ROOM_TEMPERATURE_UPDATED = f"{DOMAIN}_fks_sv_room_temperature_updated"
