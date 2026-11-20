# UVI Service for Home Assistant

Custom integration for monthly heating and water consumption from
[uvi-service.de](https://uvi-service.de). An independent command-line exporter is
also included in [scripts/uvi_downloader.py](scripts/uvi_downloader.py).

## Features

- Set up, reconfigure and renew credentials in the Home Assistant UI.
- Download available monthly data once a day.
- Show cold water, heating energy, hot water energy, estimated hot water volume,
  and the latest reporting month.
- Preserve monthly consumption history locally between refreshes.
- Include local brand images for Home Assistant 2026.3 and newer.

This is an unofficial integration and depends on the portal's Genero/FourJs UI
protocol. Portal changes may require updates to the client.

Licensed under the [MIT License](LICENSE).

## Installation

Requires Home Assistant **2026.3 or newer** and a working UVI portal account.

### Manual installation

1. Copy [custom_components/uvi_service](custom_components/uvi_service) into your
   Home Assistant configuration directory at `custom_components/uvi_service`.
2. Restart Home Assistant.
3. Open **Settings > Devices & services > Add integration > UVI Service**.
4. Enter your property ID, login email, password and launch token. The token is
   the value of `djxkaiemglvvihukvsobuyiyby` in the original UVI portal link.

### HACS custom repository

Once this repository is published **and public**, add
`https://github.com/mosenberg/uvi-homeassistant` as a custom repository of type
**Integration** in HACS. Download UVI Service, restart Home Assistant, and follow
steps 3–4 above. The repository includes the metadata described in the
[HACS integration requirements](https://www.hacs.xyz/docs/publish/integration/).
It is not currently listed in HACS's default store.

See the [integration documentation](custom_components/uvi_service/README.md)
for credentials, refresh behavior, monthly history and troubleshooting.

## Consumption semantics

Values are totals for the latest month reported by the portal, not live meter
readings. Hot water volume is estimated as `warmwater_kwh / 58.15`, rounded to
0.001 m³. Each numeric sensor exposes a `monthly_history` attribute with ISO month
dates. Sensors have no statistics state class; this version does not backfill
Recorder statistics or supply the Energy dashboard.

## Command-line exporter

The exporter uses Python 3 and only the standard library. All credentials below
are placeholders; replace them locally with your own values. Real command-line
arguments may be retained in shell history or visible in the process list.

Export selected months as JSON:

```sh
python3 scripts/uvi_downloader.py \
  --liegenschaft-id 'PROPERTY_ID' \
  --login-email 'name@example.invalid' \
  --launch-token 'LAUNCH_TOKEN' \
  --password 'PORTAL_PASSWORD' \
  --month 'Januar 2026' \
  --month 'Dezember 2025'
```

Alternatively use `--launch-url` with the full original portal link instead of
`--liegenschaft-id`, `--login-email` and `--launch-token`.

Export all available months as CSV:

```sh
python3 scripts/uvi_downloader.py \
  --liegenschaft-id 'PROPERTY_ID' \
  --login-email 'name@example.invalid' \
  --launch-token 'LAUNCH_TOKEN' \
  --password 'PORTAL_PASSWORD' \
  --all-months --format csv --out export.csv
```

The exporter fetches all months only when `--all-months` is specified. Output
fields are `month`, `coldwater_m3`, `heating_kwh`, `warmwater_kwh` and
`warmwater_m3`. `month` is the first day of the reporting month, e.g. `2026-01-01`.
Use `--debug --debug-log uvi-debug.log` for progress diagnostics. Request bodies,
response bodies, credential URLs and session identifiers are excluded from
error and debug output. Logs still contain operational metadata such as months
and record counts; review them before sharing.

## Development

Run the offline checks without portal credentials or third-party dependencies:

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q custom_components scripts tests
python3 scripts/check_publication.py --history
```

All protocol fixtures under `tests/fixtures/` are synthetic. Do not replace them
with real portal captures. GitHub Actions runs these checks on pushes and pull
requests. Full setup, reauthentication, sensor rendering and HACS installation
still need verification in a running Home Assistant instance.

## Publication and privacy

The Git remote is `https://github.com/mosenberg/uvi-homeassistant.git`; the local
publication branch is `main`. After reviewing and committing the prepared files,
run the checks above and publish with:

```sh
git push --set-upstream origin main
```

The initial push requires no force option. The remote already has an initial MIT
license commit on `master`; `main` deliberately has independent, sanitized
history. After publishing, select `main` as the default branch on GitHub. The
old `master` license notice contains the owner's full name; review whether to
retain that branch before making the repository public.

GitHub visibility is managed separately; HACS requires a public repository. Do not include local captures,
consumption exports, credentials, logs, generated ZIPs or Python caches in commits.
The `.gitignore` rules exclude common private artifacts, and the publication
check inspects working files, the staged snapshot and all local Git refs when
`--history` is supplied. It flags common privacy issues; it is not a substitute
for reviewing the actual changes before publication.
