# Ozon ORD Sync architecture

The project is now packaged as `ozon_ord_sync` under `src/`. This keeps imports stable, enables installation as a CLI, and creates room to split responsibilities further without changing runtime behavior.

## Current layers

- `ozon_ord_sync.main` — CLI entry point and command orchestration.
- `ozon_ord_sync.sync_service` — application workflow: builds sync batches, resolves Ozon IDs, handles duplicate statistic errors, and writes platform error reports.
- `ozon_ord_sync.sheets_reader` — Google Sheets CSV access, row parsing, filtering, and validation.
- `ozon_ord_sync.ozon_ord_mapping` — conversion from parsed sheet rows to Ozon ORD payload dataclasses.
- `ozon_ord_sync.ozon_ord_api` — Ozon ORD HTTP clients.
- `ozon_ord_sync.apps_script_client` — Google Apps Script HTTP client for writing platform errors back.
- `ozon_ord_sync.env_loader` — `.env` loading utility.

The root `main.py` remains as a compatibility wrapper for `python main.py`.

## Target direction

Future refactoring should move toward explicit packages without changing the domain flow:

```text
ozon_ord_sync/
  cli.py
  config/
  domain/
    models.py
    mapping.py
  application/
    sync_service.py
  infrastructure/
    google_sheets.py
    ozon_ord.py
    apps_script.py
```

The next safe step is to extract dataclasses from `sheets_reader.py` and `ozon_ord_mapping.py` into domain model modules. That will reduce coupling between parsers, mappers, and HTTP clients before any behavior changes.
