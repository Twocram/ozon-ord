from __future__ import annotations

import sys
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.infrastructure.ozon_ord import AdminOzonOrdClient


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


if __name__ == "__main__":
    unittest.main()
