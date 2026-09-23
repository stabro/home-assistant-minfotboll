"""Sensor platform for Min Fotboll."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import MinFotbollCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up match and next-match sensors for each selected team."""
    coordinator: MinFotbollCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for team_id in coordinator.data:
        entities.append(MinFotbollMatchSensor(coordinator, team_id))
        entities.append(MinFotbollNextMatchSensor(coordinator, team_id))
    async_add_entities(entities)


class MinFotbollBaseSensor(CoordinatorEntity[MinFotbollCoordinator], SensorEntity):
    """Base sensor for one Min Fotboll team."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: MinFotbollCoordinator, team_id: int) -> None:
        super().__init__(coordinator)
        self._team_id = team_id

    @property
    def _team(self) -> dict[str, Any]:
        return self.coordinator.data.get(self._team_id, {})

    @property
    def device_info(self) -> DeviceInfo:
        team = self._team
        return DeviceInfo(
            identifiers={(DOMAIN, str(self._team_id))},
            name=team.get("friendly_name") or f"Min Fotboll {self._team_id}",
            manufacturer="Min Fotboll / Sportswik",
            model="Följt lag",
        )

    @property
    def entity_picture(self) -> str | None:
        return self._team.get("logo_url")


class MinFotbollMatchSensor(MinFotbollBaseSensor):
    """Represent live/latest match result and event."""

    _attr_name = "Match"
    _attr_icon = "mdi:soccer"

    def __init__(self, coordinator: MinFotbollCoordinator, team_id: int) -> None:
        super().__init__(coordinator, team_id)
        self._attr_unique_id = f"min_fotboll_team_{team_id}"

    @property
    def native_value(self) -> str | None:
        return self._team.get("match", {}).get("score")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        match = self._team.get("match", {})
        return {key: value for key, value in match.items() if value is not None}


class MinFotbollNextMatchSensor(MinFotbollBaseSensor):
    """Represent the next scheduled match as a timestamp sensor."""

    _attr_name = "Nästa match"
    _attr_icon = "mdi:calendar-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: MinFotbollCoordinator, team_id: int) -> None:
        super().__init__(coordinator, team_id)
        self._attr_unique_id = f"min_fotboll_team_{team_id}_next_match"

    @property
    def native_value(self) -> datetime | None:
        value = self._team.get("next_match", {}).get("game_time")
        if not isinstance(value, str):
            return None
        parsed = dt_util.parse_datetime(value)
        return parsed

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        next_match = self._team.get("next_match", {})
        return {
            key: value
            for key, value in next_match.items()
            if key != "game_time" and value is not None
        }
