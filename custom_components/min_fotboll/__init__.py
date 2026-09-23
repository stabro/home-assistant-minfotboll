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
    CONF_SELECTED_TEAMS,
    CONF_SERVER_TIME,
    DOMAIN,
)
from .coordinator import MinFotbollCoordinator

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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

    selected = entry.options.get(
        CONF_SELECTED_TEAMS,
        entry.data.get(CONF_SELECTED_TEAMS),
    )

    api = MinFotbollApi(async_get_clientsession(hass), token, update_token)
    coordinator = MinFotbollCoordinator(hass, api, selected)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older Min Fotboll config entries."""
    if entry.version == 1:
        # v0.1.2 introduced team selection. Leave selected_teams unset on
        # migrated entries so the coordinator initially discovers all current
        # season teams; the user can then choose teams from Options/Configure.
        hass.config_entries.async_update_entry(entry, version=2)
        return True

    return entry.version == 2
