"""Support for sending notifications to hangouts."""

import httpx

import libksef


class ChatWebhook:
    def __init__(self, url: str, client: httpx.AsyncClient):
        self._client = client
        self._url = url

    async def send_msg(self, invoice: libksef.InvoiceMetadata):
        app_message = {
            "text": (
                f"Nowa faktura w KSEF nr {invoice.invoice_number} "
                f"od {invoice.seller_name}, "
                f"kwota brutto {invoice.gross_amount}"
            )
        }
        response = await self._client.post(self._url, json=app_message)
        response.raise_for_status()
