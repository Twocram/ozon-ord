# Apps Script и `.env`

## Что изменилось в проекте

Теперь проект читает секреты и настройки из файла `.env`. Вручную экспортировать переменные перед каждым запуском больше не нужно.

Текущая логика проекта:

1. Скрипт читает Google Sheets по публичной CSV-ссылке.
2. Обрабатывает только строки, где в колонке `Исполнитель` стоит значение `100б`.
3. Для каждой подходящей строки ищет площадку в ОЗОН ОРД по URL из `Ссылка на канал`.
4. Ошибка по площадке фиксируется в двух случаях:
   - площадка не найдена;
   - найдено больше одной площадки.
5. Если площадка найдена ровно одна, скрипт продолжает подготовку статистики.
6. Если статистика по креативу уже есть в базе, в таблицу записывается ошибка `Креатив уже есть в базе`.
7. Если ошибка связана с площадкой, запросы на создание выходов не отправляются.
8. Если есть ошибки:
   - они сохраняются в локальный `platform_errors.json`;
   - если подключён Apps Script, они записываются в колонку `Ошибка`.

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
const ERROR_COLUMN_NAME = 'Ошибка';
const SCRIPT_TOKEN = '';

function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents || '{}');

    if (SCRIPT_TOKEN && payload.token !== SCRIPT_TOKEN) {
      return jsonResponse({ ok: false, error: 'unauthorized' });
    }

    const rows = Array.isArray(payload.rows) ? payload.rows : [];

    if (payload.action === 'update_creative_erids') {
      // Writes erid values into the creative spreadsheet (a different document),
      // opened by the spreadsheet_id passed from the script.
      const eridSpreadsheet = payload.spreadsheet_id
        ? SpreadsheetApp.openById(payload.spreadsheet_id)
        : SpreadsheetApp.openById(SPREADSHEET_ID);
      const eridSheet = payload.sheet_name
        ? eridSpreadsheet.getSheetByName(payload.sheet_name)
        : eridSpreadsheet.getSheets()[0];

      if (!eridSheet) {
        return jsonResponse({ ok: false, error: 'sheet_not_found' });
      }

      const eridHeader = eridSheet
        .getRange(1, 1, 1, eridSheet.getLastColumn())
        .getValues()[0];
      const eridColumnName = payload.erid_column || 'erid';
      const eridColumnIndex = eridHeader.indexOf(eridColumnName) + 1;

      if (eridColumnIndex === 0) {
        return jsonResponse({ ok: false, error: 'erid_column_not_found' });
      }

      const eridUpdated = [];
      rows.forEach((row) => {
        const rowNumber = Number(row.row_number);
        if (rowNumber >= 2 && row.erid) {
          eridSheet.getRange(rowNumber, eridColumnIndex).setValue(row.erid);
          eridUpdated.push({ row_number: rowNumber, erid: row.erid });
        }
      });

      return jsonResponse({ ok: true, updated: eridUpdated });
    }

    if (payload.action === 'update_document_checks') {
      const checkSpreadsheet = payload.spreadsheet_id
        ? SpreadsheetApp.openById(payload.spreadsheet_id)
        : SpreadsheetApp.openById(SPREADSHEET_ID);
      const checkSheet = payload.sheet_name
        ? checkSpreadsheet.getSheetByName(payload.sheet_name)
        : checkSpreadsheet.getSheets()[0];

      if (!checkSheet) {
        return jsonResponse({ ok: false, error: 'sheet_not_found' });
      }

      const checkHeader = checkSheet
        .getRange(1, 1, 1, checkSheet.getLastColumn())
        .getValues()[0];
      const checkColumnName = payload.check_column || 'Проверка';
      const checkColumnIndex = checkHeader.indexOf(checkColumnName) + 1;

      if (checkColumnIndex === 0) {
        return jsonResponse({ ok: false, error: 'check_column_not_found' });
      }

      const checkUpdated = [];
      rows.forEach((row) => {
        const rowNumber = Number(row.row_number);
        const value = row.value || row.check || 'Проверьте вручную';
        if (rowNumber >= 2) {
          checkSheet.getRange(rowNumber, checkColumnIndex).setValue(value);
          checkUpdated.push({ row_number: rowNumber, value });
        }
      });

      return jsonResponse({ ok: true, updated: checkUpdated });
    }

    if (payload.action !== 'update_platform_errors') {
      return jsonResponse({ ok: false, error: 'unsupported_action' });
    }

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
      const value = row.error || row.platform_error || 'Не найдено';

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
      "error": "Площадка не найдена"
    },
    {
      "row_number": 15,
      "creative_id": "2W5zF...",
      "channel_url": "https://t.me/example2",
      "error": "Найдено больше одной площадки"
    }
  ]
}
```

## Запись erid в таблицу креативов (другой документ)

Таблица креативов — это **отдельный** Google-документ (не таблица статистики). Тем не менее **отдельный Apps Script создавать не нужно**: тот же самый Web App пишет и в таблицу статистики (ошибки), и в таблицу креативов (erid). Скрипт открывает нужный документ через `SpreadsheetApp.openById(...)`, а Python передаёт `spreadsheet_id` таблицы креативов в запросе.

Что делает команда: после создания креатива в ОЗОН ОРД получает его `erid` (marker) и записывает его в колонку `erid` соответствующей строки таблицы креативов.

### Что нужно сделать один раз

1. **Добавьте колонку в таблицу креативов.** Заголовок (первая строка) должен быть ровно `erid`. Если назовёте иначе — скажите, поменяю значение по умолчанию в коде.

2. **Обновите код Apps Script.** Откройте **тот же** проект скрипта на `https://script.google.com/`, который уже используется для записи ошибок (если его ещё нет — сначала создайте по инструкции выше). Полностью замените содержимое `Code.gs` на актуальный код из раздела [2. Создать Google Apps Script](#2-создать-google-apps-script) выше — он теперь поддерживает действие `update_creative_erids`.

   Константу `SPREADSHEET_ID` менять **не нужно** — она остаётся id таблицы статистики (используется для записи ошибок и как запасной вариант). Для записи erid документ открывается по `spreadsheet_id` из запроса.

