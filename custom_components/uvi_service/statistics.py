"""Import UVI monthly totals as separate external recorder statistics."""

import logging

from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.util.unit_conversion import EnergyConverter, VolumeConverter

from .const import DOMAIN
from .statistics_data import build_monthly_statistics

LOGGER = logging.getLogger(__name__)

SERIES = {
    "coldwater_m3": ("Cold water", UnitOfVolume.CUBIC_METERS, VolumeConverter.UNIT_CLASS),
    "heating_kwh": ("Heating energy", UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS),
    "warmwater_kwh": ("Hot water energy", UnitOfEnergy.KILO_WATT_HOUR, EnergyConverter.UNIT_CLASS),
    "warmwater_m3": ("Hot water volume (estimated)", UnitOfVolume.CUBIC_METERS, VolumeConverter.UNIT_CLASS),
}


def import_monthly_statistics(hass, entry_id, months):
    """Queue idempotent imports, including revisions to older months."""
    for field, (name, unit, unit_class) in SERIES.items():
        try:
            rows = build_monthly_statistics(months, field, hass.config.time_zone)
        except (ValueError, TypeError, OverflowError):
            LOGGER.error("Cannot import %s statistics: invalid monthly data", field)
            continue
        if not rows:
            continue
        metadata = {
            "mean_type": StatisticMeanType.NONE,
            "has_sum": True,
            "name": f"UVI Service {name}",
            "source": DOMAIN,
            "statistic_id": f"{DOMAIN}:{entry_id.lower()}_{field}",
            "unit_class": unit_class,
            "unit_of_measurement": unit,
        }
        async_add_external_statistics(hass, metadata, rows)
        LOGGER.info("Queued %d monthly values for %s statistics", len(rows) - 1, field)
