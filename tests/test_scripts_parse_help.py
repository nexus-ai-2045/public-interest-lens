"""scripts/ の入口は、引数を読む前に処理を走らせない（--help で本番の処理が走る事故を止める lint）。

--help を解釈しない入口に --help を渡すと、本番の処理が走って生成物を書き換える
（#217 で一覧に固定、#234 で main の CI が赤、2026-11-20 に台帳が作り直された）。
構文木で次を見る。どれかに当たる入口は落とす（例外の一覧は置かない）。
- `if __name__ == "__main__":` の中で、argparse で引数を読む（または --help を自分で比べる）より先に、ほかの処理がある。
  main() などを呼ぶときは、その関数の頭で引数を読むこと。読む前に許すのは、import・定数・パーサーの組み立てだけ。
- モジュールの読み込みのときに関数を呼ぶ・ループを回す（sys.path と warnings・csv の設定は除く）。
新しい入口は `python3 -m scripts.new_script 名前 "説明"` で雛形から作る（雛形はこの lint を通る）。
`python -m scripts.X --help` は scripts/__init__.py の守りが、入口の書き方に関係なく止める。
"""
import ast
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"

PARSE = {"parse_args", "parse_known_args", "parse_intermixed_args"}
SETUP = {"add_argument", "add_argument_group", "add_mutually_exclusive_group", "add_subparsers", "add_parser", "set_defaults", "error"}

def is_main_guard(n):
    if not isinstance(n, ast.If): return False
    s = ast.unparse(n.test).replace("'", '"').replace(" ", "")
    return s in ('__name__=="__main__"', '"__main__"==__name__')

def calls(node):
    return [c for c in ast.walk(node) if isinstance(c, ast.Call)]

def meth(c):
    return c.func.attr if isinstance(c.func, ast.Attribute) else (c.func.id if isinstance(c.func, ast.Name) else None)

def parses(stmt):
    return any(meth(c) in PARSE for c in calls(stmt))

def mentions_help(stmt):
    return any(isinstance(c, ast.Constant) and c.value in ("-h", "--help") for c in ast.walk(stmt))

def setup_only(stmt):
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant): return True  # docstring
    if isinstance(stmt, (ast.Import, ast.ImportFrom)): return True
    if isinstance(stmt, ast.For): return all(setup_only(s) for s in stmt.body)
    cs = calls(stmt)
    if not cs: return isinstance(stmt, (ast.Assign, ast.AnnAssign))  # 定数
    return all(meth(c) in SETUP | {"ArgumentParser", "dict", "Path", "str", "int", "float", "list", "tuple", "set", "frozenset", "join", "sorted", "splitlines", "strip", "format", "split", "keys", "values", "items", "today", "isoformat", "get", "getenv", "resolve", "signal", "cpu_count", "now", "astimezone", "date"} for c in cs)

def body_parses_first(body, funcs, depth=0):
    for st in body:
        if parses(st) or (isinstance(st, ast.If) and mentions_help(st.test)):
            return True
        # main(...) / sys.exit(main()) / raise SystemExit(main())
        for c in calls(st):
            n = meth(c)
            if n in funcs and depth < 2 and body_parses_first(funcs[n].body, funcs, depth + 1):
                return True
        if not setup_only(st):
            return False
    return False

def problems(text: str) -> list[str] | None:
    """入口でなければ None、入口なら当たった箇所の一覧。"""
    tree = ast.parse(text)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    guards = [n for n in tree.body if is_main_guard(n)]
    if not guards: return None
    bad = []
    for n in tree.body:
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            s = ast.unparse(n.value.func)
            if not s.startswith("sys.path.") and not s.startswith(("warnings.", "csv.field_size_limit")):
                bad.append(f"{n.lineno}: 読み込みのときに呼ぶ {s}()")
        if isinstance(n, (ast.For, ast.While, ast.With)):
            bad.append(f"{n.lineno}: 読み込みのときに回す {type(n).__name__}")
    if not body_parses_first(guards[0].body, funcs):
        bad.append(f"{guards[0].lineno}: 引数を読む前に処理が走る")
    return bad



def ignores_help(text: str) -> bool:
    return bool(problems(text))


PAST_MISTAKE = '''"""閣僚名簿を作る。"""
import csv


def main():
    with open("out.csv", "w") as f:
        csv.writer(f).writerow(["x"])


if __name__ == '__main__':
    main()
'''


class ParseHelpLintTest(unittest.TestCase):
    def test_every_entrypoint_reads_args_first(self):
        bad = {p.name: r for p in sorted(SCRIPTS.glob("*.py")) if (r := problems(p.read_text(encoding="utf-8")))}
        self.assertEqual(bad, {}, "引数を読む前に処理が走る入口がある。python3 -m scripts.new_script で作った雛形の形にする")

    def test_past_mistake_fails(self):
        # #234 の直前の parse_cabinet.py と同じ形（argparse なしで main() が書き込む）
        self.assertTrue(problems(PAST_MISTAKE))
        # argparse はあるが、読む前に書き込む形も落ちる
        late = PAST_MISTAKE.replace("def main():\n", "def main():\n    import argparse\n").replace(
            'csv.writer(f).writerow(["x"])', 'csv.writer(f).writerow(["x"])\n    argparse.ArgumentParser().parse_args()')
        self.assertTrue(problems(late))
        self.assertTrue(problems("print(1)\nif __name__ == '__main__':\n    import argparse\n    argparse.ArgumentParser().parse_args()\n"))

    def test_reading_args_first_passes(self):
        ok = 'if __name__ == "__main__":\n    import argparse\n    argparse.ArgumentParser(description=__doc__).parse_args()\n    main()\n'
        self.assertEqual(problems(ok), [])
        self.assertIsNone(problems("# python -m は入口を __main__ としても読む\n"))


if __name__ == "__main__":
    unittest.main()
