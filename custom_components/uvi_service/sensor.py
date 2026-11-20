"""Latest reported monthly consumption, with monthly history attributes."""

from datetime import date

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorEntityDescription
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

DESCRIPTIONS = (
    SensorEntityDescription(key="coldwater_m3", name="Cold water", device_class=SensorDeviceClass.WATER, native_unit_of_measurement=UnitOfVolume.CUBIC_METERS, icon="mdi:water"),
    SensorEntityDescription(key="heating_kwh", name="Heating", device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, icon="mdi:radiator"),
    SensorEntityDescription(key="warmwater_kwh", name="Hot water energy", device_class=SensorDeviceClass.ENERGY, native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR, icon="mdi:water-boiler"),
    SensorEntityDescription(key="warmwater_m3", name="Hot water volume (estimated)", device_class=SensorDeviceClass.WATER, native_unit_of_measurement=UnitOfVolume.CUBIC_METERS, icon="mdi:water-thermometer"),
    SensorEntityDescription(key="month", name="Reporting month", device_class=SensorDeviceClass.DATE, icon="mdi:calendar-month"),
)
PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(UviSensor(entry.runtime_data, entry, description) for description in DESCRIPTIONS)


class UviSensor(CoordinatorEntity, SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, description):
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.unique_id}_{description.key}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.unique_id)}, name="UVI Service", manufacturer="UVI Service", model="Monthly consumption")

    @property
    def native_value(self):
        value = self.coordinator.data.get(self.entity_description.key)
        if value is None:
            return None
        return date.fromisoformat(value) if self.entity_description.key == "month" else float(value)

    @property
    def extra_state_attributes(self):
        key = self.entity_description.key
        result = {"reporting_month": self.coordinator.data["month"]}
        if key != "month":
            result["monthly_history"] = {month: (float(row[key]) if row.get(key) is not None else None)
                                         for month, row in sorted(self.coordinator.months.items())}
        if key == "warmwater_m3":
            result["calculation"] = "warmwater_kwh / 58.15 (assumed 60 C hot, 10 C cold)"
        return result
