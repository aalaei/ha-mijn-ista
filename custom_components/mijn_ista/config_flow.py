"""Config flow for mijn.ista.nl integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import MijnIstaAPI, MijnIstaAuthError, MijnIstaConnectionError
from .const import CONF_LANGUAGE, CONF_UPDATE_INTERVAL, DEFAULT_LANGUAGE, DEFAULT_UPDATE_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

_STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
        vol.Required(CONF_LANGUAGE, default=DEFAULT_LANGUAGE): SelectSelector(
            SelectSelectorConfig(
                options=["en", "nl"],
                mode=SelectSelectorMode.LIST,
                translation_key="language",
            )
        ),
        vol.Required(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.SLIDER, min=1, max=24, step=1)
        ),
    }
)


class MijnIstaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for mijn.ista.nl."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return MijnIstaOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(user_input[CONF_USERNAME].lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass)
            api = MijnIstaAPI(
                session,
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )

            display_name: str | None = None
            try:
                await api.authenticate()
                user_data = await api.get_user_values()
                display_name = user_data.get("DisplayName", user_input[CONF_USERNAME])
            except MijnIstaAuthError:
                errors["base"] = "invalid_auth"
            except MijnIstaConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error during mijn.ista.nl config flow")
                errors["base"] = "unknown"

            if not errors:
                return self.async_create_entry(
                    title=f"ista NL — {display_name}",
                    data={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_LANGUAGE: user_input[CONF_LANGUAGE],
                    },
                    options={
                        CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL]),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_STEP_USER_SCHEMA,
            errors=errors,
        )


class MijnIstaOptionsFlowHandler(config_entries.OptionsFlowWithConfigEntry):
    """Handle options flow for mijn.ista.nl."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ):
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_UPDATE_INTERVAL: int(user_input[CONF_UPDATE_INTERVAL])},
            )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=self.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): NumberSelector(
                    NumberSelectorConfig(
                        mode=NumberSelectorMode.SLIDER, min=1, max=24, step=1
                    )
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
