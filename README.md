# ozon-ord-sync

`ozon-ord-sync` автоматизирует перенос данных из Google Sheets в Ozon ORD. Проект подготавливает и выгружает статистику рекламных размещений, проверяет договоры и чеки/акты, находит связанные сущности ORD и формирует акты. Ошибки документов и спорные случаи можно записывать обратно в колонку `Проверка` через Google Apps Script.

## Возможности

- чтение статистики, площадок, креативов и документов из Google Sheets;
- поиск площадок, креативов, договоров и контрагентов в ORD;
- подготовка и отправка статистики, включая режим для браузерного расширения;
- извлечение данных из PDF и изображений;
- сверка ФИО, сумм, дат, типа документа и НДС;
- проверка номера чека самозанятого и существования чека в ЛК НПД;
- поиск дубликатов актов перед созданием;
- отметка нескольких Telegram-каналов и ошибок документов в Google Sheets.

## Требования

- Python 3.9+;
- [uv](https://docs.astral.sh/uv/) — для локального запуска;
- ключ внешнего API Ozon ORD;
- cookies активной сессии ORD — для admin API.

OCR изображений и сканированных PDF использует Swift, Vision и PDFKit, поэтому сейчас доступен только на macOS. Текстовые PDF обрабатываются без OCR.

## Установка

```bash
git clone git@github.com:Twocram/ozon-ord.git
cd ozon-ord
cp .env.example .env
uv sync --locked
```

Основные переменные `.env`:

```dotenv
OZON_ORD_API_KEY=your_external_api_key
OZON_ORD_COOKIE=your_browser_cookie_header
OZON_ORD_BASE_URL=https://ord.ozon.ru
OZON_ORD_SYNC_API_TOKEN=change-me
```

Для записи результатов в Google Sheets дополнительно задаются:

```dotenv
GOOGLE_APPS_SCRIPT_WEB_APP_URL=https://script.google.com/macros/s/your-script-id/exec
GOOGLE_APPS_SCRIPT_TOKEN=optional_shared_secret
```

Полный список находится в [`.env.example`](.env.example).

## Статистика

Проверить строки и сформированные payload без отправки:

```bash
uv run ozon-ord-sync preview
```

Отправить статистику напрямую через admin API:

```bash
uv run ozon-ord-sync sync --send
```

ORD может отклонить серверную отправку с `Ozon anti-bot challenge required`. В этом случае endpoint `/api/extension/statistics/prepare` подготавливает payload, а браузерное расширение отправляет его из авторизованной вкладки ORD.

Строки со значением `к/а` в колонке `Креатив` пропускаются.

## Проверка документов и создание актов

Просмотреть строки таблицы проверки документов:

```bash
uv run ozon-ord-sync preview-document-check
```

Извлечь данные чеков и актов:

```bash
uv run ozon-ord-sync read-document-check-receipts
```

Записать предупреждения в колонку `Проверка`:

```bash
uv run ozon-ord-sync mark-contract-channel-checks --send
```

Подготовить черновики актов:

```bash
uv run ozon-ord-sync build-document-check-invoice-payloads \
  --output-file invoice-payloads.json
```

Проверить один payload без создания:

```bash
uv run ozon-ord-sync create-extended-invoice \
  --payload-file invoice.json
```

Создать акт после duplicate-check:

```bash
uv run ozon-ord-sync create-extended-invoice \
  --payload-file invoice.json \
  --send
```

`--force` разрешает создание при найденном дубликате и должен использоваться только вручную.

## Другие команды

```bash
uv run ozon-ord-sync preview-creatives
uv run ozon-ord-sync read-creative-contracts
uv run ozon-ord-sync preview-platforms
uv run ozon-ord-sync sync-platforms --send
uv run ozon-ord-sync probe-api
uv run ozon-ord-sync --help
```

Ссылки на таблицы можно переопределить параметрами `--sheet-url`, `--creative-sheet-url` и `--document-check-sheet-url`.

## Локальный API и Docker

Запустить API:

```bash
docker compose up --build api
```

Сервис будет доступен по адресу `http://127.0.0.1:8765`. Сохранённые cookies находятся в `./.runtime/ozon-cookie.json`.

Основные endpoints:

- `GET /api/status`
- `POST /api/auth/ozon-cookie`
- `POST /api/auth/validate`
- `POST /api/extension/statistics/prepare`
- `POST /api/preview/statistics`
- `POST /api/preview/document-check`
- `POST /api/preview/platforms`
- `POST /api/sync/statistics`
- `POST /api/sync/platforms`

## Развёртывание

Для запуска API на VPS:

```bash
cp .env.example .env
# заполнить .env
docker compose up -d --build api
docker compose logs -f api
```

Workflow `Deploy` запускается после успешного CI в `main`. Для него нужны GitHub secrets:

- `DEPLOY_HOST`
- `DEPLOY_PORT`
- `DEPLOY_USER`
- `DEPLOY_SSH_KEY`
- `DEPLOY_PATH`

## Проверки

```bash
uvx ruff check .
uv run python -m unittest discover -s tests -q
uv build
```

Описание слоёв проекта находится в [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md), настройка Google Apps Script — в [`APPS_SCRIPT.md`](APPS_SCRIPT.md).
