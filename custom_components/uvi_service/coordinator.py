"""Daily refresh and persisted monthly consumption."""

from datetime import timedelta
import logging

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CannotConnect, InvalidAuth, UviApi
from .const import DOMAIN

LOGGER = logging.getLogger(__name__)


class UviCoordinator(DataUpdateCoordinator):
    def __init__(self, hass, entry):
        super().__init__(hass, LOGGER, name=DOMAIN, config_entry=entry,
                         update_interval=timedelta(days=1))
        self.api = UviApi(entry.data)
        self.store = Store(hass, 1, f"{DOMAIN}.{entry.entry_id}")
        self.months = {}

    async def async_load_cache(self):
        self.months = await self.store.async_load() or {}

    async def _async_update_data(self):
        try:
            rows = await self.api.fetch()
        except InvalidAuth:
            raise ConfigEntryAuthFailed("UVI authentication failed") from None
        except CannotConnect:
            raise UpdateFailed("UVI service is unavailable or its protocol changed") from None
        if not rows:
            raise UpdateFailed("UVI returned no monthly data")
        self.months.update({row["month"]: row for row in rows})
        await self.store.async_save(self.months)
        LOGGER.debug("Updated %d monthly records", len(rows))
        return self.months[max(self.months)]
