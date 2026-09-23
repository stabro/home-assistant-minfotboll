"""Sensor platform for Min Fotboll."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MinFotbollCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Min Fotboll team sensors."""
    coordinator: MinFotbollCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        MinFotbollTeamSensor(coordinator, team_id)
        for team_id in coordinator.data
    )


class MinFotbollTeamSensor(CoordinatorEntity[MinFotbollCoordinator], SensorEntity):
    """Represent the latest/live match for one followed team."""

    _attr_has_entity_name = True
    _attr_name = "Match"
    _attr_icon = "mdi:soccer"

    def __init__(self, coordinator: MinFotbollCoordinator, team_id: int) -> None:
        super().__init__(coordinator)
        self._team_id = team_id
        self._attr_unique_id = f"min_fotboll_team_{team_id}"

    @property
    def _team(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._team_id, {})

    @property
    def native_value(self) -> str | None:
        """Return the current or latest score."""
        return self._team.get("score")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return match metadata."""
        team = self._team
        return {
            key: value
            for key, value in team.items()
            if key not in {"friendly_name", "logo_url"} and value is not None
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Group the entity under a team device."""
        team = self._team
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._team_id))},
            name=team.get("friendly_name") or f"Min Fotboll {self._team_id}",
            manufacturer="Min Fotboll / Sportswik",
            model="Följt lag",
        )

    @property
    def entity_picture(self) -> str | None:
        """Return the club logo when available."""
        return self._team.get("logo_url")
