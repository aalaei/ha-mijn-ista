"""Async API client for mijn.ista.nl."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

BASE_URL = "https://mijn.ista.nl"
_AUTHORIZE = "/api/Authorization/Authorize"
_JWT_REFRESH = "/api/Authorization/JWTRefresh"
_USER_VALUES = "/api/Values/UserValues"
_MONTH_VALUES = "/api/Consumption/MonthValues"
_CONSUMPTION_VALUES = "/api/Values/ConsumptionValues"
_CONSUMPTION_AVERAGES = "/api/Values/ConsumptionAverages"

_TIMEOUT = aiohttp.ClientTimeout(total=30)


class MijnIstaAuthError(Exception):
    """Raised when credentials are rejected by mijn.ista.nl."""


class MijnIstaConnectionError(Exception):
    """Raised when the API cannot be reached."""


class MijnIstaAPI:
    """Async HTTP client for mijn.ista.nl.

    Authentication uses a custom JWT that is passed in the request body
    (not as an Authorization header). Every response carries a refreshed
    JWT that must replace the stored one for the next call.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        username: str,
        password: str,
        lang: str = "nl-NL",
    ) -> None:
        self._session = session
        self._username = username
        self._password = password
        self._lang = lang
        self._jwt: str | None = None

    # ── authentication ──────────────────────────────────────────────────────

    async def authenticate(self) -> None:
        """Obtain a fresh JWT from /api/Authorization/Authorize.

        Raises MijnIstaAuthError on bad credentials,
        MijnIstaConnectionError on network failure.
        """
        try:
            async with self._session.post(
                f"{BASE_URL}{_AUTHORIZE}",
                json={
                    "username": self._username,
                    "password": self._password,
                    "LANG": self._lang,
                },
                timeout=_TIMEOUT,
            ) as resp:
                if resp.status == 400:
                    raise MijnIstaAuthError("Invalid credentials (HTTP 400)")
                resp.raise_for_status()
                data: dict[str, Any] = await resp.json()
        except MijnIstaAuthError:
            raise
        except aiohttp.ClientResponseError as exc:
            if exc.status == 400:
                raise MijnIstaAuthError("Invalid credentials") from exc
            raise MijnIstaConnectionError(str(exc)) from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise MijnIstaConnectionError(str(exc)) from exc

        if "JWT" not in data:
            raise MijnIstaAuthError("No JWT field in /Authorize response")
        self._jwt = data["JWT"]
        _LOGGER.debug("mijn.ista.nl: authenticated successfully")

    # ── data endpoints ──────────────────────────────────────────────────────

    async def get_user_values(self) -> dict[str, Any]:
        """POST /api/Values/UserValues.

        Returns the address list, available services, billing periods,
        and the current-vs-previous annual comparison.
        """
        return await self._post(_USER_VALUES, {})

    async def get_month_values(self, cuid: str) -> dict[str, Any]:
        """POST /api/Consumption/MonthValues.

        Returns full monthly history for all available years, broken down
        per service and per physical device.
        """
        return await self._post(_MONTH_VALUES, {"Cuid": cuid})

    async def get_consumption_values(
        self, cuid: str, billing_period: dict[str, Any]
    ) -> dict[str, Any]:
        """POST /api/Values/ConsumptionValues.

        Returns meter totals for a specific billing period.
        billing_period shape: {"y": 2025, "s": "2025-01-01T00:00:00",
                                "e": "2025-12-31T00:00:00", "ta": 11}
        """
        return await self._post(
            _CONSUMPTION_VALUES, {"Cuid": cuid, "Billingperiod": billing_period}
        )

    async def get_consumption_averages(
        self, cuid: str, start: str, end: str
    ) -> dict[str, Any]:
        """POST /api/Values/ConsumptionAverages.

        Returns normalised building-wide averages per service.
        start/end format: "YYYY-MM-DD"
        """
        return await self._post(
            _CONSUMPTION_AVERAGES,
            {"Cuid": cuid, "PAR": {"start": start, "end": end, "cuid": cuid}},
        )

    # ── internals ───────────────────────────────────────────────────────────

    def _body(self, extra: dict[str, Any]) -> dict[str, Any]:
        """Build a request body with JWT + LANG merged with caller extras."""
        return {"JWT": self._jwt, "LANG": self._lang, **extra}

    def _absorb_jwt(self, data: dict[str, Any]) -> None:
        """Persist the refreshed JWT that every API response carries."""
        if refreshed := data.get("JWT"):
            self._jwt = refreshed

    async def _post(self, path: str, extra: dict[str, Any]) -> dict[str, Any]:
        """POST with one automatic re-authentication retry on HTTP 401."""
        body = self._body(extra)
        try:
            async with self._session.post(
                f"{BASE_URL}{path}", json=body, timeout=_TIMEOUT
            ) as resp:
                if resp.status == 401:
                    _LOGGER.debug("mijn.ista.nl: JWT expired, re-authenticating")
                    await self.authenticate()
                    body["JWT"] = self._jwt
                    # Retry once with fresh JWT
                    async with self._session.post(
                        f"{BASE_URL}{path}", json=body, timeout=_TIMEOUT
                    ) as retry:
                        retry.raise_for_status()
                        data: dict[str, Any] = await retry.json()
                        self._absorb_jwt(data)
                        return data
                resp.raise_for_status()
                data = await resp.json()
        except MijnIstaAuthError:
            raise
        except MijnIstaConnectionError:
            raise
        except aiohttp.ClientResponseError as exc:
            raise MijnIstaConnectionError(str(exc)) from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise MijnIstaConnectionError(str(exc)) from exc

        self._absorb_jwt(data)
        return data
