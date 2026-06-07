import os
from io import BytesIO, StringIO

import httpx
import pytest

import libksef
import libksef.keys
import libksef.sessions
import libksef.invoices

pytest_plugins = ("pytest_asyncio",)

KSEF_NIP = os.environ.get("TEST_KSEF_NIP", "")
KSEF_TOKEN = os.environ.get("TEST_KSEF_TOKEN", "")

pytestmark = [
    pytest.mark.skipif(
        not KSEF_TOKEN, reason="TEST_KSEF_TOKEN environment variable is not set"
    ),
    pytest.mark.skipif(
        not KSEF_NIP, reason="TEST_KSEF_NIP environment variable is not set"
    ),
]

COMPANY = libksef.CompanyContext(
    nip=KSEF_NIP,
    ksef_token=KSEF_TOKEN,
)


@pytest.mark.asyncio
async def test_auth():
    client = httpx.AsyncClient()
    ksef_keys = await libksef.keys.get_keys(addr=libksef.TEST_ADDR)
    mgr = libksef.sessions.SessionsMgr(
        addr=libksef.TEST_ADDR,
        keys=ksef_keys,
        company=COMPANY,
        client=client,
    )
    access_tokens = await mgr.get_access_tokens()
    assert access_tokens is not None
    assert access_tokens.valid
    assert access_tokens.refreshable

    fp = StringIO()
    mgr.save_to_file(fp)
    fp.seek(0)
    mgr.load_from_file(fp)
    fp.close()

    await client.aclose()


@pytest.mark.asyncio
async def test_load_and_save():
    client = httpx.AsyncClient()
    with StringIO() as fp:
        fp.write("""{
              "accessToken": {
                "token": "aaaa",
                "validUntil": "2026-03-14T17:42:54.3771835+00:00"
              },
              "refreshToken": {
                "token": "bbbb",
                "validUntil": "2026-03-21T17:27:54.3771835+00:00"
              }
            }
            """)
        ksef_keys = libksef.keys.KsefKeys({})
        mgr = libksef.sessions.SessionsMgr(
            addr=libksef.TEST_ADDR, keys=ksef_keys, company=COMPANY, client=client
        )
        fp.seek(0)
        tokens = mgr.load_from_file(fp)

    assert tokens.access_token.token == "aaaa"
    assert tokens.refresh_token.token == "bbbb"

    with StringIO() as fp2:
        mgr.save_to_file(fp2)
        fp2.seek(0)
        tokens2 = mgr.load_from_file(fp2)

    assert tokens.refresh_token.valid_until == tokens2.refresh_token.valid_until
    assert tokens.refresh_token.token == tokens2.refresh_token.token

    assert tokens.access_token.valid_until == tokens2.access_token.valid_until
    assert tokens.access_token.token == tokens2.access_token.token

    await client.aclose()


@pytest.mark.asyncio
async def test_fetch_invoices():
    client = httpx.AsyncClient()
    ksef_keys = await libksef.keys.get_keys(addr=libksef.TEST_ADDR)
    sessions = libksef.sessions.SessionsMgr(
        addr=libksef.TEST_ADDR, keys=ksef_keys, company=COMPANY, client=client
    )

    fetcher = libksef.invoices.IncrementalFetcher(
        addr=libksef.TEST_ADDR, sessions=sessions, company=COMPANY, client=client
    )

    invoices = await fetcher.fetch_invoices("Subject2")
    assert len(invoices) > 0
    invoices2 = await fetcher.fetch_invoices("Subject2")
    assert not invoices2

    await client.aclose()