3. **Дайте доступ.** Аккаунт Google, под которым скрипт выполняется (`Execute as: Me`), должен иметь права **редактора** на таблицу креативов. Если таблицу создавал другой человек — расшарьте её на этот аккаунт с правом «Редактор».

4. **Передеплойте.** `Deploy` -> `Manage deployments` -> у активного деплоя нажмите «карандаш» -> `Version: New version` -> `Deploy`.

   > Важно: без новой версии деплоя Web App продолжит отдавать старый код. URL при этом **не меняется** — тот же `GOOGLE_APPS_SCRIPT_WEB_APP_URL` в `.env` подходит.

5. **Проверьте `.env`.** Должен быть задан `GOOGLE_APPS_SCRIPT_WEB_APP_URL` (тот же URL). Если используете `SCRIPT_TOKEN` — тот же `GOOGLE_APPS_SCRIPT_TOKEN`.

### Как запускать

```bash
# Только чтение договоров + сверка (ничего не создаёт, erid не пишет):
python3 main.py read-creative-contracts

# Создать недостающих контрагентов/договоры/креативы и записать erid в таблицу:
python3 main.py read-creative-contracts --create-missing
```

erid пишется только при `--create-missing` (marker появляется лишь при создании креатива). Если `GOOGLE_APPS_SCRIPT_WEB_APP_URL` не задан, создание пройдёт, но erid в таблицу не запишется (без ошибки).

Формат запроса, который шлёт Python:

```json
{
  "action": "update_creative_erids",
  "token": "optional_shared_secret",
  "spreadsheet_id": "1Ix4o8_aHqxa3ySfYbtYG43l9d_zNGGqXKW-Tk8zLmGM",
  "erid_column": "erid",
  "rows": [
    { "row_number": 2, "erid": "2W5zFGTPAL1" }
  ]
}
```

Возможные ошибки в ответе: `sheet_not_found`, `erid_column_not_found` (нет колонки `erid` в заголовке), `unauthorized` (не совпал `SCRIPT_TOKEN`).

## Что важно помнить

- `API key` Google Sheets для записи не подходит, поэтому запись ошибок в таблицу идёт через Apps Script.
- Для ОЗОН ОРД проект использует два вида доступа:
  - `OZON_ORD_API_KEY` для внешнего API и поиска сущностей;
  - `OZON_ORD_COOKIE` для admin endpoint отправки статистики.
- Если `GOOGLE_APPS_SCRIPT_WEB_APP_URL` не задан, ошибки всё равно сохраняются в локальный `platform_errors.json`.
