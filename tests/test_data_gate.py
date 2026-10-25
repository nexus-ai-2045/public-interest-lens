import importlib
import os
import unittest

import _data_gate

# 後の段に回してよいテストの上限（ラチェット）。減らすのはよいが、増やすときは人の判断が要る。
MAX_ENTRIES = 33


class DataGateTest(unittest.TestCase):
    def test_allowlist_does_not_grow(self):
        self.assertLessEqual(len(_data_gate.load_allowlist()), MAX_ENTRIES)

    def test_every_listed_test_is_marked(self):
        allowed = _data_gate.load_allowlist()
        for module in sorted({test_id.split(".")[0] for test_id in allowed}):
            importlib.import_module(module)
        self.assertEqual(sorted(allowed), sorted(_data_gate.REGISTERED))

    def test_unlisted_test_cannot_be_skipped(self):
        def test_not_listed(self):
            pass

        with self.assertRaises(RuntimeError):
            _data_gate.requires_data("speeches")(test_not_listed)

    def test_required_mode_never_skips(self):
        if os.environ.get("PIL_REQUIRE_DATA") == "1":
            for key, path in _data_gate.DATA.items():
                self.assertTrue(path.exists(), key)


if __name__ == "__main__":
    unittest.main()
