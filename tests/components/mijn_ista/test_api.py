"""Tests for the mijn-ista API client library."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest

from custom_components.mijn_ista.api import MijnIstaAPI, MijnIstaAuthError, MijnIstaConnectionError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_response(status: int = 200, json_data: dict | None = None):
    """Build a mock aiohttp response usable as an async context manager."""
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data or {})
    if status >= 400:
        resp.raise_for_status = MagicMock(
            side_effect=aiohttp.ClientResponseError(
                MagicMock(), (), status=status
            )
        )
    else:
        resp.raise_for_status = MagicMock()
    return resp


def _mock_session(response):
    """Wrap a response mock so session.post() works as an async context manager."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=response)
    cm.__aexit__ = AsyncMock(return_value=False)
    session = MagicMock()
    session.post = MagicMock(return_value=cm)
    return session


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


class TestAuthenticate:
    async def test_success_stores_jwt(self):
        resp = _mock_response(200, {"JWT": "my-jwt-token"})
        session = _mock_session(resp)
        api = MijnIstaAPI(session, "user@example.com", "secret")
        await api.authenticate()
        assert api._jwt == "my-jwt-token"

    async def test_http_400_raises_auth_error(self):
        resp = _mock_response(400, {})
        session = _mock_session(resp)
        api = MijnIstaAPI(session, "user@example.com", "wrong")
        with pytest.raises(MijnIstaAuthError):
            await api.authenticate()

    async def test_network_error_raises_connection_error(self):
        session = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("network down"))
        cm.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=cm)
        api = MijnIstaAPI(session, "user@example.com", "secret")
        with pytest.raises(MijnIstaConnectionError):
            await api.authenticate()

    async def test_timeout_raises_connection_error(self):
        session = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = AsyncMock(side_effect=asyncio.TimeoutError)
        cm.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=cm)
        api = MijnIstaAPI(session, "user@example.com", "secret")
        with pytest.raises(MijnIstaConnectionError):
            await api.authenticate()

    async def test_missing_jwt_in_response_raises_auth_error(self):
        resp = _mock_response(200, {"SomethingElse": "value"})
        session = _mock_session(resp)
        api = MijnIstaAPI(session, "user@example.com", "secret")
        with pytest.raises(MijnIstaAuthError):
            await api.authenticate()


# ---------------------------------------------------------------------------
# JWT refresh / absorption
# ---------------------------------------------------------------------------


class TestJWTRefresh:
    async def test_response_jwt_is_absorbed(self):
        """Every successful response should update the stored JWT."""
        auth_resp = _mock_response(200, {"JWT": "initial-jwt"})
        auth_session = _mock_session(auth_resp)
        api = MijnIstaAPI(auth_session, "u", "p")
        await api.authenticate()
        assert api._jwt == "initial-jwt"

        # Now simulate a data endpoint returning a refreshed JWT
        data_resp = _mock_response(200, {"JWT": "refreshed-jwt", "Cus": []})
        api._session = _mock_session(data_resp)
        result = await api.get_user_values()
        assert api._jwt == "refreshed-jwt"
        assert result["Cus"] == []

    async def test_no_jwt_in_response_keeps_existing(self):
        """If a response has no JWT field, the stored JWT must not change."""
        auth_resp = _mock_response(200, {"JWT": "original-jwt"})
        api = MijnIstaAPI(_mock_session(auth_resp), "u", "p")
        await api.authenticate()

        data_resp = _mock_response(200, {"data": "value"})  # no JWT key
        api._session = _mock_session(data_resp)
        await api.get_user_values()
        assert api._jwt == "original-jwt"


# ---------------------------------------------------------------------------
# 401 retry mechanism
# ---------------------------------------------------------------------------


class TestRetryOn401:
    async def test_401_triggers_reauth_and_retries(self):
        """A 401 response should trigger re-authentication and one retry."""
        call_count = 0

        async def _fake_post_enter(self_):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: 401
                resp = _mock_response(401, {})
                return resp
            elif call_count == 2:
                # Re-auth call: 200 with new JWT
                return _mock_response(200, {"JWT": "new-jwt"})
            else:
                # Retry call: 200 with data
                return _mock_response(200, {"JWT": "new-jwt", "Cus": []})

        session = MagicMock()
        cm = MagicMock()
        cm.__aenter__ = _fake_post_enter
        cm.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=cm)

        api = MijnIstaAPI(session, "u", "p", lang="en-GB")
        api._jwt = "old-jwt"
        result = await api.get_user_values()
        assert result.get("Cus") == []


# ---------------------------------------------------------------------------
# Request body construction
# ---------------------------------------------------------------------------


class TestRequestBody:
    def test_body_merges_jwt_and_lang(self):
        api = MijnIstaAPI(MagicMock(), "u", "p", lang="nl-NL")
        api._jwt = "tok"
        body = api._body({"extra": "val"})
        assert body == {"JWT": "tok", "LANG": "nl-NL", "extra": "val"}

    def test_body_extra_overrides_nothing_unexpectedly(self):
        api = MijnIstaAPI(MagicMock(), "u", "p", lang="en-GB")
        api._jwt = "tok"
        body = api._body({"Cuid": "abc"})
        assert body["Cuid"] == "abc"
        assert body["JWT"] == "tok"


# ---------------------------------------------------------------------------
# Endpoint convenience methods
# ---------------------------------------------------------------------------


class TestEndpoints:
    @pytest.fixture
    def api_with_jwt(self):
        api = MijnIstaAPI(MagicMock(), "u", "p")
        api._jwt = "tok"
        return api

    async def test_get_user_values_posts_to_correct_path(self, api_with_jwt):
        resp = _mock_response(200, {"DisplayName": "Test"})
        api_with_jwt._session = _mock_session(resp)
        result = await api_with_jwt.get_user_values()
        assert result["DisplayName"] == "Test"
        url = api_with_jwt._session.post.call_args[0][0]
        assert "/api/Values/UserValues" in url

    async def test_get_month_values_sends_cuid(self, api_with_jwt):
        resp = _mock_response(200, {"mc": []})
        api_with_jwt._session = _mock_session(resp)
        await api_with_jwt.get_month_values("my-cuid")
        body = api_with_jwt._session.post.call_args[1]["json"]
        assert body["Cuid"] == "my-cuid"

    async def test_get_consumption_averages_sends_par(self, api_with_jwt):
        resp = _mock_response(200, {"Averages": []})
        api_with_jwt._session = _mock_session(resp)
        await api_with_jwt.get_consumption_averages("cuid-1", "2024-01-01", "2024-12-31")
        body = api_with_jwt._session.post.call_args[1]["json"]
        assert body["PAR"]["start"] == "2024-01-01"
        assert body["PAR"]["end"] == "2024-12-31"
        assert body["PAR"]["cuid"] == "cuid-1"
