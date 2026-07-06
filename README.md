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

## Run Telegram bot with Docker

The bot service uses `python-telegram-bot` and talks to the local API.

Set these in `.env`:

```dotenv
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
OZON_ORD_SYNC_API_TOKEN=change-me
OZON_ORD_SYNC_API_BASE_URL=http://api:8765
```

Then start services:

```bash
docker compose up --build api bot browser
```

Telegram commands:

- `/start` — help
- `/login` — show VPS browser instructions
- `/set_token <OZON_ORD_COOKIE>` — save cookie
- `/upload` — run statistics upload

`/set-token` is not used because Telegram commands support underscores, not dashes.

## Get ORD cookie from VPS browser

Ozon can reject cookies copied from your local browser because the bot uploads from the VPS IP.
Use the bundled Chromium container to log in from the same VPS IP.

1. Start the browser service:

```bash
docker compose up -d browser
```

2. Open an SSH tunnel from your laptop:

```bash
ssh -L 3000:127.0.0.1:3000 root@<VPS_IP>
```

3. Open locally:

```text
http://127.0.0.1:3000
```

4. In that browser, log in to `https://ord.ozon.ru` and pass challenge.
5. Copy `OZON_ORD_COOKIE` from that VPS browser and send it to bot:

```text
/set_token __Secure-...; sid=...
```

## Run on a VPS

1. Install Docker and Docker Compose plugin.
2. Clone the repo on the server:

```bash
git clone <your-repo-url>
cd ozon-ord
```

3. Create `.env`:

```bash
cp .env.example .env
```

4. Fill at least these values:

```dotenv
OZON_ORD_SYNC_API_TOKEN=some-long-random-string
OZON_ORD_SYNC_API_BASE_URL=http://api:8765
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
OZON_ORD_API_KEY=your_external_api_key
```

5. Start services in background:

```bash
docker compose up -d --build api bot browser
```

6. Check logs:

```bash
docker compose logs -f api bot browser
```

Useful commands:

```bash
docker compose ps
docker compose restart bot
docker compose restart api
docker compose restart browser
docker compose up -d --build
```

Notes:
- bot works only while `bot` container is running
- VPS browser is available only through SSH tunnel on `127.0.0.1:3000`
- browser profile is persisted in `./.runtime/browser-config`
- saved cookie is persisted in `./.runtime/ozon-cookie.json`
- if you do not need public API access on the VPS, bind port `8765` to localhost only

## CI/CD to VPS

The repo now has two GitHub Actions workflows:

- `CI` — lint, tests, build
- `Deploy` — runs after successful `CI` on `main` and updates the VPS over SSH

### What happens on deploy

On every push to `main`:

1. GitHub Actions waits for `CI` to pass
2. connects to your VPS over SSH
3. runs:

```bash
cd <deploy-path>
git fetch origin
git checkout main
git reset --hard origin/main
# deploy script uses docker compose if available, otherwise docker-compose
$COMPOSE rm -sf api bot || true
$COMPOSE up -d --build --remove-orphans api bot browser
docker image prune -f
```

### GitHub secrets to add

In GitHub repo settings -> `Secrets and variables` -> `Actions`, add:

- `DEPLOY_HOST` — VPS IP or domain
- `DEPLOY_PORT` — SSH port, usually `22`
- `DEPLOY_USER` — SSH user on VPS
- `DEPLOY_SSH_KEY` — private SSH key for that user
- `DEPLOY_PATH` — absolute path to project on VPS, for example `/home/deploy/ozon-ord`

### One-time VPS preparation for deploys

1. Make sure the repo is already cloned into `DEPLOY_PATH`
2. Make sure `.env` exists there
3. Make sure `git fetch origin` works on the server

Check it manually on the VPS:

```bash
cd /home/deploy/ozon-ord
git fetch origin
# new Compose plugin:
docker compose up -d --build api bot browser

# old Compose binary:
docker-compose up -d --build api bot browser
```

If the repo is private, configure SSH deploy key or another git auth method on the VPS first.

### Manual redeploy

You can also run the `Deploy` workflow manually from the GitHub Actions tab with `workflow_dispatch`.

## Useful API endpoints

- `GET /api/status`
- `POST /api/auth/ozon-cookie`
- `POST /api/auth/validate`
- `POST /api/preview/statistics`
- `POST /api/preview/platforms`
- `POST /api/sync/statistics`
- `POST /api/sync/platforms`
