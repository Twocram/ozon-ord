from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.contract_lookup import (
    CONTRACT_SEARCH_PAGE_SIZE,
    contract_number_key,
    contract_numbers_match,
    find_ord_contracts,
)


def contract(number: str, performer: str, contract_date: str = "2026-06-04") -> dict:
    return {
        "id": f"id-{number}-{performer}",
        "contractNumber": number,
        "contractDate": contract_date,
        "performer": {"title": performer},
    }


class ContractNumberMatchTest(unittest.TestCase):
    def test_ignores_leading_zeros_and_separators(self) -> None:
        # ORD holds "04062026", the PDF prints "№ 4062026".
        self.assertTrue(contract_numbers_match("04062026", "4062026"))
        self.assertTrue(contract_numbers_match("ЛР-2026/4", "лр 2026 / 04"))

    def test_keeps_different_contracts_apart(self) -> None:
        self.assertFalse(contract_numbers_match("04062026/1", "4062026"))
        self.assertFalse(contract_numbers_match("04062026/1", "04062026/2"))
        self.assertFalse(contract_numbers_match("", "4062026"))

    def test_number_key(self) -> None:
        self.assertEqual(contract_number_key("№ 04062026/1"), ("4062026", "1"))


class FindOrdContractsTest(unittest.TestCase):
    def _client(self, contracts: list[dict]) -> MagicMock:
        client = MagicMock()
        client.list_contracts.return_value = {"contract": contracts}
        return client

    def test_finds_the_contract_among_same_day_neighbours(self) -> None:
        # ORD searches by substring: "4062026" answers with the whole day.
        client = self._client([
            contract("04062026/2", "Ткаля Михаил Алексеевич"),
            contract("04062026/12", "Зайцева Татьяна Александровна"),
            contract("04062026", "Воронкова Анна Максимовна"),
            contract("24062026/10", "Мальков Илья Денисович"),
        ])

        matches, truncated = find_ord_contracts(client, "4062026", date(2026, 6, 4))

        self.assertEqual([item["contractNumber"] for item in matches], ["04062026"])
        self.assertIsNone(truncated)

    def test_asks_for_a_page_large_enough_to_hold_a_whole_day(self) -> None:
        client = self._client([])

        find_ord_contracts(client, "4062026", date(2026, 6, 4))

        query = client.list_contracts.call_args.args[0]
        self.assertEqual(query["pageSize"], CONTRACT_SEARCH_PAGE_SIZE)
        self.assertEqual(query["contractNumber"], "4062026")

    def test_reports_a_truncated_search(self) -> None:
        client = self._client([
            contract("04062026", f"Исполнитель {index}")
            for index in range(CONTRACT_SEARCH_PAGE_SIZE)
        ])

        _, truncated = find_ord_contracts(client, "04062026", date(2026, 6, 4))

        self.assertIn("truncated", truncated or "")

    def test_uses_the_performer_to_break_a_tie(self) -> None:
        client = self._client([
            contract("04062026", "Воронкова Анна Максимовна"),
            contract("04062026", "Ткаля Михаил Алексеевич"),
        ])

        matches, _ = find_ord_contracts(
            client, "4062026", date(2026, 6, 4), "Воронковой Анны Максимовны"
        )

        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["performer"]["title"], "Воронкова Анна Максимовна")

    def test_a_contract_of_another_date_is_not_a_match(self) -> None:
        client = self._client([contract("04062026", "Воронкова Анна Максимовна")])

        matches, _ = find_ord_contracts(client, "4062026", date(2026, 7, 4))

        self.assertEqual(matches, [])

    def test_without_a_number_there_is_nothing_to_search(self) -> None:
        client = self._client([])

        self.assertEqual(find_ord_contracts(client, None, date(2026, 6, 4)), ([], None))
        client.list_contracts.assert_not_called()


if __name__ == "__main__":
    unittest.main()
