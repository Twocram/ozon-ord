# Apps Script и `.env`

## Что изменилось в проекте

Теперь проект читает секреты и настройки из файла `.env`. Вручную экспортировать переменные перед каждым запуском больше не нужно.

Текущая логика проекта:

1. Скрипт читает Google Sheets по публичной CSV-ссылке.
2. Для каждой строки ищет площадку в ОЗОН ОРД по URL из `Ссылка на канал`.
3. Ошибка по площадке фиксируется в двух случаях:
   - площадка не найдена;
   - найдено больше одной площадки.
4. Если площадка найдена ровно одна, скрипт продолжает подготовку статистики.
5. Если есть ошибки площадок:
   - они сохраняются в локальный `platform_errors.json`;
   - если подключён Apps Script, они записываются в колонку `Ошибка площадки`.

## Что нужно сделать один раз

### 1. Создать `.env`

Скопируйте [.env.example](/Users/artyom/Documents/projects/ozon-ord/.env.example:1) в `.env`:

```bash
cp .env.example .env
```

Заполните в `.env` реальные значения:

```dotenv
OZON_ORD_API_KEY=your_external_api_key
OZON_ORD_BASE_URL=https://ord.ozon.ru
OZON_ORD_TIMEOUT=30

OZON_ORD_COOKIE=your_browser_cookie_header
OZON_ORD_APP_NAME=ord-ui
OZON_ORD_APP_VERSION=release/OORD-2732

GOOGLE_APPS_SCRIPT_WEB_APP_URL=https://script.google.com/macros/s/your-script-id/exec
GOOGLE_APPS_SCRIPT_TOKEN=optional_shared_secret
GOOGLE_APPS_SCRIPT_TIMEOUT=30
```

`.env` уже добавлен в `.gitignore`, в git он не попадёт.

### 2. Создать Google Apps Script

1. Откройте `https://script.google.com/`.
2. Создайте новый проект.
3. Вставьте код ниже в `Code.gs`.
4. Укажите ID вашей таблицы в `SPREADSHEET_ID`.
5. При желании задайте `SCRIPT_TOKEN`.

```javascript
const SPREADSHEET_ID = '1PuvoA3GcHIger8bXYR0uY_jIhj_3LZ7ieypF1IcGcIw';
const SHEET_NAME = '';
const ERROR_COLUMN_NAME = 'Ошибка площадки';
const SCRIPT_TOKEN = '';

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');

    if (SCRIPT_TOKEN && payload.token !== SCRIPT_TOKEN) {
      return jsonResponse({ ok: false, error: 'unauthorized' });
    }

    if (payload.action !== 'update_platform_errors') {
      return jsonResponse({ ok: false, error: 'unsupported_action' });
    }

    const rows = Array.isArray(payload.rows) ? payload.rows : [];
    const spreadsheet = SpreadsheetApp.openById(SPREADSHEET_ID);
    const sheet = SHEET_NAME
      ? spreadsheet.getSheetByName(SHEET_NAME)
      : spreadsheet.getSheets()[0];

    if (!sheet) {
      return jsonResponse({ ok: false, error: 'sheet_not_found' });
    }

    const header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
    const errorColumnIndex = header.indexOf(ERROR_COLUMN_NAME) + 1;

    if (errorColumnIndex === 0) {
      return jsonResponse({ ok: false, error: 'error_column_not_found' });
    }

    const updated = [];

    rows.forEach((row) => {
      const rowNumber = Number(row.row_number);
      const value = row.platform_error || 'Не найдено';

      if (rowNumber >= 2) {
        sheet.getRange(rowNumber, errorColumnIndex).setValue(value);
        updated.push({ row_number: rowNumber, value });
      }
    });

    return jsonResponse({ ok: true, updated });
  } catch (error) {
    return jsonResponse({
      ok: false,
      error: String(error && error.message ? error.message : error),
    });
  }
}

function jsonResponse(payload) {
  return ContentService
    .createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}
```

### 3. Задеплоить Apps Script как Web App

1. Нажмите `Deploy` -> `New deployment`.
2. Выберите `Web app`.
3. `Execute as`: `Me`.
4. `Who has access`: `Anyone with the link`.
5. Нажмите `Deploy`.
6. Скопируйте `Web app URL`.

Этот URL вставьте в `.env` как:

```dotenv
GOOGLE_APPS_SCRIPT_WEB_APP_URL=https://script.google.com/macros/s/your-script-id/exec
```

Если в скрипте задали `SCRIPT_TOKEN`, то его же укажите в `.env`:

```dotenv
GOOGLE_APPS_SCRIPT_TOKEN=your_secret_token
```

## Как запускать

После настройки `.env` команды становятся такими:

Проверка чтения и маппинга:

```bash
python3 main.py preview
```

Dry-run без записи в ОЗОН ОРД:

```bash
python3 main.py sync
```

Боевая отправка в ОЗОН ОРД:

```bash
python3 main.py sync --send
```

## Что пишет Apps Script

Python отправляет в Apps Script JSON такого формата:

```json
{
  "action": "update_platform_errors",
  "token": "optional_shared_secret",
  "rows": [
    {
      "row_number": 12,
      "creative_id": "2W5zF...",
      "channel_url": "https://t.me/example",
      "platform_error": "Не найдено"
    },
    {
      "row_number": 15,
      "creative_id": "2W5zF...",
      "channel_url": "https://t.me/example2",
      "platform_error": "Найдено больше одной"
    }
  ]
}
```

## Что важно помнить

- `API key` Google Sheets для записи не подходит, поэтому запись ошибок в таблицу идёт через Apps Script.
- Для ОЗОН ОРД проект использует два вида доступа:
  - `OZON_ORD_API_KEY` для внешнего API и поиска сущностей;
  - `OZON_ORD_COOKIE` для admin endpoint отправки статистики.
- Если `GOOGLE_APPS_SCRIPT_WEB_APP_URL` не задан, ошибки всё равно сохраняются в локальный `platform_errors.json`.
