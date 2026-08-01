from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.commands import create_extended_invoice


class CreateExtendedInvoiceTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.payload_file = Path(directory.name) / "payload.json"
        self.payload_file.write_text(
            json.dumps({"contractId": "5469541", "invoiceNumber": "24"}),
            encoding="utf-8",
        )

    def _client(self, duplicate_ids: list[str]) -> MagicMock:
        client = MagicMock()
        client.check_invoice_duplicates.return_value = {"ids": duplicate_ids}
        client.create_extended_invoice.return_value = {"id": "77124"}
        return client

    def _run(self, client: MagicMock, send: bool, force: bool = False) -> int:
        with patch(
            "ozon_ord_sync.application.commands.build_admin_ozon_ord_client_from_env",
            return_value=client,
        ):
            return create_extended_invoice(str(self.payload_file), send, force)

    def test_refuses_to_create_a_duplicate(self) -> None:
        client = self._client(["77123"])

        self.assertEqual(self._run(client, send=True), 1)
        client.create_extended_invoice.assert_not_called()

    def test_creates_when_ord_has_no_duplicate(self) -> None:
        client = self._client([])

        self.assertEqual(self._run(client, send=True), 0)
        client.create_extended_invoice.assert_called_once()

    def test_force_creates_despite_a_duplicate(self) -> None:
        client = self._client(["77123"])

        self.assertEqual(self._run(client, send=True, force=True), 0)
        client.create_extended_invoice.assert_called_once()

    def test_dry_run_never_creates(self) -> None:
        client = self._client([])

        self.assertEqual(self._run(client, send=False), 0)
        client.create_extended_invoice.assert_not_called()


if __name__ == "__main__":
    unittest.main()
