"""Authentication and sessions."""

import asyncio
import datetime
import json
from typing import Optional

import httpx
import logging

import libksef.keys
from libksef.timeutil import parse_timestamp

logger = logging.getLogger("libksef.sessions")

# Initial auth challenge.
# Example:
# {
#   "challenge": "20250514-CR-226FB7B000-3ACF9BE4C0-10",
#   "timestamp": "2025-07-11T12:23:56.0154302+00:00",
#   "timestampMs": 1752236636015,
#   "clientIp": "127.0.0.1"
# }
type AuthChallenge = dict[str, str]

# Token of the authentication operation.
#
# Can be redeemed into AccessTokens
#
# Example:
# {
#   "referenceNumber": "20250514-AU-2DFC46C000-3AC6D5877F-D4",
#   "authenticationToken": {
#     "token": "...",
#     "validUntil": "2025-07-11T12:23:56.0154302+00:00"
#   }
# }
type AuthenticationToken = dict[str, str]


class TimeBoundToken:
    """Represents a token with validity information."""

    def __init__(self, json_payload):
        self._valid_until = parse_timestamp(json_payload["validUntil"])
        self._token = json_payload["token"]
        logging.info(
            "Time bound token: valid_until=%s, remainig=%s",
            self.valid_until,
            self.remaining,
        )

    @property
    def valid_until(self) -> datetime.datetime:
        return self._valid_until

    @property
    def valid(self):
        remaining = self.remaining
        return remaining.total_seconds() > 30

    @property
    def remaining(self) -> datetime.timedelta:
        now = datetime.datetime.now(datetime.timezone.utc)
        return self.valid_until - now

    @property
    def token(self):
        return self._token

    def to_json(self):
        return {
            "token": self._token,
            "validUntil": self._valid_until.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00"),
        }


class AccessTokens:
    """Represents a pair of tokens: access and refresh token."""

    def __init__(self, access_token, refresh_token):
        self._access_token = access_token
        self._refresh_token = refresh_token

    @classmethod
    def from_json(cls, json_payload):
        return cls(
            access_token=TimeBoundToken(json_payload["accessToken"]),
            refresh_token=TimeBoundToken(json_payload["refreshToken"]),
        )

    @property
    def valid(self):
        return self._access_token.valid

    @property
    def refreshable(self):
        return self._refresh_token.valid

    @property
    def access_token(self) -> TimeBoundToken:
        """Returns the access token. Note it might need refreshing."""
        return self._access_token

    @property
    def refresh_token(self) -> TimeBoundToken:
        """Returns the refresh token."""
        return self._refresh_token

    def to_json(self):
        return {
            "accessToken": self._access_token.to_json(),
            "refreshToken": self._refresh_token.to_json(),
        }

    def headers(self):
        return {"Authorization": "Bearer " + self.access_token.token}


class SessionsMgr:
    """Manages authentication and sessions"""

    def __init__(
        self,
        addr: str,
        keys: libksef.keys.KsefKeys,
        company: libksef.CompanyContext,
        client: httpx.AsyncClient,
    ):
        self._addr = addr
        self._keys = keys
        self._company = company
        self._client = client
        self._access_tokens: Optional[AccessTokens] = None

    def _should_retry(self, response: httpx.Response) -> bool:
        """Helper for handling Too Many Requests error code"""
        return response.status_code == 429

    async def _get_auth_challenge(self) -> AuthChallenge:
        """Fetch the auth challenge."""
        uri = self._addr + "/auth/challenge"
        logger.info("Sending /auth/challenge to %s", uri)
        resp = await self._client.post(uri)
        resp.raise_for_status()
        r = resp.json()
        return r

    def _prepare_auth_request(self, auth_challenge: AuthChallenge):
        """Prepares JSON payload for the authentication request."""
        timestamp_millis = int(auth_challenge["timestampMs"])
        token_with_timestamp = self._company.ksef_token + "|" + str(timestamp_millis)
        request = {
            "challenge": auth_challenge["challenge"],
            "encryptedToken": self._keys.encrypt_token(token_with_timestamp),
            "contextIdentifier": {"type": "Nip", "value": self._company.nip},
        }
        return request

    async def _get_auth_token(
        self, auth_challenge: AuthChallenge
    ) -> AuthenticationToken:
        """Begins the authentication operation. Returns temporary token."""
        request = self._prepare_auth_request(auth_challenge)
        uri = self._addr + "/auth/ksef-token"
        logger.info("Sending /auth/ksef-token to %s", uri)
        resp = await self._client.post(uri, json=request)
        resp.raise_for_status()
        return resp.json()

    async def _wait_for_auth_token(self, auth_token: AuthenticationToken):
        """Waits for authentication to finish."""
        while True:
            refno = auth_token["referenceNumber"]
            uri = self._addr + "/auth/" + refno
            hdrs = {
                "Authorization": "Bearer " + auth_token["authenticationToken"]["token"]
            }
            logger.info("Sending auth check request to %s", uri)
            resp = await self._client.get(uri, headers=hdrs)
            if self._should_retry(resp):
                await asyncio.sleep(1)
                continue
            resp.raise_for_status()
            resp = resp.json()
            match resp["status"]["code"]:
                case 100:
                    await asyncio.sleep(1)
                    continue
                case 200:
                    return
                case _:
                    raise PermissionError(resp["status"]["description"])

    async def _redeem_token(self, auth_token: AuthenticationToken) -> AccessTokens:
        """Redeems the token, obtaining access token and refresh token."""
        uri = self._addr + "/auth/token/redeem"
        hdrs = {"Authorization": "Bearer " + auth_token["authenticationToken"]["token"]}
        logger.info("Sending redeem request")
        resp = await self._client.post(uri, headers=hdrs)
        resp.raise_for_status()
        return AccessTokens.from_json(resp.json())

    async def _refresh_token(self, access_tokens: AccessTokens) -> AccessTokens:
        """Refreshes the access token using the refresh token."""
        uri = self._addr + "/auth/token/refresh"
        hdrs = {"Authorization": "Bearer " + access_tokens.refresh_token.token}
        logger.info("Sending refresh request")
        resp = await self._client.post(uri, headers=hdrs)
        resp.raise_for_status()
        payload = resp.json()
        # KSEF refresh returns a new access token. We keep the existing refresh token.
        return AccessTokens(
            access_token=TimeBoundToken(payload["accessToken"]),
            refresh_token=access_tokens.refresh_token,
        )

    def load_from_file(self, fp):
        """Load tokens from a file"""
        logger.info("Loading tokens from file")
        payload = json.load(fp)
        if payload:
            self._access_tokens = AccessTokens.from_json(payload)
        return self._access_tokens

    def save_to_file(self, fp):
        """Save tokens to file for reuse later."""
        if self._access_tokens:
            logger.info("Saving tokens to file")
            json.dump(self._access_tokens.to_json(), fp)

    async def get_access_tokens(self) -> AccessTokens:
        """Refreshes access tokens or obtains new ones."""
        if self._access_tokens is None or not self._access_tokens.refreshable:
            # No tokens or past refresh date, need new tokens
            self._access_tokens = None
            challenge = await self._get_auth_challenge()
            auth_token = await self._get_auth_token(challenge)
            await self._wait_for_auth_token(auth_token)
            self._access_tokens = await self._redeem_token(auth_token)

        if not self._access_tokens.valid:
            self._access_tokens = await self._refresh_token(self._access_tokens)

        return self._access_tokens
