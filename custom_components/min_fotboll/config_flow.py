"""Config flow for Min Fotboll."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import (
    MinFotbollApi,
    MinFotbollAuthError,
    MinFotbollConnectionError,
    jwt_member_id,
    parse_token_json,
)
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES,
    CONF_REFRESH_TOKEN,
    CONF_SERVER_TIME,
    CONF_TOKEN_JSON,
    DOMAIN,
)


class MinFotbollConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Min Fotboll."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Set up Min Fotboll using the JWT_token cookie JSON."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                token = parse_token_json(user_input[CONF_TOKEN_JSON])
                api = MinFotbollApi(async_get_clientsession(self.hass), token)
                header = await api.async_validate()
            except MinFotbollAuthError:
                errors["base"] = "invalid_auth"
            except MinFotbollConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                member_id = jwt_member_id(token["AccessToken"])
                if member_id:
                    await self.async_set_unique_id(member_id)
                    self._abort_if_unique_id_configured()

                title = header.get("FirstName") or "Min Fotboll"
                return self.async_create_entry(
                    title=f"Min Fotboll – {title}",
                    data={
                        CONF_ACCESS_TOKEN: token["AccessToken"],
                        CONF_REFRESH_TOKEN: token["RefreshToken"],
                        CONF_EXPIRES: token.get("Expires"),
                        CONF_SERVER_TIME: token.get("ServerTime"),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN_JSON): str}),
            errors=errors,
        )
