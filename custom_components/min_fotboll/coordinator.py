"""Data coordinator for Min Fotboll."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import MinFotbollApi, MinFotbollAuthError, MinFotbollConnectionError
from .const import (
    DOMAIN,
    STATUS_CANCELLED,
    STATUS_FINISHED,
    STATUS_INTERRUPTED,
    STATUS_LIVE,
    STATUS_POSTPONED,
    STATUS_UNKNOWN,
    STATUS_UPCOMING,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class MinFotbollCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Coordinate selected Min Fotboll teams."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: MinFotbollApi,
        selected_team_ids: list[int] | None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api
        self.selected_team_ids = (
            {int(team_id) for team_id in selected_team_ids}
            if selected_team_ids
            else None
        )

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        try:
            my_teams = await self.api.async_get_my_teams()
            teams = _current_season_teams(my_teams)

            if self.selected_team_ids is not None:
                teams = [
                    team
                    for team in teams
                    if int(team["TeamID"]) in self.selected_team_ids
                ]

            result: dict[int, dict[str, Any]] = {}
            for team in teams:
                team_id = int(team["TeamID"])

                coming_payload = await self.api.async_get_coming_team_games(team_id, 5)
                previous_payload = await self.api.async_get_previous_team_games(team_id)
                coming_games = _extract_games(coming_payload)
                previous_games = _extract_games(previous_payload)

                current_game = _pick_current_game(coming_games, previous_games)
                next_game = _pick_next_game(coming_games)

                timeline: dict[str, Any] = {}
                if current_game and current_game.get("GameID") and _should_load_timeline(current_game):
                    try:
                        timeline = await self.api.async_get_timeline(
                            int(current_game["GameID"])
                        )
                    except MinFotbollConnectionError as err:
                        _LOGGER.debug(
                            "Timeline unavailable for game %s: %s",
                            current_game.get("GameID"),
                            err,
                        )
                    else:
                        header = timeline.get("GameHeaderInfo")
                        if isinstance(header, dict):
                            current_game = header

                result[team_id] = _build_team_state(
                    team,
                    current_game,
                    next_game,
                    timeline,
                )

            return result
        except MinFotbollAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except MinFotbollConnectionError as err:
            raise UpdateFailed(f"Communication failed: {err}") from err
        except (KeyError, TypeError, ValueError) as err:
            raise UpdateFailed(f"Unexpected Min Fotboll response: {err}") from err


def _current_season_teams(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge current-season Roles and TeamsIFollow, deduplicated by TeamID."""
    current_year = str(datetime.now(timezone.utc).year)
    merged: dict[int, dict[str, Any]] = {}

    for group_name in ("Roles", "TeamsIFollow"):
        for season in payload.get(group_name, []):
            if not isinstance(season, dict) or str(season.get("Name")) != current_year:
                continue
            for team in season.get("Items", []):
                if not isinstance(team, dict) or not team.get("TeamID"):
                    continue
                if team.get("MemberFollowsTeam") is False:
                    continue
                merged[int(team["TeamID"])] = team

    return list(merged.values())


