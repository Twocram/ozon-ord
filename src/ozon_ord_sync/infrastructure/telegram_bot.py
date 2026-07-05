from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
import re
from typing import Any

START_TEXT = (
    "👋 Добро пожаловать в бот Ozon ORD Sync.\n\n"
    "Как пользоваться:\n"
    "1. Выполните команду /set_token <OZON_ORD_COOKIE>\n"
    "2. Дождитесь сообщения об успешном сохранении\n"
    "3. Выполните /upload для отправки статистики\n\n"
    "Команды:\n"
    "🔑 /set_token <OZON_ORD_COOKIE> — сохранить cookie\n"
    "🚀 /upload — отправить статистику"
)
SET_TOKEN_TEXT = (
    "🔑 Пожалуйста, добавьте ваш token в команду.\n"
    "Пример: /set_token <OZON_ORD_COOKIE>"
)
EMPTY_COOKIE_TEXT = "⚠️ Пустой token. Передайте значение OZON_ORD_COOKIE в команде."
API_BASE_URL = "http://api:8765"
OZON_BASE_URL = "https://ord.ozon.ru"


@dataclass
class ApiResult:
    status: int
    payload: dict[str, Any]


@dataclass
class TelegramBotConfig:
    telegram_bot_token: str
    api_base_url: str
    api_token: str
    ozon_base_url: str

    @classmethod
    def from_env(cls) -> TelegramBotConfig:
        return cls(
            telegram_bot_token=_required_env("TELEGRAM_BOT_TOKEN"),
            api_base_url=os.getenv("OZON_ORD_SYNC_API_BASE_URL", API_BASE_URL).strip()
            or API_BASE_URL,
            api_token=_required_env("OZON_ORD_SYNC_API_TOKEN"),
            ozon_base_url=os.getenv("OZON_ORD_BASE_URL", OZON_BASE_URL).strip()
            or OZON_BASE_URL,
        )


def run_telegram_bot() -> None:
    try:
        from telegram import BotCommand, Update
        from telegram.ext import Application, CommandHandler, ContextTypes
    except ImportError as error:
        raise RuntimeError(
            "python-telegram-bot is required for the bot service"
        ) from error

    config = TelegramBotConfig.from_env()
    application = Application.builder().token(config.telegram_bot_token).build()

    async def post_init(application: Application) -> None:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Помощь"),
                BotCommand("set_token", "Сохранить cookie"),
                BotCommand("upload", "Загрузить статистику"),
            ]
        )

    async def start_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is not None:
            await message.reply_text(START_TEXT)

    async def upload_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return

        await message.reply_text("🚀 Запускаю отправку статистики...")
        result = await asyncio.to_thread(
            _post_api,
            config,
            "/api/sync/statistics",
            {},
        )
        await message.reply_text(format_upload_result(result.payload, result.status))

    async def set_token_command(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        message = update.effective_message
        if message is None:
            return

        cookie = extract_command_value(message.text or "")
        if not cookie:
            await message.reply_text(SET_TOKEN_TEXT)
            return

        if not cookie.strip():
            await message.reply_text(EMPTY_COOKIE_TEXT)
            return

        result = await asyncio.to_thread(
            _post_api,
            config,
            "/api/auth/ozon-cookie",
            {
                "cookie": cookie,
                "baseUrl": config.ozon_base_url,
                "capturedAt": datetime.now(timezone.utc).isoformat(),
            },
        )
        if result.status >= 400 or result.payload.get("ok") is not True:
            await message.reply_text(
                truncate_message(
                    "❌ Не удалось сохранить cookie.\n"
                    + extract_error_message(result.payload, result.status)
                )
            )
            return

        await message.reply_text(
            f"✅ Cookie сохранён. Найдено записей: {result.payload.get('cookieEntries', 0)}"
        )

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("upload", upload_command))
    application.add_handler(CommandHandler("set_token", set_token_command))

    application.post_init = post_init

    print("🤖 Запуск Telegram-бота")
    application.run_polling(allowed_updates=Update.ALL_TYPES)



def extract_command_value(text: str) -> str:
    _, _, value = text.partition(" ")
    return value.strip()


def truncate_message(text: str, max_length: int = 4000) -> str:
    return text if len(text) <= max_length else f"{text[: max_length - 3]}..."


