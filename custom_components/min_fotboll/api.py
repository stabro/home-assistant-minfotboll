"""API client for Min Fotboll."""

from __future__ import annotations

from collections.abc import Callable
import base64
import json
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_BASE_URL, PLATFORM_ID


class MinFotbollError(Exception):
    """Base error for Min Fotboll."""


class MinFotbollAuthError(MinFotbollError):
    """Authentication failed."""


class MinFotbollConnectionError(MinFotbollError):
    """Connection to Min Fotboll failed."""


TokenUpdateCallback = Callable[[dict[str, Any]], None]


class MinFotbollApi:
    """Small asynchronous client for the Min Fotboll web API."""

    def __init__(
        self,
        session: ClientSession,
        token: dict[str, Any],
        token_update_callback: TokenUpdateCallback | None = None,
    ) -> None:
        self._session = session
        self._token = dict(token)
        self._token_update_callback = token_update_callback

    @property
    def token(self) -> dict[str, Any]:
        return dict(self._token)

    async def async_validate(self) -> dict[str, Any]:
        return await self._request("GET", "/api/mainviewapi/initmainheader")

    async def async_get_my_teams(self) -> dict[str, Any]:
        """Return roles and all teams followed by the signed-in account."""
        return await self._request("GET", "/api/memberapi/initmyteams")

    async def async_get_coming_team_games(
        self, team_id: int, number_of_games: int = 5
    ) -> Any:
        """Return upcoming games using the endpoint used by the web client."""
        return await self._request(
            "GET",
            "/api/teamapi/getcomingteamgames",
            params={
                "TeamID": team_id,
                "LastGameID": 0,
                "NrOfGames": number_of_games,
            },
        )

    async def async_get_previous_team_games(self, team_id: int) -> Any:
        """Return recent games using the endpoint used by the web client."""
        return await self._request(
            "GET",
            "/api/teamapi/getpreviousteamgames",
            params={"TeamID": team_id, "LastGameID": 0},
        )

    async def async_get_timeline(self, game_id: int) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/followgameapi/initlivetimelineblurbs",
            params={"GameID": game_id},
        )

    async def async_refresh_token(self) -> dict[str, Any]:
        access_token = self._clean_access_token(self._token.get("AccessToken"))
        refresh_token = self._token.get("RefreshToken")
        if not access_token or not refresh_token:
            raise MinFotbollAuthError("Missing access or refresh token")

        try:
            async with self._session.post(
                f"{API_BASE_URL}/api/jwtapi/refreshtoken",
                json={"AccessToken": access_token, "RefreshToken": refresh_token},
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Content-Type": "application/json",
                    "X-Platform": PLATFORM_ID,
                    "Accept-Language": "sv-SE",
                },
                timeout=30,
            ) as response:
                if response.status == 401:
                    raise MinFotbollAuthError("Refresh token rejected")
                response.raise_for_status()
                data = await response.json(content_type=None)
        except MinFotbollAuthError:
            raise
        except (ClientError, TimeoutError, ValueError) as err:
            raise MinFotbollConnectionError(str(err)) from err

        if not isinstance(data, dict) or not data.get("AccessToken"):
            raise MinFotbollAuthError("Invalid refresh response")

        data["AccessToken"] = self._clean_access_token(data["AccessToken"])
        self._token.update(data)
        if self._token_update_callback is not None:
            self._token_update_callback(self.token)
        return self.token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        retry_auth: bool = True,
    ) -> Any:
        access_token = self._clean_access_token(self._token.get("AccessToken"))
        if not access_token:
            raise MinFotbollAuthError("Missing access token")

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {access_token}",
            "X-Platform": PLATFORM_ID,
            "Origin": "https://minfotboll.svenskfotboll.se",
            "Referer": "https://minfotboll.svenskfotboll.se/",
            "Accept-Language": "sv-SE",
        }

        try:
            async with self._session.request(
                method,
                f"{API_BASE_URL}{path}",
                params=params,
                headers=headers,
                timeout=30,
            ) as response:
                if response.status == 401:
                    if retry_auth:
                        await self.async_refresh_token()
                        return await self._request(
                            method, path, params=params, retry_auth=False
                        )
                    raise MinFotbollAuthError("Access token rejected")
                response.raise_for_status()
                text = await response.text()
                if not text:
                    return {}
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text
        except MinFotbollAuthError:
            raise
        except ClientResponseError as err:
            if err.status in (401, 403):
                raise MinFotbollAuthError(str(err)) from err
            raise MinFotbollConnectionError(str(err)) from err
        except (ClientError, TimeoutError) as err:
            raise MinFotbollConnectionError(str(err)) from err

    @staticmethod
    def _clean_access_token(value: Any) -> str:
        if not isinstance(value, str):
            return ""
        return value.strip().strip('"')


def parse_token_json(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as err:
        raise MinFotbollAuthError("Token JSON is not valid JSON") from err

    if not isinstance(value, dict):
        raise MinFotbollAuthError("Token JSON must be an object")
    if not value.get("AccessToken") or not value.get("RefreshToken"):
        raise MinFotbollAuthError("AccessToken and RefreshToken are required")

    value["AccessToken"] = MinFotbollApi._clean_access_token(value["AccessToken"])
    return value


def jwt_member_id(access_token: str) -> str | None:
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded)
        member_id = data.get("memberid")
        return str(member_id) if member_id is not None else None
    except (IndexError, ValueError, json.JSONDecodeError):
        return None
