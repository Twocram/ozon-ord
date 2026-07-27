from __future__ import annotations

import json
from pathlib import Path

from ozon_ord_sync.application.contract_channel_checker import (
    build_contract_channel_check_rows,
)
from ozon_ord_sync.application.contract_reader import read_contracts_from_creative_sheet
from ozon_ord_sync.application.invoice_payload_builder import build_invoice_payload_drafts
from ozon_ord_sync.application.receipt_parser import read_receipts_from_sheet
from ozon_ord_sync.application.sync_workflows import (
    run_creative_preview,
    run_document_check_preview,
    run_platform_preview,
    run_platform_sync,
    run_statistics_preview,
    run_statistics_sync,
)
from ozon_ord_sync.config.factories import (
    build_admin_ozon_ord_client_from_env,
    build_apps_script_client_from_env,
    build_external_ozon_ord_client_from_env,
)
from ozon_ord_sync.infrastructure.google_sheets import google_sheet_id



def mark_contract_channel_checks(sheet_url: str, send: bool) -> int:
    rows = build_contract_channel_check_rows(sheet_url)
    print(f"Rows to update: {len(rows)}")
    print(
        json.dumps(
            [row.to_dict() for row in rows],
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    if not send or not rows:
        if not send:
            print("\nDry run mode. Use --send to write to Проверка column.")
        return 0

    client = build_apps_script_client_from_env()
    if client is None:
        print("Error: GOOGLE_APPS_SCRIPT_WEB_APP_URL is required")
        return 1

    response = client.update_document_checks(
        [row.to_dict() for row in rows],
        spreadsheet_id=google_sheet_id(sheet_url),
    )
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0 if response.get("ok", True) else 1


def build_document_check_invoice_payloads(
    sheet_url: str,
    output_file: str | None,
) -> int:
    drafts = build_invoice_payload_drafts(
        sheet_url,
        admin_client=build_admin_ozon_ord_client_from_env(),
    )
    payload = {
        "rowsParsed": len(drafts),
        "rowsOk": sum(1 for draft in drafts if draft.ok),
        "rowsSkipped": sum(1 for draft in drafts if draft.skip_reason),
        "drafts": [draft.to_dict() for draft in drafts],
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if output_file:
        Path(output_file).write_text(text + "\n", encoding="utf-8")
        print(f"Saved: {output_file}")
    else:
        print(text)
    return 0



def create_extended_invoice(payload_file: str | None, send: bool) -> int:
    if not payload_file:
        print("Error: --payload-file is required")
        return 1

    payload = json.loads(Path(payload_file).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        print("Error: payload file must contain a JSON object")
        return 1

    client = build_admin_ozon_ord_client_from_env()
    duplicates = client.check_invoice_duplicates(payload)
    print("Duplicate check:")
    print(json.dumps(duplicates, ensure_ascii=False, indent=2, default=str))

    if not send:
        print("\nDry run mode. Use --send to create extended invoice.")
        return 0

    response = client.create_extended_invoice(payload)
    print("\nCreate response:")
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def read_creative_contracts(sheet_url: str, create_missing: bool = False) -> int:
    rows = read_contracts_from_creative_sheet(
        sheet_url,
        admin_client=build_admin_ozon_ord_client_from_env(),
        apps_script_client=build_apps_script_client_from_env(),
        create_missing=create_missing,
    )
    errors = [row for row in rows if row.error]
    counterparties_found = sum(
        1 for row in rows if row.counterparty and row.counterparty.get("found")
    )
    counterparties_created = sum(
        1 for row in rows if row.counterparty and row.counterparty.get("created")
    )
    counterparties_to_create = sum(
        1
        for row in rows
        if row.counterparty
        and row.counterparty.get("create_payload")
        and not row.counterparty.get("created")
    )
    contracts_found = sum(
        1 for row in rows if row.ord_contract and row.ord_contract.get("found")
    )
    contracts_created = sum(
        1 for row in rows if row.ord_contract and row.ord_contract.get("created")
    )
    contracts_to_create = sum(
        1
        for row in rows
        if row.ord_contract
        and row.ord_contract.get("create_payload")
        and not row.ord_contract.get("created")
    )
    creatives_created = sum(
        1 for row in rows if row.creative and row.creative.get("created")
    )
    creatives_to_create = sum(
        1 for row in rows if row.creative and row.creative.get("would_create")
    )
    erids_written = sum(
        1 for row in rows if row.creative and row.creative.get("erid_written")
    )

    print(f"Rows parsed: {len(rows)}")
    print(f"Contracts read: {len(rows) - len(errors)}")
    print(f"Counterparties found in ORD: {counterparties_found}")
    print(f"Contracts found in ORD: {contracts_found}")
    if create_missing:
        print(f"Counterparties created: {counterparties_created}")
        print(f"Contracts created: {contracts_created}")
        print(f"Creatives created: {creatives_created}")
        print(f"erid cells written: {erids_written}")
    print(f"Counterparties to create (dry-run): {counterparties_to_create}")
    print(f"Contracts to create (dry-run): {contracts_to_create}")
    print(f"Creatives to create (dry-run): {creatives_to_create}")
    print(f"Errors: {len(errors)}")
    print("\nRows:")
    print(
        json.dumps(
            [row.to_dict() for row in rows],
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 1 if errors else 0


def read_document_check_receipts(sheet_url: str) -> int:
    rows = read_receipts_from_sheet(sheet_url)
    errors = [row for row in rows if row.error]

    print(f"Rows parsed: {len(rows)}")
    print(f"Receipts read: {len(rows) - len(errors)}")
    print(f"Errors: {len(errors)}")
    print("\nRows:")
    print(
        json.dumps(
            [row.to_dict() for row in rows],
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 1 if errors else 0


def preview_creatives(sheet_url: str, limit: int) -> int:
    result = run_creative_preview(sheet_url, limit)

    print(f"Rows parsed: {result.rows_parsed}")
    print("\nHeader:")
    print(json.dumps(result.header, ensure_ascii=False, indent=2, default=str))
    print("\nSample rows:")
    print(json.dumps(result.sample_rows, ensure_ascii=False, indent=2, default=str))
    return 0


def preview_document_check(sheet_url: str, limit: int) -> int:
    result = run_document_check_preview(sheet_url, limit)

    print(f"Rows parsed: {result.rows_parsed}")
    print("\nHeader:")
    print(json.dumps(result.header, ensure_ascii=False, indent=2, default=str))
    print("\nSample rows:")
    print(json.dumps(result.sample_rows, ensure_ascii=False, indent=2, default=str))
    return 0


def preview(sheet_url: str, limit: int) -> int:
    result = run_statistics_preview(sheet_url, limit)

    print(f"Rows parsed: {result.rows_parsed}")
    print(f"Rows eligible: {result.rows_eligible}")
    print(f"Rows skipped by executor filter: {result.rows_skipped_by_executor}")
    print(f"Rows with issues: {result.rows_with_issues}")
    print(f"Statistics prepared: {result.statistics_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    print("\nSample rows:")
    print(json.dumps(result.sample_rows, ensure_ascii=False, indent=2, default=str))

    print("\nSample statistic payloads:")
    print(
        json.dumps(
            result.sample_statistics,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    if result.issues:
        print("\nIssues:")
        for issue in result.issues[:10]:
            print(issue)

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
            print(error)

    return 0


def preview_platforms(sheet_url: str, sheet_name: str, limit: int) -> int:
    result = run_platform_preview(sheet_url, sheet_name, limit)

    print(f"Platform sheet: {result.sheet_name}")
    print(f"Rows parsed: {result.rows_parsed}")
    print(f"Rows with issues: {result.rows_with_issues}")
    print(f"Platforms prepared: {result.platforms_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    print("\nSample rows:")
    print(json.dumps(result.sample_rows, ensure_ascii=False, indent=2, default=str))

    print("\nSample platform payloads:")
    print(
        json.dumps(
            result.sample_platforms,
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    if result.issues:
        print("\nIssues:")
        for issue in result.issues[:10]:
            print(issue)

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
            print(error)

    return 0


def probe_api() -> int:
    client = build_external_ozon_ord_client_from_env()
    response = client.list_platforms(page_size=1)
    print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
    return 0


def sync_platforms(sheet_url: str, sheet_name: str, send: bool) -> int:
    result = run_platform_sync(sheet_url, sheet_name, send)

    print(f"Platform sheet: {result.sheet_name}")
    print(f"Rows parsed: {result.rows_parsed}")
    print(f"Rows with issues: {result.rows_with_issues}")
    print(f"Platforms prepared: {result.platforms_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    if result.issues:
        print("\nIssues:")
        for issue in result.issues[:10]:
            print(issue)
        return 1

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
            print(error)
        return 1

    if result.dry_run:
        print("\nDry run mode. Use --send to push platforms to Ozon ORD.")
        return 0

    print(json.dumps(result.ozon_response, ensure_ascii=False, indent=2, default=str))
    return 0


def sync(sheet_url: str, send: bool) -> int:
    result = run_statistics_sync(sheet_url, send)

    print(f"Rows eligible: {result.rows_eligible}")
    print(f"Statistics prepared: {result.statistics_prepared}")
    print(f"Mapping errors: {len(result.mapping_errors)}")

    if result.mapping_errors:
        print("\nMapping errors:")
        for error in result.mapping_errors[:10]:
            print(error)
        return 1

    if result.dry_run:
        print("\nDry run mode. Use --send to push data to Ozon ORD.")
        if result.resolution_errors:
            print("\nResolution errors:")
            for error in result.resolution_errors[:10]:
                print(error)
            print("\nSaved platform lookup errors to platform_errors.json")
            return 1
        return 0

    print(json.dumps(result.ozon_response, ensure_ascii=False, indent=2, default=str))
    return 0
