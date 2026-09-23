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
        try:
            main = await self.api.async_get_main()
            teams = [
                team
                for team in main.get("Teams", [])
                if isinstance(team, dict) and team.get("MemberFollowsTeam", True)
            ]

            result: dict[int, dict[str, Any]] = {}
            for team in teams:
                team_id = int(team["TeamID"])
                live_games = _extract_games(
                    await self.api.async_get_live_team_games(team_id)
                )
                if live_games:
                    game = _pick_latest(live_games)
                else:
                    previous_games = _extract_games(
                        await self.api.async_get_previous_team_games(team_id)
                    )
                    game = _pick_latest(previous_games)

                timeline: dict[str, Any] = {}
                if game and game.get("GameID"):
                    timeline = await self.api.async_get_timeline(int(game["GameID"]))
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


def _extract_games(payload: Any) -> list[dict[str, Any]]:
    """Extract game dictionaries from the API's varying response shapes."""
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict) and item.get("GameID")]
    if not isinstance(payload, dict):
        return []

    for key in ("Games", "PreviousGames", "ComingGames", "Items", "Result"):
        value = payload.get(key)
        if isinstance(value, list):
            games = [item for item in value if isinstance(item, dict) and item.get("GameID")]
            if games:
                return games

    for value in payload.values():
        if isinstance(value, list):
            games = [item for item in value if isinstance(item, dict) and item.get("GameID")]
            if games:
                return games
    return []


def _pick_latest(games: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the newest game from an API game list."""
    if not games:
        return None

    def game_time(game: dict[str, Any]) -> datetime:
        value = game.get("GameTime")
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    return max(games, key=game_time)


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

    home_score = str(game.get("HomeTeamScore", ""))
    away_score = str(game.get("AwayTeamScore", ""))
    score = f"{home_score}-{away_score}" if home_score != "" and away_score != "" else None

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
            "status": _game_status(game, latest),
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
