import datetime
import json
import asyncio
from io import StringIO
from unittest.mock import MagicMock, patch

import httpx
import pytest
import libksef
import libksef.sessions
import libksef.keys

pytest_plugins = ("pytest_asyncio",)

# Sample data for tests
CHALLENGE_RESP = {
    "challenge": "20250514-CR-226FB7B000-3ACF9BE4C0-10",
    "timestamp": "2025-07-11T12:23:56.0154302+00:00",
    "timestampMs": "1752236636015",
    "clientIp": "127.0.0.1",
}

AUTH_TOKEN_RESP = {
    "referenceNumber": "20250514-AU-2DFC46C000-3AC6D5877F-D4",
    "authenticationToken": {
        "token": "auth_token_123",
        "validUntil": "2025-07-11T13:23:56.0154302+00:00",
    },
}

AUTH_STATUS_RESP = {"status": {"code": 200, "description": "OK"}}

REDEEM_RESP = {
    "accessToken": {
        "token": "access_123",
        "validUntil": "2099-07-11T14:23:56.0154302+00:00",
    },
    "refreshToken": {
        "token": "refresh_123",
        "validUntil": "2099-07-11T15:23:56.0154302+00:00",
    },
}

REFRESH_RESP = {
    "accessToken": {
        "token": "access_new",
        "validUntil": "2099-07-11T16:23:56.0154302+00:00",
    }
}

COMPANY = libksef.CompanyContext(nip="1234567890", ksef_token="my_ksef_token")


class MockKeys:
    """Mock for KsefKeys class."""

    def encrypt_token(self, token_with_timestamp):
        return f"encrypted({token_with_timestamp})"


@pytest.fixture
def mock_keys():
    return MockKeys()


def test_time_bound_token():
    payload = {"token": "test_token", "validUntil": "2099-01-01T00:00:00.0000000+00:00"}
    tbt = libksef.sessions.TimeBoundToken(payload)
    assert tbt.token == "test_token"
    assert tbt.valid
    assert tbt.remaining.total_seconds() > 0
    assert tbt.to_json()["token"] == "test_token"


def test_time_bound_token_expired():
    payload = {"token": "test_token", "validUntil": "2019-01-01T00:00:00.0000000+00:00"}
    tbt = libksef.sessions.TimeBoundToken(payload)
    assert tbt.token == "test_token"
    assert not tbt.valid
    assert tbt.remaining.total_seconds() < 0
    assert tbt.to_json()["token"] == "test_token"


def test_access_tokens():
    payload = REDEEM_RESP
    at = libksef.sessions.AccessTokens.from_json(payload)
    assert at.access_token.token == "access_123"
    assert at.refresh_token.token == "refresh_123"
    assert "Authorization" in at.headers()
    assert at.headers()["Authorization"] == "Bearer access_123"


@pytest.mark.asyncio
async def test_get_access_tokens_full_flow(mock_keys):
    def transport_handler(request: httpx.Request):
        if request.url.path == "/auth/challenge":
            return httpx.Response(200, json=CHALLENGE_RESP)
        if request.url.path == "/auth/ksef-token":
            return httpx.Response(200, json=AUTH_TOKEN_RESP)
        if request.url.path == f"/auth/{AUTH_TOKEN_RESP['referenceNumber']}":
            return httpx.Response(200, json=AUTH_STATUS_RESP)
        if request.url.path == "/auth/token/redeem":
            return httpx.Response(200, json=REDEEM_RESP)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport_handler)
    ) as client:
        mgr = libksef.sessions.SessionsMgr(
            addr="http://test", keys=mock_keys, company=COMPANY, client=client
        )
        tokens = await mgr.get_access_tokens()
        assert tokens.access_token.token == REDEEM_RESP["accessToken"]["token"]
        assert tokens.refresh_token.token == REDEEM_RESP["refreshToken"]["token"]


@pytest.mark.asyncio
async def test_get_access_tokens_refresh(mock_keys):
    # Setup mgr with expired access token but valid refresh token
    expired_time = (
        datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    valid_future_time = (
        datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
    ).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")

    initial_tokens = {
        "accessToken": {"token": "old_access", "validUntil": expired_time},
        "refreshToken": {"token": "valid_refresh", "validUntil": valid_future_time},
    }

    def transport_handler(request: httpx.Request):
        if request.url.path == "/auth/token/refresh":
            assert request.headers["Authorization"] == "Bearer valid_refresh"
            return httpx.Response(200, json=REFRESH_RESP)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport_handler)
    ) as client:
        mgr = libksef.sessions.SessionsMgr(
            addr="http://test", keys=mock_keys, company=COMPANY, client=client
        )
        mgr.load_from_file(StringIO(json.dumps(initial_tokens)))

        tokens = await mgr.get_access_tokens()
        assert tokens.access_token.token == "access_new"
        assert tokens.refresh_token.token == "valid_refresh"


@pytest.mark.asyncio
async def test_save_load_tokens(mock_keys):
    mgr = libksef.sessions.SessionsMgr(
        addr="http://test", keys=mock_keys, company=COMPANY, client=None
    )

    # Manually set some tokens
    mgr._access_tokens = libksef.sessions.AccessTokens.from_json(REDEEM_RESP)

    io = StringIO()
    mgr.save_to_file(io)
    io.seek(0)

    mgr2 = libksef.sessions.SessionsMgr(
        addr="http://test", keys=mock_keys, company=COMPANY, client=None
    )
    mgr2.load_from_file(io)

    assert mgr2._access_tokens.access_token.token == "access_123"
    assert mgr2._access_tokens.refresh_token.token == "refresh_123"


@pytest.mark.asyncio
async def test_wait_for_auth_token_retry(mock_keys):
    call_count = 0

    def transport_handler(request: httpx.Request):
        nonlocal call_count
        if request.url.path == "/auth/challenge":
            return httpx.Response(200, json=CHALLENGE_RESP)
        if request.url.path == "/auth/ksef-token":
            return httpx.Response(200, json=AUTH_TOKEN_RESP)
        if request.url.path == f"/auth/{AUTH_TOKEN_RESP['referenceNumber']}":
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200, json={"status": {"code": 100, "description": "Processing"}}
                )
            return httpx.Response(200, json=AUTH_STATUS_RESP)
        if request.url.path == "/auth/token/redeem":
            return httpx.Response(200, json=REDEEM_RESP)
        return httpx.Response(404)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport_handler)
    ) as client:
        mgr = libksef.sessions.SessionsMgr(
            addr="http://test", keys=mock_keys, company=COMPANY, client=client
        )
        # We need to mock asyncio.sleep to avoid waiting in tests
        with patch("asyncio.sleep", return_value=None):
            tokens = await mgr.get_access_tokens()
            assert tokens.access_token.token == "access_123"
            assert call_count == 2
