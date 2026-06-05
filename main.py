from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable, cast


def _ensure_src_on_path() -> None:
    src_path = Path(__file__).resolve().parent / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))


def main() -> int:
    _ensure_src_on_path()

    cli = importlib.import_module("ozon_ord_sync.cli")
    cli_main = cast(Callable[[], int], cli.main)
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
