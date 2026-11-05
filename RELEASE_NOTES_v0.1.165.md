# ELTAKO Sensors & Actuators v0.1.165

This release combines the tested Home Assistant climate API modernization with the serialx migration and the corrected ESP2 receive path.

## Highlights

- **Home Assistant 2026.11:** Use the native ClimateEntity temperature properties while keeping the existing FHK14/F4HK14/FAE14 and FKS-SV control logic.
- **External room temperature:** Accept values from **−15 °C to +40 °C** for configured Home Assistant sensor entities. The displayed value remains unchanged. A5-10-06 can represent only 0–40 °C; negative measurements are clamped to 0 °C *for transmission only*, with `protokoll_isttemperatur` and `protokoll_temperatur_begrenzt` diagnostics. FKS-SV continues to fall back to its native sensor path below 0 °C.
- **serialx 1.15.1:** Replace `pyserial` for USB serial I/O. Maintain stable FAM-USB `if01` detection and FTDI FGW14-USB/FAM14 port resolution.
- **Reliable EnOcean receive:** Buffer fragmented ESP2 frames instead of dropping partial USB reads, preserve FIFO order and checksum resynchronization. This fixes intermittent FT55 press/release states and protects 1BS/4BS sensors and separately addressed battery telegrams.
- **Marketplace downloads:** Ship `ELTAKO_Sensors_Actuators.zip` as the release asset to support direct Marketplace installation and GitHub asset download counts.

## Compatibility and installation

- Requires **Home Assistant 2026.11.0 or newer** for this release.
- Existing device identities and configuration options are retained. No automatic integration reload is introduced for room temperature assignments.
- Marketplace/HACS users can update via the repository entry once the new release is available. Restart Home Assistant after updating.
- For manual installation, extract the integration files to `/config/custom_components/eltako_sensors_actuators/`.
- Before updating, make a Home Assistant backup.

## Verification

The FAM-USB and FGW14-USB gateways, FT55 press/release and temperature assignment were checked in real hardware tests of the combined v0.1.165b6 preview. Automated tests cover ESP2 fragmentation/resynchronization and the FKS-SV room-temperature path. Other device-specific combinations may require additional testing.

**Note:** Publishing a GitHub release does not automatically make a repository searchable in the Marketplace catalog. Public catalog inclusion requires an accepted pull request to `hacs/default`.
