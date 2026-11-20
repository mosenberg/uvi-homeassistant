"""Home Assistant setup for UVI Service."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .coordinator import UviCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = UviCoordinator(hass, entry)
    await coordinator.async_load_cache()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, [Platform.SENSOR])
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, [Platform.SENSOR])


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    from homeassistant.helpers.storage import Store

    await Store(hass, 1, f"uvi_service.{entry.entry_id}").async_remove()
