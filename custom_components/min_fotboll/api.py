"""API client for Min Fotboll."""

from __future__ import annotations

from collections.abc import Callable
import base64
import json
import logging
import re
from typing import Any

from aiohttp import ClientError, ClientResponseError, ClientSession

from .const import API_BASE_URL, PLATFORM_ID

_LOGGER = logging.getLogger(__name__)


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
        """Return a copy of the current token data."""
        return dict(self._token)

    async def async_validate(self) -> dict[str, Any]:
        """Validate credentials by loading the account header."""
        return await self._request("GET", "/api/mainviewapi/initmainheader")

    async def async_get_main(self) -> dict[str, Any]:
        """Load the main view with followed teams and upcoming games."""
        return await self._request(
            "GET", "/api/mainviewapi/initmain", params={"IsFromWeb": "true"}
        )

    async def async_get_live_team_games(self, team_id: int) -> Any:
        """Load live games for a followed team."""
        return await self._request(
            "GET", "/api/teamapi/getlivegames/", params={"teamid": team_id}
        )

    async def async_get_previous_team_games(self, team_id: int) -> Any:
        """Load previous games for a followed team."""
        return await self._request(
            "GET",
            "/api/teamapi/getpreviousteamgames/",
            params={"teamid": team_id, "lastgameid": 0},
        )

    async def async_get_timeline(self, game_id: int) -> dict[str, Any]:
        """Load current score and timeline for a game."""
        return await self._request(
            "GET",
            "/api/followgameapi/initlivetimelineblurbs",
            params={"GameID": game_id},
        )

    async def async_refresh_token(self) -> dict[str, Any]:
        """Refresh the JWT pair."""
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
        """Perform one authenticated API request."""
        access_token = self._clean_access_token(self._token.get("AccessToken"))
        if not access_token:
            raise MinFotbollAuthError("Missing access token")

        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {access_token}",
            "X-Platform": PLATFORM_ID,
            "Origin": "https://minfotboll.svenskfotboll.se",
            "Referer": "https://minfotboll.svenskfotboll.se/",
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
        """Normalize the access token returned by the site."""
        if not isinstance(value, str):
            return ""
        return value.strip().strip('"')


def parse_token_json(raw: str) -> dict[str, Any]:
    """Parse the JWT_token cookie JSON used by Min Fotboll."""
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
    """Read memberid from the JWT payload without verifying the signature."""
    try:
        payload = access_token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
        data = json.loads(decoded)
        member_id = data.get("memberid")
        return str(member_id) if member_id is not None else None
    except (IndexError, ValueError, json.JSONDecodeError):
        return None


def parse_dotnet_date(value: str | None) -> int | None:
    """Return milliseconds from a .NET /Date(...)/ value."""
    if not value:
        return None
    match = re.match(r"^/Date\((\d+)\)/$", value)
    return int(match.group(1)) if match else None
