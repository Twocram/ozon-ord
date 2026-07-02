# ozon-ord-sync

## Run API server with Docker

1. Create env file:

```bash
cp .env.example .env
```

2. Set at least:

```dotenv
OZON_ORD_SYNC_API_TOKEN=change-me
OZON_ORD_API_KEY=your_external_api_key
```

Add `OZON_ORD_COOKIE` too if you want to send statistics through the admin endpoint.

3. Start the API server:

```bash
docker compose up --build api
```

The server will be available at `http://127.0.0.1:8765`.

Cookie state is persisted in `./.runtime/ozon-cookie.json`.

## Useful endpoints

- `GET /api/status`
- `POST /api/auth/ozon-cookie`
- `POST /api/preview/statistics`
- `POST /api/preview/platforms`
- `POST /api/sync/statistics`
- `POST /api/sync/platforms`
