from __future__ import annotations

import io
import sys
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.application.sync_workflows import (
    run_extension_statistics_prepare,
    run_statistics_preview,
)
from ozon_ord_sync.domain.models import (
    OzonOrdAdminStatisticPayload,
    OzonOrdStatisticPayload,
    ParsedRow,
    ResolvedStatisticPayload,
    RowIssue,
    SyncBatch,
)
from ozon_ord_sync.infrastructure.api_server import MAX_REQUEST_BODY_BYTES, _ApiHandler
from ozon_ord_sync.infrastructure.ozon_ord import CookieValidationResult


class ApiHandlerHelpersTest(unittest.TestCase):
    def test_path_ignores_query_string(self) -> None:
        handler = object.__new__(_ApiHandler)
        handler.path = "/api/status?ping=1"

        self.assertEqual(handler._path(), "/api/status")

    def test_read_bool_handles_false_string(self) -> None:
        handler = object.__new__(_ApiHandler)

        self.assertFalse(handler._read_bool({"dryRun": "false"}, "dryRun", default=False))
        self.assertTrue(handler._read_bool({"dryRun": "true"}, "dryRun", default=False))

        with self.assertRaises(ValueError):
            handler._read_bool({"dryRun": "maybe"}, "dryRun", default=False)

    def test_read_json_rejects_large_body(self) -> None:
        handler = object.__new__(_ApiHandler)
        handler.headers = {"Content-Length": str(MAX_REQUEST_BODY_BYTES + 1)}
        handler.rfile = io.BytesIO(b"")

        with self.assertRaises(ValueError):
            handler._read_json()


class AuthValidateHandlerTest(unittest.TestCase):
    def test_auth_validate_without_cookie_returns_400_payload(self) -> None:
        handler = object.__new__(_ApiHandler)
        payloads: list[tuple[dict[str, object], int]] = []
        handler._send_json = lambda payload, status=200: payloads.append((payload, status))

        with patch(
            "ozon_ord_sync.infrastructure.api_server.apply_stored_ozon_cookie"
        ), patch(
            "ozon_ord_sync.infrastructure.api_server.stored_cookie_status",
            return_value={
                "hasOzonCookie": False,
                "cookieEntries": 0,
                "cookieUpdatedAt": None,
                "baseUrl": None,
            },
        ):
            handler._handle_auth_validate()

        self.assertEqual(payloads[0][1], 400)
        self.assertEqual(payloads[0][0]["cookieValid"], None)

    def test_auth_validate_with_valid_cookie_returns_200_payload(self) -> None:
        handler = object.__new__(_ApiHandler)
        payloads: list[tuple[dict[str, object], int]] = []
        handler._send_json = lambda payload, status=200: payloads.append((payload, status))
        client = type(
            "Client",
            (),
            {"validate_cookie": lambda self: CookieValidationResult(True, 400, None)},
        )()

        with patch(
            "ozon_ord_sync.infrastructure.api_server.apply_stored_ozon_cookie"
        ), patch(
            "ozon_ord_sync.infrastructure.api_server.stored_cookie_status",
            return_value={
                "hasOzonCookie": True,
                "cookieEntries": 3,
                "cookieUpdatedAt": "now",
                "baseUrl": "https://ord.ozon.ru",
            },
        ), patch(
            "ozon_ord_sync.infrastructure.api_server.build_admin_ozon_ord_client_from_env",
            return_value=client,
        ):
            handler._handle_auth_validate()

        self.assertEqual(payloads[0][1], 200)
        self.assertEqual(payloads[0][0]["cookieValid"], True)
        self.assertEqual(payloads[0][0]["validationStatusCode"], 400)


