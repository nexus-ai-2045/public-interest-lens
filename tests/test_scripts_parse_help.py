"""scripts/ の入口はすべて --help を解釈する。

--help を解釈しない入口に --help を渡すと、本番の処理が走って生成物を書き換える（進め方 3章の事前チェック）。
2026-11-19 に 57 本あった例外は 2026-11-20 に全部直した（例外の一覧は置かない）。
入口を足すときは、`if __name__ == "__main__":` の直後で argparse を通す。
自前の引数を sys.argv で読む入口は parse_known_args() にする（例：scripts/strip_commit_trace.py）。
"""
import re
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
ENTRY = re.compile(r"^if __name__ == ['\"]__main__['\"]:", re.M)


def ignores_help(text: str) -> bool:
    """直接実行の入口なのに、argparse も --help の自前の扱いも無い。"""
    if not ENTRY.search(text):
        return False
    return "ArgumentParser" not in text and '"--help"' not in text and "'--help'" not in text


class ParseHelpTest(unittest.TestCase):
    def test_every_entrypoint_parses_help(self):
        bad = sorted(p.name for p in SCRIPTS.glob("*.py") if ignores_help(p.read_text(encoding="utf-8")))
        self.assertEqual(
            bad,
            [],
            "--help を解釈しない入口がある。`if __name__ == \"__main__\":` の直後に "
            "argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args() を置く"
            "（sys.argv を自分で読む入口は parse_known_args()）",
        )

    def test_detects_entry_without_parser(self):
        self.assertTrue(ignores_help('"""x"""\ndef main():\n    pass\n\n\nif __name__ == "__main__":\n    main()\n'))
        self.assertFalse(ignores_help("# python -m は入口を __main__ としても読む\n"))


if __name__ == "__main__":
    unittest.main()
