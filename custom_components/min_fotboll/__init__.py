"""Min Fotboll integration."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
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
_TEAM_UNIQUE_ID_RE = re.compile(r"^min_fotboll_team_(\d+)(?:_next_match)?$")


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

    await _async_cleanup_unselected_teams(hass, entry, selected)

    api = MinFotbollApi(async_get_clientsession(hass), token, update_token)
    coordinator = MinFotbollCoordinator(hass, api, selected)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_cleanup_unselected_teams(
    hass: HomeAssistant,
    entry: ConfigEntry,
    selected_team_ids: list[int] | None,
) -> None:
    """Remove stale entities/devices when a team is deselected."""
    if selected_team_ids is None:
        return

    selected = {int(team_id) for team_id in selected_team_ids}
    entity_registry = er.async_get(hass)
    stale_team_ids: set[int] = set()

    for entity_entry in er.async_entries_for_config_entry(
        entity_registry, entry.entry_id
    ):
        match = _TEAM_UNIQUE_ID_RE.match(entity_entry.unique_id)
        if not match:
            continue
        team_id = int(match.group(1))
        if team_id in selected:
            continue
        stale_team_ids.add(team_id)
        entity_registry.async_remove(entity_entry.entity_id)

    if not stale_team_ids:
        return

    device_registry = dr.async_get(hass)
    for team_id in stale_team_ids:
        device = device_registry.async_get_device_by_identifier(
            (DOMAIN, str(team_id)), entry.entry_id
        )
        if device is not None:
            device_registry.async_remove_device(device.id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate older Min Fotboll config entries."""
    if entry.version == 1:
        hass.config_entries.async_update_entry(entry, version=2)
        return True

    return entry.version == 2
