"""Config flow for Hikvision User & PIN Control."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .client import HikvisionClient
from .const import (
    CONF_ALLOWED_EVENTS,
    CONF_BASE_URL,
    CONF_PASSWORD,
    CONF_PROTECTED_EMPLOYEE_NOS,
    CONF_SCAN_INTERVAL,
    CONF_TIMEOUT,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DEFAULT_TIMEOUT,
    DEFAULT_VERIFY_SSL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): bool,
    }
)


class HikvisionUserPinConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hikvision User & PIN Control."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Check for duplicate entries
            await self.async_set_unique_id(user_input[CONF_BASE_URL])
            self._abort_if_unique_id_configured()

            # Test the connection
            client = HikvisionClient(
                user_input[CONF_BASE_URL],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
                verify=user_input.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
                timeout=DEFAULT_TIMEOUT,
            )
            try:
                status = await self.hass.async_add_executor_job(
                    client.test_connection
                )
                if status == "ok":
                    return self.async_create_entry(
                        title=user_input[CONF_BASE_URL],
                        data=user_input,
                    )
                if status == "auth_failed":
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during connection test")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> HikvisionUserPinOptionsFlow:
        """Return the options flow handler."""
        return HikvisionUserPinOptionsFlow(config_entry)


class HikvisionUserPinOptionsFlow(OptionsFlow):
    """Handle options for Hikvision User & PIN Control."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_TIMEOUT,
                        default=options.get(CONF_TIMEOUT, DEFAULT_TIMEOUT),
                    ): vol.Coerce(float),
                    vol.Optional(
                        CONF_PROTECTED_EMPLOYEE_NOS,
                        default=options.get(CONF_PROTECTED_EMPLOYEE_NOS, ""),
                    ): str,
                    vol.Optional(
                        CONF_ALLOWED_EVENTS,
                        default=options.get(CONF_ALLOWED_EVENTS, ""),
                    ): str,
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=options.get(
                            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                        ),
                    ): vol.Coerce(int),
                }
            ),
        )
