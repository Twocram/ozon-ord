# Ozon ORD Sync architecture

The project is now packaged as `ozon_ord_sync` under `src/`. This keeps imports stable, enables installation as a CLI, and creates room to split responsibilities further without changing runtime behavior.

## Current layers

- `ozon_ord_sync.cli` — CLI entry point and command orchestration.
- `ozon_ord_sync.application.sync_service` — application workflow: builds sync batches, resolves Ozon IDs, handles duplicate statistic errors, and writes platform error reports.
- `ozon_ord_sync.domain.models` — shared parsed row, validation issue, Ozon ORD payload, and sync batch dataclasses.
- `ozon_ord_sync.infrastructure.google_sheets` — Google Sheets CSV access, row parsing, filtering, and validation.
- `ozon_ord_sync.domain.mapping` — conversion from parsed sheet rows to Ozon ORD payload models.
- `ozon_ord_sync.infrastructure.ozon_ord` — Ozon ORD HTTP clients.
- `ozon_ord_sync.infrastructure.apps_script` — Google Apps Script HTTP client for writing platform errors back.
- `ozon_ord_sync.config.env` — `.env` loading utility.

The root `main.py` remains as a compatibility wrapper for `python main.py`. The former package-level module names (`ozon_ord_sync.sync_service`, `ozon_ord_sync.sheets_reader`, and similar) are also kept as compatibility wrappers while the codebase migrates to the layered imports.

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
    sync_service.py
  infrastructure/
    google_sheets.py
    ozon_ord.py
    apps_script.py
```

The next safe step is to split Google Sheets transport from row parsing/validation. That will keep network access in infrastructure while moving sheet normalization rules closer to the application/domain boundary.