def _extract_games(payload: Any) -> list[dict[str, Any]]:
    """Extract game dictionaries from common Min Fotboll response shapes."""
    if isinstance(payload, list):
        return [
            item for item in payload
            if isinstance(item, dict) and item.get("GameID")
        ]
    if not isinstance(payload, dict):
        return []

    if payload.get("GameID"):
        return [payload]

    for key in (
        "Games",
        "ComingGames",
        "PreviousGames",
        "Items",
        "Result",
        "GameHeaderInfos",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            games = [
                item for item in value
                if isinstance(item, dict) and item.get("GameID")
            ]
            if games:
                return games

    for value in payload.values():
        if isinstance(value, list):
            games = [
                item for item in value
                if isinstance(item, dict) and item.get("GameID")
            ]
            if games:
                return games
    return []


def _parse_game_time(game: dict[str, Any]) -> datetime:
    value = game.get("GameTime")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _is_live(game: dict[str, Any]) -> bool:
    return bool(game.get("GameStatusID") == 2 or game.get("ClockIsRunning"))


def _is_finished(game: dict[str, Any]) -> bool:
    return bool(game.get("GameStatusID") == 3)


def _pick_current_game(
    coming_games: list[dict[str, Any]],
    previous_games: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Pick live game first, otherwise latest completed match."""
    all_games = coming_games + previous_games
    live = [game for game in all_games if _is_live(game)]
    if live:
        return max(live, key=_parse_game_time)

    finished = [game for game in previous_games if _is_finished(game)]
    if finished:
        return max(finished, key=_parse_game_time)

    if previous_games:
        return max(previous_games, key=_parse_game_time)

    return None


def _pick_next_game(games: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the nearest future/non-finished game."""
    now = datetime.now(timezone.utc)
    upcoming = [
        game
        for game in games
        if not _is_finished(game)
        and (_parse_game_time(game) >= now or _is_live(game))
    ]
    if not upcoming:
        return None
    return min(upcoming, key=_parse_game_time)


def _should_load_timeline(game: dict[str, Any]) -> bool:
    return bool(
        game.get("GameStatusID") in (2, 3)
        or game.get("ClockIsRunning")
        or game.get("LatestEventTime")
    )


def _build_team_state(
    team: dict[str, Any],
    current_game: dict[str, Any] | None,
    next_game: dict[str, Any] | None,
    timeline: dict[str, Any],
) -> dict[str, Any]:
    club_name = team.get("ClubName") or ""
    team_name = (
        team.get("DisplayName")
        or team.get("TeamName")
        or team.get("Name")
        or ""
    )
    friendly_name = f"{club_name} {team_name}".strip()

    data: dict[str, Any] = {
        "team_id": team.get("TeamID"),
        "team_name": team_name,
        "club_name": club_name,
        "friendly_name": friendly_name,
        "logo_url": team.get("ClubLogoURL"),
        "match": _build_match(current_game, timeline),
        "next_match": _build_next_match(next_game, int(team["TeamID"])),
    }
    return data


def _build_match(
    game: dict[str, Any] | None,
    timeline: dict[str, Any],
) -> dict[str, Any]:
    if not game:
        return {
            "game_id": None,
            "score": None,
            "status": STATUS_UNKNOWN,
            "latest_event": None,
            "minute": None,
        }

    latest = _latest_event(timeline)
    status = _game_status(game, latest)
    home_score = game.get("HomeTeamScore")
    away_score = game.get("AwayTeamScore")
    score = None
    if status in (STATUS_LIVE, STATUS_FINISHED):
        if home_score is not None and away_score is not None:
            score = f"{home_score}-{away_score}"

    return {
        "game_id": game.get("GameID"),
        "home_team": game.get("HomeTeamDisplayName"),
        "away_team": game.get("AwayTeamDisplayName"),
        "home_team_id": game.get("HomeTeamID"),
        "away_team_id": game.get("AwayTeamID"),
        "game_time": game.get("GameTime"),
        "arena": game.get("ArenaName"),
        "score": score,
        "home_score": home_score,
        "away_score": away_score,
        "status": status,
        "latest_event": latest.get("Text") if latest else None,
        "minute": latest.get("GameMinute") if latest else None,
        "latest_event_short": latest.get("ShortText") if latest else None,
        "latest_event_details": latest.get("DetailsText") if latest else None,
    }


def _build_next_match(
    game: dict[str, Any] | None,
    team_id: int,
) -> dict[str, Any]:
    if not game:
        return {
            "game_id": None,
            "game_time": None,
            "status": STATUS_UNKNOWN,
        }

    home_team_id = game.get("HomeTeamID")
    away_team_id = game.get("AwayTeamID")
    is_home = home_team_id == team_id
    opponent = (
        game.get("AwayTeamDisplayName")
        if is_home
        else game.get("HomeTeamDisplayName")
    )

    return {
        "game_id": game.get("GameID"),
        "game_time": game.get("GameTime"),
        "home_team": game.get("HomeTeamDisplayName"),
        "away_team": game.get("AwayTeamDisplayName"),
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "opponent": opponent,
        "home_away": "hemma" if is_home else "borta",
        "arena": game.get("ArenaName"),
        "status": STATUS_LIVE if _is_live(game) else STATUS_UPCOMING,
    }


def _latest_event(timeline: dict[str, Any]) -> dict[str, Any] | None:
    for item in timeline.get("TimelineBlurbs", []) if isinstance(timeline, dict) else []:
        if not isinstance(item, dict) or item.get("Deleted") or item.get("IsAd"):
            continue
        event = item.get("EREventInfo")
        if isinstance(event, dict):
            return event
    return None


def _game_status(game: dict[str, Any], latest: dict[str, Any] | None) -> str:
    if game.get("Cancelled"):
        return STATUS_CANCELLED
    if game.get("Postponed"):
        return STATUS_POSTPONED
    if game.get("Interrupted"):
        return STATUS_INTERRUPTED
    if latest and latest.get("IsGameEnd"):
        return STATUS_FINISHED
    if _is_finished(game):
        return STATUS_FINISHED
    if _is_live(game):
        return STATUS_LIVE
    return STATUS_UNKNOWN
