"""Normalisation and fuzzy matching for person / organisation names.

The same person reaches us written three different ways:

* the sheet "Контрагент" column — "СЗ Дорофеева ИЮНЬ", "ИП Иванов И.И.";
* the contract — full ФИО, sometimes declined ("Дорофеевой Алисы Михайловны");
* the "Чеки/Акты" file — frequently OCR'd, ALL CAPS, with Latin homoglyphs
  ("ДОРОФEEВА" where E is Latin).

So every comparison here is case-insensitive (everything is casefolded first),
ё is folded to е, Latin homoglyphs inside Cyrillic words are repaired, legal
forms / statuses / month names are dropped as noise and Russian case endings are
stripped before tokens are compared. Matching itself is a bipartite cover: every
token of the shorter name must map to a distinct token of the longer one, with
initials matching a full token by first letter.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# OCR routinely swaps visually identical Latin glyphs into Cyrillic words. Only
# applied to tokens that already mix both alphabets, so genuinely Latin names
# ("John Smith") are left alone.
_HOMOGLYPHS = str.maketrans(
    {
        "a": "а",
        "b": "в",
        "c": "с",
        "e": "е",
        "h": "н",
        "k": "к",
        "m": "м",
        "n": "п",
        "o": "о",
        "p": "р",
        "t": "т",
        "u": "и",
        "x": "х",
        "y": "у",
        "0": "о",
        "3": "з",
    }
)

# Words that carry no identity: legal forms, statuses, document labels, months.
# Kept in normalised form (casefolded, ё -> е) — see `normalize_name`.
NOISE_WORDS = frozenset(
    {
        # legal forms and statuses
        "ип",
        "ооо",
        "оао",
        "зао",
        "пао",
        "ао",
        "нао",
        "одо",
        "кфх",
        "сз",
        "самозанятый",
        "самозанятая",
        "самозанятого",
        "самозанятой",
        "самозанят",
        "индивидуальный",
        "индивидуального",
        "индивидуальным",
        "предприниматель",
        "предпринимателя",
        "предпринимателем",
        "физическое",
        "физического",
        "физлицо",
        "лицо",
        "лица",
        "лице",
        "гражданин",
        "гражданка",
        "общество",
        "ограниченной",
        "ответственностью",
        "компания",
        "организация",
        # document labels
        "продавец",
        "продавца",
        "покупатель",
        "покупателя",
        "заказчик",
        "заказчика",
        "исполнитель",
        "исполнителя",
        "получатель",
        "получателя",
        "плательщик",
        "плательщика",
        "директор",
        "директора",
        "генеральный",
        "генерального",
        "фио",
        "инн",
        "огрнип",
        "огрн",
        "кпп",
        "бик",
        "чек",
        "акт",
        "договор",
        "договора",
        "счет",
        "режим",
        "но",
        "наименование",
        "итого",
        "всего",
        "сумма",
        "суммы",
        "услуг",
        "услуги",
        "услуга",
        "дата",
        "время",
        "подпись",
        "руб",
        "рублей",
        "ндс",
        "оплата",
        "оплате",
        "налог",
        "налога",
        "профессиональный",
        "доход",
        "дохода",
        "нпд",
        "канал",
        "телеграм",
        "телеграмм",
        "telegram",
        "тг",
        # month names (the sheet appends them to the counterparty)
        "январь",
        "января",
        "февраль",
        "февраля",
        "март",
        "марта",
        "апрель",
        "апреля",
        "май",
        "мая",
        "июнь",
        "июня",
        "июль",
        "июля",
        "август",
        "августа",
        "сентябрь",
        "сентября",
        "октябрь",
        "октября",
        "ноябрь",
        "ноября",
        "декабрь",
        "декабря",
    }
)

# Russian case endings, longest first. Stripped only while at least four
# characters remain, so "Дорофеевой"/"Дорофеева" collapse to "дорофеев" but
# short names ("Илья") stay intact and are handled by the edit distance.
_CASE_SUFFIXES = (
    "ами",
    "ями",
    "ого",
    "его",
    "ому",
    "ему",
    "ыми",
    "ими",
    "ой",
    "ей",
    "ая",
    "яя",
    "ую",
    "юю",
    "ым",
    "им",
    "ом",
    "ем",
    "ах",
    "ях",
    "ии",
    "ия",
    "а",
    "я",
    "у",
    "ю",
    "е",
    "и",
    "ы",
    "й",
    "ь",
    "о",
)


@dataclass(frozen=True)
class ParsedName:
    """A name split into full tokens and single-letter initials."""

    words: tuple[str, ...]
    initials: tuple[str, ...]

    @property
    def is_usable(self) -> bool:
        # Initials alone carry too little identity to decide anything.
        return bool(self.words)


def normalize_name(value: str | None) -> str:
    """Casefold, fold ё -> е and collapse whitespace."""
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", text).strip()


def is_noise_word(value: str) -> bool:
    """True for words that never identify a person (labels, legal forms, months)."""
    token = re.sub(r"[^а-яa-z]", "", normalize_name(value))
    return not token or token in NOISE_WORDS


def parse_name(value: str | None) -> ParsedName:
    normalized = re.sub(r"\([^)]*\)", " ", normalize_name(value))
    words: list[str] = []
    initials: list[str] = []
    for raw in re.findall(r"[а-яa-z0-9]+", normalized):
        token = _repair_homoglyphs(raw)
        if any(char.isdigit() for char in token) or token in NOISE_WORDS:
            continue
        if len(token) == 1:
            initials.append(token)
        else:
            words.append(token)
    return ParsedName(tuple(words), tuple(initials))


def names_match(left: str | None, right: str | None) -> bool | None:
    """Whether two names denote the same person; None when undecidable."""
    parsed_left = parse_name(left)
    parsed_right = parse_name(right)
    if not parsed_left.is_usable or not parsed_right.is_usable:
        return None
    return _covers(parsed_left, parsed_right) or _covers(parsed_right, parsed_left)


def name_contains(short_name: str | None, full_name: str | None) -> bool | None:
    """Whether every meaningful token of `short_name` occurs in `full_name`."""
    parsed_short = parse_name(short_name)
    parsed_full = parse_name(full_name)
    if not parsed_short.is_usable or not parsed_full.is_usable:
        return None
    return _covers(parsed_short, parsed_full)


def name_key(value: str | None) -> str:
    """Stable comparable form of a name — handy for logs and dedupe."""
    parsed = parse_name(value)
    return " ".join(sorted(_stem(word) for word in parsed.words))


def _repair_homoglyphs(token: str) -> str:
    has_cyrillic = any("а" <= char <= "я" for char in token)
    has_latin = any("a" <= char <= "z" or char.isdigit() for char in token)
    return token.translate(_HOMOGLYPHS) if has_cyrillic and has_latin else token


def _covers(needle: ParsedName, haystack: ParsedName) -> bool:
    needle_units = list(needle.words) + list(needle.initials)
    haystack_units = list(haystack.words) + list(haystack.initials)
    assignment = _assign(needle_units, haystack_units)
    if assignment is None:
        return False
    # An initial-only overlap ("Д." against "Дорофеева") proves nothing: require
    # at least one full token matched against a full token.
    return any(
        len(needle_units[needle_index]) > 1 and len(haystack_units[haystack_index]) > 1
        for haystack_index, needle_index in assignment.items()
    )


def _assign(needles: list[str], candidates: list[str]) -> dict[int, int] | None:
    """Match every needle to a distinct candidate (Kuhn's algorithm)."""

    matched: dict[int, int] = {}

    def augment(needle_index: int, seen: set[int]) -> bool:
        for candidate_index, candidate in enumerate(candidates):
            if candidate_index in seen:
                continue
            if not _units_match(needles[needle_index], candidate):
                continue
            seen.add(candidate_index)
            taken = matched.get(candidate_index)
            if taken is None or augment(taken, seen):
                matched[candidate_index] = needle_index
                return True
        return False

    for index in range(len(needles)):
        if not augment(index, set()):
            return None
    return matched


def _units_match(left: str, right: str) -> bool:
    left, right = _align_alphabets(left, right)
    if len(left) == 1 or len(right) == 1:
        return left[0] == right[0]
    return _tokens_match(left, right)


def _align_alphabets(left: str, right: str) -> tuple[str, str]:
    """Read a whole-Latin token back as Cyrillic when the other side is Cyrillic.

    A PDF font without a Unicode map renders "АКАЕВА ЕВА" as "AKAEBA EBA": every
    letter is a Latin look-alike, so the per-token repair (which needs both
    alphabets inside one word) never fires. Comparing against a Cyrillic name is
    what reveals the substitution.
    """
    if _is_latin(left) and _is_cyrillic(right):
        return left.translate(_HOMOGLYPHS), right
    if _is_cyrillic(left) and _is_latin(right):
        return left, right.translate(_HOMOGLYPHS)
    return left, right


def _is_latin(token: str) -> bool:
    return all("a" <= char <= "z" for char in token)


def _is_cyrillic(token: str) -> bool:
    return all("а" <= char <= "я" for char in token)


def _tokens_match(left: str, right: str) -> bool:
    left_stem = _stem(left)
    right_stem = _stem(right)
    if left_stem == right_stem:
        return True
    shortest = min(len(left_stem), len(right_stem))
    limit = 0 if shortest < 4 else 1 if shortest < 7 else 2
    if limit == 0:
        return False
    return _distance(left_stem, right_stem, limit) <= limit


def _stem(token: str) -> str:
    for suffix in _CASE_SUFFIXES:
        if len(token) - len(suffix) >= 4 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token


def _distance(left: str, right: str, limit: int) -> int:
    if abs(len(left) - len(right)) > limit:
        return limit + 1
    previous = list(range(len(right) + 1))
    for row, left_char in enumerate(left, start=1):
        current = [row]
        for column, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[column] + 1,
                    current[column - 1] + 1,
                    previous[column - 1] + (left_char != right_char),
                )
            )
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]
