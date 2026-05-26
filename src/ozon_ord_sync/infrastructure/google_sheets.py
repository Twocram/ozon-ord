from __future__ import annotations

import csv
import json
import re
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO
from itertools import islice
from typing import Any, TypeVar


DEFAULT_SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1PuvoA3GcHIger8bXYR0uY_jIhj_3LZ7ieypF1IcGcIw/edit?gid=0#gid=0"
)
DEFAULT_PLATFORM_SHEET_NAME = "Лист3"
TARGET_EXECUTOR = "100б"


@dataclass
class ParsedRow:
    row_number: int
    manager: str | None
    month: date | None
    platform: str | None
    creative_id: str | None
    channel_url: str | None
    executor: str | None
    contractor: str | None
    price_with_tax: Decimal | None
    publication_date: date | None
    reach: int | None
    mark: str | None
    error: str | None
    raw: dict[str, Any]


@dataclass
class ParsedPlatformRow:
    row_number: int
    name: str | None
    url: str | None
    raw: dict[str, Any]


@dataclass
class RowIssue:
    row_number: int
    messages: list[str]


ParsedSheetRow = TypeVar("ParsedSheetRow", ParsedRow, ParsedPlatformRow)


def google_sheet_csv_url(
    sheet_url: str,
    gid: str | int | None = None,
    sheet_name: str | None = None,
) -> str:
    parsed = urllib.parse.urlparse(sheet_url)
    path_match = re.search(r"/spreadsheets/d/([^/]+)", parsed.path)
    if not path_match:
        raise ValueError("Unsupported Google Sheets URL format")

    sheet_id = path_match.group(1)
    if sheet_name is not None:
        return (
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq"
            f"?tqx=out:csv&sheet={urllib.parse.quote(sheet_name)}"
        )

    fragment_params = urllib.parse.parse_qs(parsed.fragment)
    query_params = urllib.parse.parse_qs(parsed.query)
    resolved_gid = str(
        gid
        if gid is not None
        else fragment_params.get("gid", query_params.get("gid", ["0"]))[0]
    )

    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
        f"?format=csv&gid={resolved_gid}"
    )


def fetch_sheet_rows(
    sheet_url: str = DEFAULT_SHEET_URL,
    gid: str | int | None = None,
    sheet_name: str | None = None,
) -> tuple[list[str], list[list[str]]]:
    csv_url = google_sheet_csv_url(sheet_url, gid=gid, sheet_name=sheet_name)
    with urllib.request.urlopen(csv_url, timeout=30) as response:
        payload = response.read().decode("utf-8-sig")

    reader = csv.reader(StringIO(payload))
    rows = list(reader)
    if not rows:
        return [], []

    return rows[0], rows[1:]


def parse_sheet(sheet_url: str = DEFAULT_SHEET_URL) -> tuple[list[str], list[ParsedRow]]:
    header, rows = fetch_sheet_rows(sheet_url)
    normalized_header = normalize_header(header)

    parsed_rows: list[ParsedRow] = []
    for offset, row in enumerate(rows, start=2):
        if is_effectively_empty(row):
            continue

        raw_row = build_raw_row(normalized_header, row)
        parsed_rows.append(
            ParsedRow(
                row_number=offset,
                manager=text_or_none(raw_row.get("manager")),
                month=parse_date(raw_row.get("month")),
                platform=text_or_none(raw_row.get("platform") or raw_row.get("ploschadka")),
                creative_id=text_or_none(raw_row.get("creative")),
                channel_url=text_or_none(
                    raw_row.get("channel_url")
                    or raw_row.get("platform")
                    or raw_row.get("ploschadka")
                ),
                executor=text_or_none(raw_row.get("executor")),
                contractor=text_or_none(raw_row.get("contractor")),
                price_with_tax=parse_decimal(
                    raw_row.get("price_with_tax") or raw_row.get("tsena")
                ),
                publication_date=parse_date(raw_row.get("publication_date")),
                reach=parse_int(raw_row.get("reach")),
                mark=text_or_none(raw_row.get("mark")),
                error=text_or_none(raw_row.get("error") or raw_row.get("platform_error")),
                raw=raw_row,
            )
        )

    return normalized_header, parsed_rows


def parse_platform_sheet(
    sheet_url: str = DEFAULT_SHEET_URL,
    sheet_name: str = DEFAULT_PLATFORM_SHEET_NAME,
) -> tuple[list[str], list[ParsedPlatformRow]]:
    candidates = [sheet_name]
    if sheet_name == DEFAULT_PLATFORM_SHEET_NAME:
        candidates.append("Лист 3")

    header: list[str] = []
    rows: list[list[str]] = []
    normalized_header: list[str] = []
    for candidate in dict.fromkeys(candidates):
        header, rows = fetch_sheet_rows(sheet_url, sheet_name=candidate)
        normalized_header = normalize_header(header)
        if {"platform_name", "platform_url"}.issubset(normalized_header):
            break

    if not normalized_header:
        normalized_header = normalize_header(header)

    parsed_rows: list[ParsedPlatformRow] = []
    for offset, row in enumerate(rows, start=2):
        if is_effectively_empty(row):
            continue

        raw_row = build_raw_row(normalized_header, row)
        parsed_rows.append(
            ParsedPlatformRow(
                row_number=offset,
                name=text_or_none(raw_row.get("platform_name")),
                url=text_or_none(raw_row.get("platform_url")),
                raw=raw_row,
            )
        )

    return normalized_header, parsed_rows


