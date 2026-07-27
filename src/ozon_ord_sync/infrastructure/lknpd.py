"""ЛК НПД lookups for self-employed receipts.

OCR cannot tell 6 from b or 1 from l inside a random receipt id, and both
readings look equally valid — a wrong number then goes straight into ORD. The
public print endpoint settles it: an existing receipt answers 200, a wrong id
answers 422.
"""

from __future__ import annotations

import urllib.error
import urllib.request

RECEIPT_PRINT_URL = "https://lknpd.nalog.ru/api/v1/receipt/{inn}/{receipt_id}/print"
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
_MISSING_STATUSES = frozenset({400, 404, 422})


def receipt_exists(inn: str, receipt_id: str, timeout: int = 20) -> bool | None:
    """True/False when ЛК НПД answered, None when it could not be reached."""
    request = urllib.request.Request(
        RECEIPT_PRINT_URL.format(inn=inn, receipt_id=receipt_id),
        headers={"User-Agent": _USER_AGENT},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except urllib.error.HTTPError as error:
        return False if error.code in _MISSING_STATUSES else None
    except Exception:
        return None
