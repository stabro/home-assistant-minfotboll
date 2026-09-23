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
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class MinFotbollCoordinator(DataUpdateCoordinator[dict[int, dict[str, Any]]]):
    """Coordinate updates for all followed teams in one account."""

    def __init__(self, hass: HomeAssistant, api: MinFotbollApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
        )
        self.api = api

    async def _async_update_data(self) -> dict[int, dict[str, Any]]:
        """Update all followed teams from the verified main-view payload."""
        try:
            main = await self.api.async_get_main()
            teams = [
                team
                for team in main.get("Teams", [])
                if isinstance(team, dict) and team.get("MemberFollowsTeam", True)
            ]
            games = _main_games(main)

            result: dict[int, dict[str, Any]] = {}
            for team in teams:
                team_id = int(team["TeamID"])
                team_games = [
                    game for game in games if _game_belongs_to_team(game, team_id)
                ]
                game = _pick_game(team_games)

                timeline: dict[str, Any] = {}
                if game and game.get("GameID") and _should_load_timeline(game):
                    try:
                        timeline = await self.api.async_get_timeline(int(game["GameID"]))
                    except MinFotbollConnectionError as err:
                        # A missing timeline must not make the whole integration unavailable.
                        _LOGGER.debug(
                            "Timeline unavailable for game %s: %s",
                            game.get("GameID"),
                            err,
                        )
                    else:
                        if isinstance(timeline.get("GameHeaderInfo"), dict):
                            game = timeline["GameHeaderInfo"]

                result[team_id] = _build_team_state(team, game, timeline)

            return result
        except MinFotbollAuthError as err:
            raise UpdateFailed(f"Authentication failed: {err}") from err
        except MinFotbollConnectionError as err:
            raise UpdateFailed(f"Communication failed: {err}") from err
        except (KeyError, TypeError, ValueError) as err:
            raise UpdateFailed(f"Unexpected Min Fotboll response: {err}") from err


def _main_games(main: dict[str, Any]) -> list[dict[str, Any]]:
    """Collect game headers already returned by initmain.

    Min Fotboll's verified web response includes ComingGames and may include
    recent completed games in TeamsIFollowBlurbs. Using those avoids depending
    on undocumented teamapi endpoints.
    """
    games: dict[int, dict[str, Any]] = {}

    for item in main.get("ComingGames", []):
        if isinstance(item, dict) and item.get("GameID"):
            games[int(item["GameID"])] = item

    for blurb in main.get("TeamsIFollowBlurbs", []):
        if not isinstance(blurb, dict) or blurb.get("Deleted") or blurb.get("IsAd"):
            continue
        header = blurb.get("GameHeaderInfo")
        if isinstance(header, dict) and header.get("GameID"):
            games[int(header["GameID"])] = header

    return list(games.values())


def _game_belongs_to_team(game: dict[str, Any], team_id: int) -> bool:
    """Return True when a game explicitly references the followed team ID."""
    return team_id in (game.get("HomeTeamID"), game.get("AwayTeamID"))


def _parse_game_time(game: dict[str, Any]) -> datetime:
    value = game.get("GameTime")
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.min.replace(tzinfo=timezone.utc)


def _pick_game(games: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Choose live first, then latest finished, then nearest upcoming."""
    if not games:
        return None

    live = [
        game
        for game in games
        if game.get("GameStatusID") == 2 or game.get("ClockIsRunning")
    ]
    if live:
        return max(live, key=_parse_game_time)

    finished = [game for game in games if game.get("GameStatusID") == 3]
    if finished:
        return max(finished, key=_parse_game_time)

    upcoming = [game for game in games if game.get("GameStatusID") == 1]
    if upcoming:
        return min(upcoming, key=_parse_game_time)

    return max(games, key=_parse_game_time)


def _should_load_timeline(game: dict[str, Any]) -> bool:
    """Only query the timeline when a game is live or completed."""
    return bool(
        game.get("GameStatusID") in (2, 3)
        or game.get("ClockIsRunning")
        or game.get("LatestEventTime")
    )


def _build_team_state(
    team: dict[str, Any],
    game: dict[str, Any] | None,
    timeline: dict[str, Any],
) -> dict[str, Any]:
    """Create the compact representation consumed by sensor entities."""
    club_name = team.get("ClubName") or ""
    team_name = team.get("DisplayName") or team.get("TeamName") or team.get("Name") or ""
    friendly_name = f"{club_name} {team_name}".strip()

    data: dict[str, Any] = {
        "team_id": team.get("TeamID"),
        "team_name": team_name,
        "club_name": club_name,
        "friendly_name": friendly_name,
        "logo_url": team.get("ClubLogoURL"),
        "game_id": None,
        "score": None,
        "status": STATUS_UNKNOWN,
        "latest_event": None,
        "minute": None,
    }
    if not game:
        return data

    status = _game_status(game, _latest_event(timeline))
    home_score = str(game.get("HomeTeamScore", ""))
    away_score = str(game.get("AwayTeamScore", ""))

    # Avoid presenting an unplayed 0-0 fixture as a result.
    score = None
    if status in (STATUS_LIVE, STATUS_FINISHED):
        if home_score != "" and away_score != "":
            score = f"{home_score}-{away_score}"

    latest = _latest_event(timeline)
    data.update(
        {
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
    )
    return data


def _latest_event(timeline: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest real event, ignoring ads and deleted timeline rows."""
    for item in timeline.get("TimelineBlurbs", []) if isinstance(timeline, dict) else []:
        if not isinstance(item, dict) or item.get("Deleted") or item.get("IsAd"):
            continue
        event = item.get("EREventInfo")
        if isinstance(event, dict):
            return event
    return None


def _game_status(game: dict[str, Any], latest: dict[str, Any] | None) -> str:
    """Translate the game state to a compact Swedish status."""
    if game.get("Cancelled"):
        return STATUS_CANCELLED
    if game.get("Postponed"):
        return STATUS_POSTPONED
    if game.get("Interrupted"):
        return STATUS_INTERRUPTED
    if latest and latest.get("IsGameEnd"):
        return STATUS_FINISHED
    status_id = game.get("GameStatusID")
    if status_id == 3:
        return STATUS_FINISHED
    if status_id == 2 or game.get("ClockIsRunning"):
        return STATUS_LIVE
    return STATUS_UNKNOWN
