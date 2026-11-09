# ELTAKO Sensors & Actuators v0.1.166

This release consolidates the Marketplace review fixes and the device fixes that were hardware-tested in the v0.1.166 beta/offline builds.

## Marketplace and Home Assistant fixes

- Move blocking filesystem work out of the Home Assistant event loop where required.
- Restrict entity-registry cleanup to entities owned by this integration/config entry.
- Protect the diagnostics WebSocket interface with administrator authentication.
- Fix the diagnostics panel static path and cache-busting so `frontend/diagnostics-panel.js` loads reliably.
- Keep Python bytecode (`__pycache__`, `*.pyc`) out of the repository and release ZIP.
- Keep translated UI/menu entries, teach-in controls, room-temperature assignment and gateway display behavior from the validated combined test build.

## FAH / FHD60SB illuminance

- Add ELTAKO-specific `A5-06-01` illuminance decoding without changing unrelated devices that share the EEP.
- Current EEDTOY exports are identified primarily by the stable technical `device_type` (`FAH`, FAH variants, `FIH65S`, `FHD60SB`).
- Retain a narrow compatibility fallback for older YAML using `device_class: illuminance` when no technical `device_type` exists.
- Decode the low range from DB3 (`0..100 lx`) and the high range from DB2 (`300..30000 lx`).
- Ignore teach-in telegrams for measurement updates.
- Preserve/migrate the existing brightness entity where possible instead of exposing the raw four-byte telegram as the sensor value.

Verified examples:

- FAH `00-00-00-0F` -> `0 lx`
- FAH `62-00-00-0F` -> `98 lx`
- FHD60SB `63-00-00-09` -> `99 lx`

## Legacy FRW-ws smoke detector

- Interpret the legacy `F6-02-01` RPS telegram as FRW status only when the configured device is identified as FRW/smoke detector.
- `0x10` (left-bottom pressed) -> smoke alarm ON.
- `0x30` (left-top pressed) -> low-battery warning ON.
- `0x00` (released) -> smoke alarm OFF / free and battery warning OFF / OK.
- Remove obsolete rocker/button helper entities only for the identified FRW; normal `F6-02-01` rockers remain unchanged.
- Keep FRWB (`A5-30-03`) separate and unchanged.

## Compatibility

- Requires Home Assistant 2026.11.0 or newer.
- Existing configuration entries and stable entity identities are retained where possible.
- EEDTOY 1.1.01 exports the recommended `device_type` fields for current configurations.
- Manual installation: replace `/config/custom_components/eltako_sensors_actuators/` with the contents of the release ZIP and restart Home Assistant.

## Validation

The release workflow validates Python syntax, JSON files, HACS metadata and hassfest, and runs regressions for serial receive, FKS-SV/FHK14 room temperature, F2L14 FAM-USB sender IDs, FAH/FHD60SB illuminance and legacy FRW status handling.