def format_upload_result(payload: dict[str, Any], status: int) -> str:
    if status >= 400 or payload.get("ok") is not True:
        lines = ["❌ Ошибка при отправке статистики."]
        error = payload.get("error")
        if isinstance(error, str) and error:
            lines.append(_translate_error_text(error))

        mapping_errors = _translate_error_list(_to_string_list(payload.get("mapping_errors")))
        resolution_errors = _translate_error_list(
            _to_string_list(payload.get("resolution_errors"))
        )
        if mapping_errors:
            lines.extend(["", "Ошибки маппинга:", *mapping_errors[:20]])
        if resolution_errors:
            lines.extend(["", "Ошибки проверки данных:", *resolution_errors[:20]])
        if len(lines) == 1:
            lines.append(f"HTTP {status}")
        return truncate_message("\n".join(lines))

    lines = [
        "✅ Отправка статистики завершена.",
        f"Подходящих строк: {payload.get('rows_eligible', 0)}",
        f"Подготовлено выходов: {payload.get('statistics_prepared', 0)}",
    ]
    skipped_errors = _translate_error_list(
        _to_string_list(
            (payload.get("ozon_response") or {}).get("skipped_errors")
            if isinstance(payload.get("ozon_response"), dict)
            else None
        )
    )
    if skipped_errors:
        lines.extend(["", "⚠️ Предупреждения:", *skipped_errors[:20]])
    return truncate_message("\n".join(lines))


def extract_error_message(payload: dict[str, Any], status: int) -> str:
    error = payload.get("error")
    if isinstance(error, str) and error:
        return _translate_error_text(error)
    return f"HTTP {status}"


def _to_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _translate_error_list(errors: list[str]) -> list[str]:
    return [_translate_error_text(error) for error in errors]


def _translate_error_text(text: str) -> str:
    translated = text.strip()
    if not translated:
        return translated

    translated = re.sub(r"^Row (\d+):\s*", r"Строка \1: ", translated)

    replacements = {
        "Platform not found:": "Платформа не найдена:",
        "Platform not found": "Платформа не найдена",
        "Platform matched more than one:": "Найдено больше одной платформы:",
        "Platform matched more than one": "Найдено больше одной платформы",
        "Creative marker not found:": "Маркер креатива не найден:",
        "Creative marker not found": "Маркер креатива не найден",
        "Creative not found for marker=": "Креатив не найден для маркера=",
        "Creative missing": "Креатив не найден",
        "missing required mapping fields:": "Отсутствуют обязательные поля:",
        "missing required mapping fields": "Отсутствуют обязательные поля",
        "missing required platform fields:": "Отсутствуют обязательные поля платформы:",
        "missing required platform fields": "Отсутствуют обязательные поля платформы",
        "missing channel_url for platform payload": "Отсутствует channel_url для платформы",
        "missing manager": "отсутствует manager",
        "missing month": "отсутствует month",
        "missing creative_id": "отсутствует creative_id",
        "missing channel_url": "отсутствует channel_url",
        "missing contractor": "отсутствует contractor",
        "missing price_with_tax": "отсутствует price_with_tax",
        "missing publication_date": "отсутствует publication_date",
        "missing reach": "отсутствует reach",
        "cookie is not set": "Cookie не установлен.",
        "unauthorized": "Нет доступа.",
    }
    for source, target in replacements.items():
        translated = translated.replace(source, target)
    return translated


def _post_api(
    config: TelegramBotConfig,
    path: str,
    payload: dict[str, Any],
) -> ApiResult:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url=f"{config.api_base_url.rstrip('/')}{path}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return ApiResult(
                status=response.status,
                payload=_read_json_payload(response.read().decode("utf-8")),
            )
    except urllib.error.HTTPError as error:
        return ApiResult(
            status=error.code,
            payload=_read_json_payload(error.read().decode("utf-8", errors="replace")),
        )
    except urllib.error.URLError as error:
        return ApiResult(status=599, payload={"ok": False, "error": str(error)})


def _read_json_payload(raw: str) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": raw}
    return payload if isinstance(payload, dict) else {"ok": False, "error": raw}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Environment variable {name} is required")
    return value
