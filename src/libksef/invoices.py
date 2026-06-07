"""Fetching invoices."""

import datetime
import json
import logging

import httpx

import libksef
import libksef.sessions
from libksef.timeutil import parse_timestamp, write_timestamp

logger = logging.getLogger("libksef.invoices")


class IncrementalFetcher:
    """Fetch invoices incrementally."""

    def __init__(
        self,
        addr: str,
        sessions: libksef.sessions.SessionsMgr,
        company: libksef.CompanyContext,
        client: httpx.AsyncClient,
    ):
        self._addr = addr
        self._sessions = sessions
        self._company = company
        self._client: httpx.AsyncClient = client

        # Last fetch timestamp, by subject type.
        # Use strings as returned by KSEF to avoid precision loss.
        self._last_fetch = {}

    async def _fetch_once(self, subject_type: str, start_date: str, page: int):
        """Perform a single fetch operation."""
        request = {
            "subjectType": subject_type,
            "dateRange": {
                "dateType": "PermanentStorage",
                "from": start_date,
            },
        }
        uri = self._addr + "/invoices/query/metadata?pageSize=100&pageOffset=%d" % page

        access_tokens = await self._sessions.get_access_tokens()
        hdrs = access_tokens.headers()
        logger.info("Sending invoices query at %s body %s", uri, request)
        resp = await self._client.post(uri, headers=hdrs, json=request)
        resp.raise_for_status()
        return resp.json()

    async def fetch_invoices(self, subject_type: str):
        """Fetches all invoices since last fetch."""
        min_valid_start = (
            datetime.datetime.now() - datetime.timedelta(days=88)
        ).astimezone(datetime.timezone.utc)

        start_date = self._last_fetch.get(subject_type, None)
        if not start_date or parse_timestamp(start_date) < min_valid_start:
            start_date = write_timestamp(min_valid_start)

        invoices = []
        seen_ids = set()

        page = 0
        while True:
            payload = await self._fetch_once(subject_type, start_date, page)
            for invoice in payload["invoices"]:
                ksef_no = invoice["ksefNumber"]
                if ksef_no not in seen_ids:
                    invoices.append(invoice)
                    seen_ids.add(ksef_no)
            if not payload["hasMore"]:
                # We got all. Next time start with the HWM.
                start_date = payload["permanentStorageHwmDate"]
                break
            if payload["isTruncated"]:
                # Query too large, reduce window.
                # Might return same invoice again, because "from" is
                # inclusive.
                start_date = invoices[-1]["permanentStorageDate"]
                page = 0
            else:
                # Query is not truncated, but has more pages.
                page += 1
                continue
        self._last_fetch[subject_type] = start_date
        return [libksef.InvoiceMetadata.from_json(i) for i in invoices]

    def save_fetch_status(self, fp):
        """Saves fetch status to a file to allow resuming later."""
        logger.info("Saving last fetch status")
        json.dump(self._last_fetch, fp)

    def load_fetch_status(self, fp):
        """Loads fetch status to resume fetching."""
        logger.info("Loading last fetch status")
        self._last_fetch = json.load(fp)
