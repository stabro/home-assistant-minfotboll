"""Config flow for Min Fotboll."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig, SelectSelectorMode

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
    CONF_SELECTED_TEAMS,
    CONF_SERVER_TIME,
    CONF_TOKEN_JSON,
    DOMAIN,
)


def _current_season_teams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge current-season Roles and TeamsIFollow, deduplicated by TeamID."""
    now = datetime.now(timezone.utc)
    current_year = str(now.year)
    merged: dict[int, dict[str, Any]] = {}

    for group_name in ("Roles", "TeamsIFollow"):
        for season in payload.get(group_name, []):
            if not isinstance(season, dict):
                continue
            if str(season.get("Name")) != current_year:
                continue
            for team in season.get("Items", []):
                if not isinstance(team, dict) or not team.get("TeamID"):
                    continue
                if team.get("MemberFollowsTeam") is False:
                    continue
                merged[int(team["TeamID"])] = team

    return sorted(
        merged.values(),
        key=lambda team: (
            str(team.get("ClubName") or ""),
            str(team.get("DisplayName") or team.get("TeamName") or ""),
        ),
    )


def _team_options(teams: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "value": str(team["TeamID"]),
            "label": f'{team.get("ClubName") or ""} – '
            f'{team.get("DisplayName") or team.get("TeamName") or team["TeamID"]}',
        }
        for team in teams
    ]


class MinFotbollConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Min Fotboll."""

    VERSION = 2

    def __init__(self) -> None:
        self._token: dict[str, Any] | None = None
        self._header: dict[str, Any] = {}
        self._teams: list[dict[str, Any]] = []
        self._member_id: str | None = None

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Authenticate using the JWT_token cookie JSON."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                token = parse_token_json(user_input[CONF_TOKEN_JSON])
                api = MinFotbollApi(async_get_clientsession(self.hass), token)
                header = await api.async_validate()
                teams_payload = await api.async_get_my_teams()
                teams = _current_season_teams(teams_payload)
            except MinFotbollAuthError:
                errors["base"] = "invalid_auth"
            except MinFotbollConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                errors["base"] = "unknown"
            else:
                self._token = token
                self._header = header
                self._teams = teams
                self._member_id = jwt_member_id(token["AccessToken"])
                if self._member_id:
                    await self.async_set_unique_id(self._member_id)
                    self._abort_if_unique_id_configured()
                return await self.async_step_teams()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN_JSON): str}),
            errors=errors,
        )

    async def async_step_teams(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Let the user choose which current-season teams to create."""
        if not self._token:
            return await self.async_step_user()

        options = _team_options(self._teams)
        if not options:
            return self.async_abort(reason="no_teams")

        if user_input is not None:
            selected = [int(value) for value in user_input[CONF_SELECTED_TEAMS]]
            title = self._header.get("FirstName") or "Min Fotboll"
            return self.async_create_entry(
                title=f"Min Fotboll – {title}",
                data={
                    CONF_ACCESS_TOKEN: self._token["AccessToken"],
                    CONF_REFRESH_TOKEN: self._token["RefreshToken"],
                    CONF_EXPIRES: self._token.get("Expires"),
                    CONF_SERVER_TIME: self._token.get("ServerTime"),
                    CONF_SELECTED_TEAMS: selected,
                },
            )

        default_values = [item["value"] for item in options]
        return self.async_show_form(
            step_id="teams",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SELECTED_TEAMS,
                        default=default_values,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MinFotbollOptionsFlow:
        """Create the options flow."""
        return MinFotbollOptionsFlow()


class MinFotbollOptionsFlow(config_entries.OptionsFlowWithReload):
    """Allow changing selected teams later and reload after saving."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        token = {
            "AccessToken": self.config_entry.data[CONF_ACCESS_TOKEN],
            "RefreshToken": self.config_entry.data[CONF_REFRESH_TOKEN],
            "Expires": self.config_entry.data.get(CONF_EXPIRES),
            "ServerTime": self.config_entry.data.get(CONF_SERVER_TIME),
        }
        api = MinFotbollApi(async_get_clientsession(self.hass), token)

        try:
            payload = await api.async_get_my_teams()
            teams = _current_season_teams(payload)
        except MinFotbollAuthError:
            return self.async_abort(reason="invalid_auth")
        except MinFotbollConnectionError:
            return self.async_abort(reason="cannot_connect")

        options = _team_options(teams)
        available = {item["value"] for item in options}
        existing = self.config_entry.options.get(
            CONF_SELECTED_TEAMS,
            self.config_entry.data.get(CONF_SELECTED_TEAMS, []),
        )
        defaults = [str(team_id) for team_id in existing if str(team_id) in available]
        if not defaults:
            defaults = [item["value"] for item in options]

        if user_input is not None:
            selected = [int(value) for value in user_input[CONF_SELECTED_TEAMS]]
            return self.async_create_entry(
                title="",
                data={CONF_SELECTED_TEAMS: selected},
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SELECTED_TEAMS,
                        default=defaults,
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=options,
                            multiple=True,
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )
