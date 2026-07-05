from __future__ import annotations

import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ozon_ord_sync.config.runtime_auth import save_ozon_cookie


class RuntimeAuthTest(unittest.TestCase):
    def test_saved_cookie_file_is_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ozon-cookie.json"

            save_ozon_cookie("a=b", "https://ord.ozon.ru", path=path)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
