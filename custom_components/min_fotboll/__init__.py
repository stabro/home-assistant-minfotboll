"""Min Fotboll integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MinFotbollApi
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_EXPIRES,
    CONF_REFRESH_TOKEN,
    CONF_SERVER_TIME,
    DOMAIN,
)
from .coordinator import MinFotbollCoordinator

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Min Fotboll from a config entry."""
    token = {
        "AccessToken": entry.data[CONF_ACCESS_TOKEN],
        "RefreshToken": entry.data[CONF_REFRESH_TOKEN],
        "Expires": entry.data.get(CONF_EXPIRES),
        "ServerTime": entry.data.get(CONF_SERVER_TIME),
    }

    def update_token(new_token: dict[str, Any]) -> None:
        data = dict(entry.data)
        data.update(
            {
                CONF_ACCESS_TOKEN: new_token.get("AccessToken"),
                CONF_REFRESH_TOKEN: new_token.get("RefreshToken"),
                CONF_EXPIRES: new_token.get("Expires"),
                CONF_SERVER_TIME: new_token.get("ServerTime"),
            }
        )
        hass.config_entries.async_update_entry(entry, data=data)

    api = MinFotbollApi(async_get_clientsession(hass), token, update_token)
    coordinator = MinFotbollCoordinator(hass, api)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
