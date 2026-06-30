# Ozon ORD Sync architecture

The project is now packaged as `ozon_ord_sync` under `src/`. This keeps imports stable, enables installation as a CLI, and creates room to split responsibilities further without changing runtime behavior.

## Current layers

- `ozon_ord_sync.cli` — CLI argument parsing and command dispatch.
- `ozon_ord_sync.application.commands` — command handlers and user-facing command output.
- `ozon_ord_sync.application.sync_workflows` — structured sync use cases shared by CLI and HTTP API.
- `ozon_ord_sync.application.sync_service` — batch building, Ozon ID resolution, duplicate statistic handling, and platform error reports.
- `ozon_ord_sync.domain.models` — shared parsed row, validation issue, Ozon ORD payload, and sync batch dataclasses.
- `ozon_ord_sync.infrastructure.google_sheets` — Google Sheets CSV URL building and transport.
- `ozon_ord_sync.application.sheet_parser` — sheet row parsing, filtering, validation, and row preview formatting.
- `ozon_ord_sync.application.formatting` — CLI-facing JSON preview formatting for payload dataclasses.
- `ozon_ord_sync.domain.mapping` — conversion from parsed sheet rows to Ozon ORD payload models.
- `ozon_ord_sync.infrastructure.ozon_ord` — Ozon ORD HTTP clients.
- `ozon_ord_sync.infrastructure.apps_script` — Google Apps Script HTTP client for writing platform errors back.
- `ozon_ord_sync.infrastructure.api_server` — local JSON HTTP API for browser-extension actions.
- `ozon_ord_sync.config.env` — `.env` loading utility.
- `ozon_ord_sync.config.factories` — environment-based client factories.
- `ozon_ord_sync.config.runtime_auth` — runtime Ozon cookie storage under `.runtime/`.

The root `main.py` remains as a compatibility wrapper for `python main.py`. Former package-level compatibility wrappers such as `ozon_ord_sync.sync_service`, `ozon_ord_sync.sheets_reader`, and similar have been removed; use the layered modules directly.

The API server starts with `ozon-ord-sync api` and requires `OZON_ORD_SYNC_API_TOKEN`.
It exposes local extension-facing endpoints:

- `GET /api/status`
- `POST /api/auth/ozon-cookie`
- `POST /api/sync/statistics`
- `POST /api/sync/platforms`

## Refactoring review snapshot

The current split has one canonical implementation per responsibility and no legacy compatibility wrapper modules.

Observed boundaries:

- `cli.py` handles argument parsing and dispatch only; command behavior lives in `application.commands`.
- `application.sync_workflows` exposes structured sync use cases used by both CLI and API.
- `application.sync_service` coordinates batch creation, Ozon ID resolution, sync submission, duplicate-statistic retries, and platform error report generation.
- `domain.models` and `domain.mapping` are pure dataclasses/transformation logic.
- `infrastructure.google_sheets` owns only Google Sheets CSV URL building and transport; parsing/validation lives in `application.sheet_parser`.
- `infrastructure.ozon_ord`, `infrastructure.apps_script`, and `infrastructure.api_server` own HTTP access; environment-based construction lives in `config.factories`.

## Target direction

The package now follows this structure:

```text
ozon_ord_sync/
  config/
    env.py
    factories.py
    runtime_auth.py
  domain/
    models.py
    mapping.py
  application/
    commands.py
    formatting.py
    sheet_parser.py
    sync_service.py
    sync_workflows.py
  infrastructure/
    api_server.py
    google_sheets.py
    ozon_ord.py
    apps_script.py
```

The next safe step is to create the separate browser extension repository that calls the API endpoints.
