# Ozon ORD Sync architecture

The project is now packaged as `ozon_ord_sync` under `src/`. This keeps imports stable, enables installation as a CLI, and creates room to split responsibilities further without changing runtime behavior.

## Current layers

- `ozon_ord_sync.cli` — CLI entry point and command orchestration.
- `ozon_ord_sync.application.sync_service` — application workflow: builds sync batches, resolves Ozon IDs, handles duplicate statistic errors, and writes platform error reports.
- `ozon_ord_sync.domain.models` — shared parsed row, validation issue, Ozon ORD payload, and sync batch dataclasses.
- `ozon_ord_sync.infrastructure.google_sheets` — Google Sheets CSV URL building and transport.
- `ozon_ord_sync.application.sheet_parser` — sheet row parsing, filtering, validation, and row preview formatting.
- `ozon_ord_sync.application.formatting` — CLI-facing JSON preview formatting for payload dataclasses.
- `ozon_ord_sync.domain.mapping` — conversion from parsed sheet rows to Ozon ORD payload models.
- `ozon_ord_sync.infrastructure.ozon_ord` — Ozon ORD HTTP clients.
- `ozon_ord_sync.infrastructure.apps_script` — Google Apps Script HTTP client for writing platform errors back.
- `ozon_ord_sync.config.env` — `.env` loading utility.

The root `main.py` remains as a compatibility wrapper for `python main.py`. The former package-level module names (`ozon_ord_sync.sync_service`, `ozon_ord_sync.sheets_reader`, and similar) are also kept as compatibility wrappers while the codebase migrates to the layered imports.

## Refactoring review snapshot

The current split has one canonical implementation per responsibility. The former top-level modules are explicit compatibility wrappers only; they do not contain business logic or wildcard re-exports:

| Legacy module | Current implementation | Status |
| --- | --- | --- |
| `ozon_ord_sync.env_loader` | `ozon_ord_sync.config.env` | Explicit compatibility wrapper |
| `ozon_ord_sync.ozon_ord_mapping` | `ozon_ord_sync.domain.mapping` | Explicit compatibility wrapper |
| `ozon_ord_sync.sync_service` | `ozon_ord_sync.application.sync_service` | Explicit compatibility wrapper |
| `ozon_ord_sync.sheets_reader` | `ozon_ord_sync.application.sheet_parser` + `ozon_ord_sync.infrastructure.google_sheets` | Explicit compatibility wrapper |
| `ozon_ord_sync.ozon_ord_api` | `ozon_ord_sync.infrastructure.ozon_ord` | Explicit compatibility wrapper |
| `ozon_ord_sync.apps_script_client` | `ozon_ord_sync.infrastructure.apps_script` | Explicit compatibility wrapper |

Observed boundaries:

- `cli.py` imports the new layered modules directly, handles argument parsing/printing, and delegates duplicate-statistic retry logic to the application layer.
- `application.sync_service` coordinates batch creation, Ozon ID resolution, sync submission, duplicate-statistic retries, and platform error report generation.
- `domain.models` and `domain.mapping` are pure dataclasses/transformation logic.
- `infrastructure.google_sheets` owns only Google Sheets CSV URL building and transport; parsing/validation lives in `application.sheet_parser`.
- `infrastructure.ozon_ord` and `infrastructure.apps_script` own HTTP access and environment-based client factories.

## Target direction

The package now follows this structure:

```text
ozon_ord_sync/
  config/
    env.py
  domain/
    models.py
    mapping.py
  application/
    formatting.py
    sheet_parser.py
    sync_service.py
  infrastructure/
    google_sheets.py
    ozon_ord.py
    apps_script.py
```

The next safe step is to add focused tests for sheet parsing, payload mapping, and duplicate-statistic error extraction before larger behavior changes.
