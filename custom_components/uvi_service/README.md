# UVI Service for Home Assistant

Custom integration for the UVI heating and water portal. Requires Home Assistant
2026.3 or newer for bundled brand images.

## Installation

1. Place this `uvi_service` directory inside your Home Assistant configuration
   directory at `custom_components/uvi_service`.
2. Restart Home Assistant.
3. Open Settings > Devices & services > Add integration > UVI Service.
4. Enter the plain property ID, login email and password. If the original portal
   link includes `djxkaiemglvvihukvsobuyiyby`, enter its value as the optional
   launch token; otherwise leave that field empty.

No YAML or script installation is required. The existing command-line exporter
continues to work independently.

## Credentials

Credentials are stored by Home Assistant in its config entry. This is normal
Home Assistant configuration storage, not an encrypted secrets vault. Protect
your configuration directory and backups. Password and token inputs are masked.
Neither credentials nor request/response bodies are written to integration logs.

Use the integration entry's Reconfigure menu to change credentials. The account
identity stays fixed; to change property or email, create another entry. Failed
authentication during updates starts Home Assistant's reauthentication flow.
There are no credentials bundled in this integration or the installation archive.

## Sensors and monthly history

The integration exposes cold water (m3), heating (kWh), hot water energy (kWh),
estimated hot water volume (m3), and a reporting-month date sensor. Sensor values
always refer to the latest month reported by the portal, not the current day.
Hot water volume is estimated as `kWh / 58.15`, rounded to 0.001 m3.

Data refreshes once a day. You can refresh manually using Home Assistant's
`homeassistant.update_entity` action. Each numeric sensor includes a
`monthly_history` attribute mapping ISO month dates to values. Monthly data is
persisted locally between refreshes; deleting the entry removes this cache.
If an update fails, entities become unavailable until a successful refresh.

The portal sends a complete initial form and subsequent UI deltas. The client
merges these in sequence, retaining unchanged values (including zero), and reads
the initial month directly from the full login response. Empty values remain
unknown rather than being converted to zero.

These are monthly totals, not meter readings. Sensors intentionally have no
statistics state class. This version does not backfill Recorder statistics or
feed the Energy dashboard. Native sensor history records when values were
downloaded; use `monthly_history` for the actual consumption month. Historical
statistics import requires a separate policy for representing monthly-only
measurements without inventing daily or hourly readings.

## Troubleshooting and verification

Enable debug logging for `custom_components.uvi_service` to see the number of
updated monthly records. Network errors and authentication errors are reported
without dumping sensitive portal data.

Offline protocol tests can be run from the repository root with:

```sh
python3 -m unittest discover -s tests -v
```

The integration uses Home Assistant's bundled aiohttp and voluptuous packages.
End-to-end setup, reauthentication and UI rendering must also be checked in a
running Home Assistant installation.

The original SVG icon source is included in `brand/`. PNG images are bundled for
Home Assistant's local brand image support:
https://contributors.home-assistant.io/core/integrations/brands/