def normalize_header(header: list[str]) -> list[str]:
    known_names = {
        "menedzher": "manager",
        "mesyats": "month",
        "sotsset": "platform",
        "kreativ": "creative",
        "ploschadka": "channel_url",
        "ssylka_na_kanal": "channel_url",
        "ispolnitel": "executor",
        "k_a": "contractor",
        "tsena": "price_with_tax",
        "tsena_s_nalogom": "price_with_tax",
        "data_vyhoda": "publication_date",
        "ohvat": "reach",
        "mark": "mark",
        "oshibka": "error",
        "oshibka_ploshchadki": "error",
        "nazvanie_ploschadki": "platform_name",
        "nazvanie_ploshchadki": "platform_name",
        "url_ploschadki": "platform_url",
        "url_ploshchadki": "platform_url",
    }

    normalized: list[str] = []
    used_names: dict[str, int] = {}

    for index, column in enumerate(header):
        slug = slugify(column)
        base_name = known_names.get(slug) or slug or f"column_{index + 1}"
        count = used_names.get(base_name, 0)
        used_names[base_name] = count + 1
        normalized.append(base_name if count == 0 else f"{base_name}_{count + 1}")

    return normalized


def build_raw_row(header: list[str], row: list[str]) -> dict[str, Any]:
    padded_row = row + [""] * max(0, len(header) - len(row))
    raw_row: dict[str, Any] = {}
    for key, value in zip(header, padded_row):
        raw_row[key] = text_or_none(value)
    return raw_row


def is_effectively_empty(row: list[str]) -> bool:
    return not any(text_or_none(value) is not None for value in row)


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()
    return text or None


def parse_date(value: Any) -> date | None:
    text = text_or_none(value)
    if text is None:
        return None
    return date.fromisoformat(text)


def parse_decimal(value: Any) -> Decimal | None:
    text = text_or_none(value)
    if text is None:
        return None

    normalized = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def parse_int(value: Any) -> int | None:
    text = text_or_none(value)
    if text is None:
        return None

    digits = text.replace("\xa0", "").replace(" ", "")
    if not re.fullmatch(r"-?\d+", digits):
        return None
    return int(digits)


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    translit = (
        lowered.replace("ё", "e")
        .replace("й", "i")
        .replace("ц", "ts")
        .replace("у", "u")
        .replace("к", "k")
        .replace("е", "e")
        .replace("н", "n")
        .replace("г", "g")
        .replace("ш", "sh")
        .replace("щ", "sch")
        .replace("з", "z")
        .replace("х", "h")
        .replace("ъ", "")
        .replace("ф", "f")
        .replace("ы", "y")
        .replace("в", "v")
        .replace("а", "a")
        .replace("п", "p")
        .replace("р", "r")
        .replace("о", "o")
        .replace("л", "l")
        .replace("д", "d")
        .replace("ж", "zh")
        .replace("э", "e")
        .replace("я", "ya")
        .replace("ч", "ch")
        .replace("с", "s")
        .replace("м", "m")
        .replace("и", "i")
        .replace("т", "t")
        .replace("ь", "")
        .replace("б", "b")
        .replace("ю", "yu")
    )
    return re.sub(r"[^a-z0-9]+", "_", translit).strip("_")


def rows_to_json(rows: Iterable[ParsedSheetRow], limit: int = 3) -> str:
    payload = [asdict(row) for row in islice(rows, limit)]
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def filter_rows_for_processing(
    rows: list[ParsedRow], target_executor: str = TARGET_EXECUTOR
) -> list[ParsedRow]:
    target = _normalize_executor_value(target_executor)
    return [
        row
        for row in rows
        if _normalize_executor_value(row.executor) == target
    ]


def validate_rows(rows: list[ParsedRow]) -> list[RowIssue]:
    issues: list[RowIssue] = []
    required_fields = {
        "manager": "manager",
        "month": "month",
        "creative_id": "creative_id",
        "channel_url": "channel_url",
        "contractor": "contractor",
        "price_with_tax": "price_with_tax",
        "publication_date": "publication_date",
        "reach": "reach",
    }

    for row in rows:
        messages: list[str] = []

        for attr_name, label in required_fields.items():
            if getattr(row, attr_name) is None:
                messages.append(f"missing {label}")

        suspicious_columns = [
            key
            for key, value in row.raw.items()
            if key.startswith("column_") and text_or_none(value) is not None
        ]
        if suspicious_columns:
            messages.append(
                "unexpected values in unnamed columns: "
                + ", ".join(suspicious_columns[:5])
            )

        if messages:
            issues.append(RowIssue(row_number=row.row_number, messages=messages))

    return issues


def validate_platform_rows(rows: list[ParsedPlatformRow]) -> list[RowIssue]:
    issues: list[RowIssue] = []
    required_fields = {
        "name": "название площадки",
        "url": "URL площадки",
    }

    for row in rows:
        messages: list[str] = []
        for attr_name, label in required_fields.items():
            if getattr(row, attr_name) is None:
                messages.append(f"missing {label}")

        if row.url is not None:
            parsed_url = urllib.parse.urlparse(row.url)
            if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
                messages.append("invalid URL площадки")

        suspicious_columns = [
            key
            for key, value in row.raw.items()
            if key.startswith("column_") and text_or_none(value) is not None
        ]
        if suspicious_columns:
            messages.append(
                "unexpected values in unnamed columns: "
                + ", ".join(suspicious_columns[:5])
            )

        if messages:
            issues.append(RowIssue(row_number=row.row_number, messages=messages))

    return issues


def _normalize_executor_value(value: str | None) -> str | None:
    text = text_or_none(value)
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).casefold()
