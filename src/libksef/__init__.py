"""Basic constants for accessing KSEF"""

import decimal
from dataclasses import dataclass

# Address of the test instance.
TEST_ADDR = "https://api-test.ksef.mf.gov.pl/v2"

# Address of the preprod instance.
PREPROD_ADDR = "https://api-demo.ksef.mf.gov.pl/v2"

# Address of the prod instance.
PROD_ADDR = "https://api.ksef.mf.gov.pl/v2"


@dataclass
class CompanyContext:
    nip: str
    ksef_token: str


@dataclass
class InvoiceMetadata:
    ksef_number: str
    invoice_number: str

    seller_name: str
    buyer_name: str

    net_amount: decimal.Decimal
    gross_amount: decimal.Decimal

    @classmethod
    def from_json(cls, data):
        return cls(
            ksef_number=data["ksefNumber"],
            invoice_number=data["invoiceNumber"],
            seller_name=data["seller"]["name"],
            buyer_name=data["buyer"]["name"],
            net_amount=data["netAmount"],
            gross_amount=data["grossAmount"],
        )
