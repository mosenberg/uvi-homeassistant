"""Configure credentials through Home Assistant's UI."""

import hashlib

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .api import CannotConnect, InvalidAuth, UviApi
from .const import DOMAIN


def schema(defaults=None):
    defaults = defaults or {}
    fields = {}
    for key in ("property_id", "email", "password", "launch_token"):
        field = vol.Required(key, default=defaults[key]) if key in defaults and key not in ("password", "launch_token") else vol.Required(key)
        kind = selector.TextSelectorType.PASSWORD if key in ("password", "launch_token") else selector.TextSelectorType.TEXT
        fields[field] = selector.TextSelector(selector.TextSelectorConfig(type=kind))
    return vol.Schema(fields)


class UviConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        return await self._form("user", user_input)

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        return await self._form("reauth_confirm", user_input)

    async def async_step_reconfigure(self, user_input=None):
        return await self._form("reconfigure", user_input)

    async def _form(self, step, user_input):
        entry = None
        if step == "reauth_confirm":
            entry = self._get_reauth_entry()
        elif step == "reconfigure":
            entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            identity = hashlib.sha256((user_input["property_id"] + "\0" + user_input["email"].strip().lower()).encode()).hexdigest()
            if entry and identity != entry.unique_id:
                errors["base"] = "account_mismatch"
            else:
                try:
                    await UviApi(user_input).fetch()
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(identity)
                    if entry:
                        return self.async_update_reload_and_abort(entry, data_updates=user_input)
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(title="UVI Service", data=user_input)
        return self.async_show_form(step_id=step, data_schema=schema(entry.data if entry else user_input), errors=errors)
