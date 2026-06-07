import asyncio
import argparse
import logging
import os
import pathlib
import sys
from typing import Optional

import httpx
from dotenv import load_dotenv

import libksef
import libksef.keys
import libksef.sessions
import libksef.invoices
from libksef import gchat


async def run_fetch(
    tokens_file: Optional[pathlib.Path], state_file: Optional[pathlib.Path]
):
    client = httpx.AsyncClient()
    company = libksef.CompanyContext(
        nip=os.environ["KSEF_NIP"], ksef_token=os.environ["KSEF_TOKEN"]
    )
    ksef_addr = os.environ.get("KSEF_ADDR", libksef.TEST_ADDR)

    chat_client = httpx.AsyncClient()
    chat = gchat.ChatWebhook(os.environ["CHAT_WEBHOOK"], chat_client)

    keys = await libksef.keys.get_keys(addr=ksef_addr)

    session_mgr = libksef.sessions.SessionsMgr(
        addr=ksef_addr,
        company=company,
        keys=keys,
        client=client,
    )

    if tokens_file and tokens_file.exists():
        with open(tokens_file) as f:
            session_mgr.load_from_file(f)

    fetcher = libksef.invoices.IncrementalFetcher(
        addr=ksef_addr,
        company=company,
        sessions=session_mgr,
        client=client,
    )

    if state_file and state_file.exists():
        with open(state_file) as f:
            try:
                fetcher.load_fetch_status(f)
            except Exception as e:
                logging.exception("Failed to read last fetch status, ignoring")
                pass

    invoices = await fetcher.fetch_invoices("Subject2")
    for invoice in invoices:
        logging.info("Sending message about invoice %s", invoice)
        await chat.send_msg(invoice)

    if state_file:
        with open(state_file, "w") as f:
            fetcher.save_fetch_status(f)
    if tokens_file:
        with open(tokens_file, "w") as f:
            session_mgr.save_to_file(f)

    await client.aclose()
    await chat_client.aclose()


def main():
    # Early logging
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    # Update secrets
    load_dotenv(verbose=True)

    # Things that are not secrets are passed via flags.
    parser = argparse.ArgumentParser()
    parser.add_argument("--loglevel", default="INFO")
    parser.add_argument("--tokens_file", type=pathlib.Path)
    parser.add_argument("--state_file", type=pathlib.Path)
    args = parser.parse_args()

    # Proper logging.
    logging.getLogger().setLevel(args.loglevel)

    return asyncio.run(run_fetch(args.tokens_file, args.state_file))


if __name__ == "__main__":
    main()