class ExtensionStatisticsPrepareWorkflowTest(unittest.TestCase):
    def test_prepare_returns_admin_payloads_for_extension(self) -> None:
        row = ParsedRow(
            row_number=2,
            manager="m",
            month=date(2026, 7, 1),
            platform="p",
            creative_id="creative",
            channel_url="https://t.me/test",
            executor="100б",
            contractor="c",
            price_with_tax=Decimal("100"),
            publication_date=date(2026, 7, 2),
            display_date=date(2026, 7, 3),
            reach=10,
            mark=None,
            error=None,
            raw={},
        )
        batch = SyncBatch(platforms=[], statistics=[], mapping_errors=[])
        admin_payload = OzonOrdAdminStatisticPayload(
            creativeId="creative-id",
            platformId="platform-id",
            price={"amount": "100", "vatRate": "", "withNdsSelected": False},
            comment="",
            dateEndFact=date(2026, 7, 3),
            dateEndPlan=date(2026, 7, 3),
            paymentType="PAYMENT_TYPE_OTHER",
            dateStartFact=date(2026, 7, 2),
            dateStartPlan=date(2026, 7, 2),
            unitCost="100",
            viewsCountByFact="10",
            viewsCountByInvoice="10",
            sameDate=True,
            sameViews=True,
            isAutoCalc=True,
            isSelfPromo=False,
            isNative=False,
            externalId="",
            fromDate="",
            toDate="",
        )

        with (
            patch("ozon_ord_sync.application.sync_workflows.parse_sheet", return_value=([], [row])),
            patch("ozon_ord_sync.application.sync_workflows.filter_rows_for_processing", return_value=[row]),
            patch("ozon_ord_sync.application.sync_workflows.build_sync_batch", return_value=batch),
            patch("ozon_ord_sync.application.sync_workflows.build_external_ozon_ord_client_from_env", return_value=object()),
            patch(
                "ozon_ord_sync.application.sync_workflows.resolve_admin_statistics",
                return_value=([ResolvedStatisticPayload(2, admin_payload)], []),
            ),
        ):
            result = run_extension_statistics_prepare("sheet")

        self.assertTrue(result.ok)
        self.assertEqual(result.rows_eligible, 1)
        self.assertEqual(result.statistics_prepared, 1)
        self.assertEqual(result.statistics[0]["creativeId"], "creative-id")
        self.assertEqual(result.to_dict()["rowsEligible"], 1)


class StatisticsPreviewWorkflowTest(unittest.TestCase):
    def test_preview_returns_counts_issues_and_samples(self) -> None:
        parsed_rows = [
            ParsedRow(
                row_number=2,
                manager="m",
                month=date(2026, 7, 1),
                platform="p",
                creative_id="creative",
                channel_url="https://t.me/test",
                executor="100б",
                contractor="c",
                price_with_tax=Decimal("100"),
                publication_date=date(2026, 7, 2),
                display_date=date(2026, 7, 3),
                reach=10,
                mark=None,
                error=None,
                raw={},
            ),
            ParsedRow(
                row_number=3,
                manager="skip",
                month=date(2026, 7, 1),
                platform="p",
                creative_id="creative-2",
                channel_url="https://t.me/skip",
                executor="other",
                contractor="c",
                price_with_tax=Decimal("200"),
                publication_date=date(2026, 7, 2),
                display_date=date(2026, 7, 3),
                reach=20,
                mark=None,
                error=None,
                raw={},
            ),
        ]
        eligible_rows = parsed_rows[:1]
        issues = [RowIssue(row_number=2, messages=["missing contractor"])]
        batch = SyncBatch(
            platforms=[],
            statistics=[
                OzonOrdStatisticPayload(
                    externalStatisticId="stat-1",
                    externalCreativeId="creative",
                    externalPlatformId="platform-1",
                    dateStartFact=date(2026, 7, 2),
                    dateEndFact=date(2026, 7, 3),
                    dateStartPlan=date(2026, 7, 2),
                    dateEndPlan=date(2026, 7, 3),
                    viewsCountByFact="10",
                    viewsCountByInvoice="10",
                    moneySpent="100.00",
                    unitCost="100.00",
                    withNds=False,
                    comment="Imported from Google Sheets row 2",
                )
            ],
            mapping_errors=[],
        )

        with (
            patch("ozon_ord_sync.application.sync_workflows.parse_sheet", return_value=([], parsed_rows)),
            patch("ozon_ord_sync.application.sync_workflows.filter_rows_for_processing", return_value=eligible_rows),
            patch("ozon_ord_sync.application.sync_workflows.validate_rows", return_value=issues),
            patch("ozon_ord_sync.application.sync_workflows.build_sync_batch", return_value=batch),
        ):
            result = run_statistics_preview("sheet", limit=1)

        self.assertFalse(result.ok)
        self.assertEqual(result.rows_parsed, 2)
        self.assertEqual(result.rows_eligible, 1)
        self.assertEqual(result.rows_skipped_by_executor, 1)
        self.assertEqual(result.rows_with_issues, 1)
        self.assertEqual(result.statistics_prepared, 1)
        self.assertEqual(result.issues, ["Row 2: missing contractor"])
        self.assertEqual(len(result.sample_rows), 1)
        self.assertEqual(len(result.sample_statistics), 1)


if __name__ == "__main__":
    unittest.main()
