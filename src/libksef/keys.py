"""KSEF public keys."""

import base64
import httpx
import logging
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives import hashes

logger = logging.getLogger("libksef.sessions")


class KsefKeys:
    """Wrapper around public keys of the KSEF service."""

    # Constants for allowed key usage types
    KsefTokenEncryption = "KsefTokenEncryption"
    SymmetricKeyEncryption = "SymmetricKeyEncryption"

    def __init__(self, json_data):
        self.keys = {}
        for d in json_data:
            certificate = base64.b64decode(d["certificate"])
            certificate = x509.load_der_x509_certificate(certificate)
            for usage in d["usage"]:
                self.keys[usage] = certificate

    def __repr__(self):
        return "KsefKeys:" + repr(self.keys)

    def encrypt_token(self, token: str) -> str:
        ciphertext = (
            self.keys[self.KsefTokenEncryption]
            .public_key()
            .encrypt(
                token.encode("utf-8"),
                padding.OAEP(
                    mgf=padding.MGF1(algorithm=hashes.SHA256()),
                    algorithm=hashes.SHA256(),
                    label=None,
                ),
            )
        )
        return base64.b64encode(ciphertext).decode("ascii")


async def get_keys(addr: str):
    """Fetch the public keys for given KSEF instance"""
    async with httpx.AsyncClient() as client:
        uri = addr + "/security/public-key-certificates"
        logger.info("Getting keys from %s", uri)
        resp = await client.get(uri)
        resp.raise_for_status()
        return KsefKeys(resp.json())
