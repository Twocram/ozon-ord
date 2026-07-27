from __future__ import annotations

import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.infrastructure.ozon_ord import (
    AdminOzonOrdClient,
    admin_query,
    invoice_duplicate_query,
)


class AdminQueryTest(unittest.TestCase):
    def test_encodes_repeated_array_values(self) -> None:
        query = admin_query({"contractId": ["1", "2"], "pageSize": 10})

        self.assertEqual(query, "contractId=1&contractId=2&pageSize=10")


class InvoiceDuplicateQueryTest(unittest.TestCase):
    def test_builds_browser_duplicate_query(self) -> None:
        query = invoice_duplicate_query(
            {
                "invoiceNumber": "2063nnhqr9",
                "invoiceDate": "2026-04-28",
                "startDate": "2026-04-01",
                "endDate": "2026-04-30",
                "clientRole": "ORGANISATION_ROLE_RD",
                "contractId": "5433538",
                "contractorRole": "ORGANISATION_ROLE_RR",
                "servicePrice": {
                    "amount": "20000",
                    "vatRate": "",
                    "excludingAmount": "20000",
                    "withNdsSelected": False,
                },
            }
        )

        self.assertIn("key.invoiceNumber=2063nnhqr9", query)
        self.assertIn("key.servicePrice.vatRate=", query)
        self.assertIn("key.servicePrice.withNdsSelected=false", query)


class ValidateCookieTest(unittest.TestCase):
    def test_treats_400_as_valid_cookie(self) -> None:
        client = AdminOzonOrdClient("cookie")

        with patch(
            "ozon_ord_sync.infrastructure.ozon_ord.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout='{"error":"bad payload"}\n400', stderr=""),
        ):
            result = client.validate_cookie()

        self.assertTrue(result.is_valid)
        self.assertEqual(result.status_code, 400)
        self.assertIsNone(result.error)

    def test_treats_401_as_invalid_cookie(self) -> None:
        client = AdminOzonOrdClient("cookie")

        with patch(
            "ozon_ord_sync.infrastructure.ozon_ord.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout='{"message":"unauthorized"}\n401', stderr=""),
        ):
            result = client.validate_cookie()

        self.assertFalse(result.is_valid)
        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.error, "unauthorized")

    def test_treats_challenge_as_invalid_cookie(self) -> None:
        client = AdminOzonOrdClient("cookie")

        with patch(
            "ozon_ord_sync.infrastructure.ozon_ord.subprocess.run",
            return_value=CompletedProcess(
                args=[],
                returncode=0,
                stdout='{"challengeURL":"https://ord.ozon.ru/challenge.html"}\n403',
                stderr="",
            ),
        ):
            result = client.validate_cookie()

        self.assertFalse(result.is_valid)
        self.assertEqual(result.status_code, 403)
        self.assertEqual(result.error, "Ozon anti-bot challenge required")

    def test_treats_redirect_as_invalid_cookie(self) -> None:
        client = AdminOzonOrdClient("cookie")

        with patch(
            "ozon_ord_sync.infrastructure.ozon_ord.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="\n302", stderr=""),
        ):
            result = client.validate_cookie()

        self.assertFalse(result.is_valid)
        self.assertEqual(result.status_code, 302)
        self.assertEqual(
            result.error,
            "ORD redirected to login; cookie is invalid or expired",
        )

    def test_curl_uses_cookie_jar_for_redirect_cookie(self) -> None:
        client = AdminOzonOrdClient("cookie")

        with patch(
            "ozon_ord_sync.infrastructure.ozon_ord.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="{}\n200", stderr=""),
        ) as run:
            client.validate_cookie()

        command = run.call_args.args[0]
        self.assertIn("--location", command)
        self.assertIn("--cookie-jar", command)
        self.assertNotIn("cookie: cookie", command)

    def test_treats_200_html_as_invalid_cookie(self) -> None:
        client = AdminOzonOrdClient("cookie")

        with patch(
            "ozon_ord_sync.infrastructure.ozon_ord.subprocess.run",
            return_value=CompletedProcess(args=[], returncode=0, stdout="<html></html>\n200", stderr=""),
        ):
            result = client.validate_cookie()

        self.assertFalse(result.is_valid)
        self.assertEqual(result.status_code, 200)
        self.assertIn("non-JSON", result.error or "")


if __name__ == "__main__":
    unittest.main()
