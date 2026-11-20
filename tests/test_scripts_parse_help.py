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
# 受け手に関係なく副作用の無い呼び出し（名前だけで見てよいもの）
PURE = SETUP | {"ArgumentParser", "dict", "Path", "str", "int", "float", "list", "tuple", "set", "frozenset", "sorted",
                "splitlines", "strip", "format", "split", "keys", "values", "items", "isoformat", "resolve", "astimezone", "date",
                "range", "Counter", "defaultdict", "OrderedDict", "namedtuple", "replace", "encode", "hexdigest", "lower", "upper"}
# 名前だけでは決められないもの（get・join・now など）は、受け手まで含めた名前で許す
PURE_DOTTED = {"os.environ.get", "os.getenv", "signal.signal", "os.cpu_count", "os.path.join", "os.path.dirname",
               "datetime.now", "datetime.datetime.now", "date.today", "datetime.date.today", "datetime.date",
               "re.compile", "Path.home", "Path.cwd", "timezone", "timedelta", "datetime.timezone", "datetime.timedelta",
               "ZoneInfo", "threading.Lock", "time.strftime", "dt.date", "urlsplit", "re.escape", "re.sub", "str.maketrans",
               "hashlib.sha256", "unicodedata.normalize", "urllib.request.build_opener", "build_opener"}
# モジュールの読み込みのときに呼んでよいもの（環境の設定だけ）
MODULE_SETUP = ("sys.path.", "warnings.", "csv.field_size_limit")
EXITS = (ast.Return, ast.Raise)

def is_main_guard(n):
    if not isinstance(n, ast.If): return False
    s = ast.unparse(n.test).replace("'", '"').replace(" ", "")
    return s in ('__name__=="__main__"', '"__main__"==__name__')

def calls(node):
    return [c for c in ast.walk(node) if isinstance(c, ast.Call)]

def meth(c):
    return c.func.attr if isinstance(c.func, ast.Attribute) else (c.func.id if isinstance(c.func, ast.Name) else None)

LOCAL: dict[str, ast.AST] = {}  # 調べている入口のモジュールで定義した関数・クラス（problems が詰める）

def local_pure(name, seen=()):
    """同じモジュールで定義したクラスか、副作用の無い呼び出しだけをする関数か。"""
    node = LOCAL.get(name)
    if isinstance(node, ast.ClassDef): return True
    if node is None or name in seen or len(seen) > 2: return False
    return all(pure(c, seen + (name,)) for st in node.body for c in calls(st))

def pure(c, seen=()):
    name = ast.unparse(c.func)
    if meth(c) in PURE or name in PURE_DOTTED: return True
    if isinstance(c.func, ast.Name) and local_pure(c.func.id, seen): return True
    # "区切り".join(...) のように、文字列の定数を受け手にする join
    return meth(c) == "join" and isinstance(c.func, ast.Attribute) and isinstance(c.func.value, ast.Constant)

def parses(stmt):
    """枝の外で、必ず引数を読む文か（if の中で読むだけのものは数えない）。"""
    if not isinstance(stmt, (ast.Expr, ast.Assign, ast.AnnAssign, ast.Return)): return False
    return any(meth(c) in PARSE for c in calls(stmt))

def mentions_help(stmt):
    return any(isinstance(c, ast.Constant) and c.value in ("-h", "--help") for c in ast.walk(stmt))

def ends_in_exit(body):
    last = body[-1] if body else None
    if isinstance(last, EXITS): return True
    return isinstance(last, ast.Expr) and isinstance(last.value, ast.Call) and ast.unparse(last.value.func) in ("sys.exit", "exit", "SystemExit")

def handles_help(stmt):
    """--help を自分で比べて、その枝で必ず抜ける if か。"""
    return isinstance(stmt, ast.If) and mentions_help(stmt.test) and ends_in_exit(stmt.body)

def setup_only(stmt):
    if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant): return True  # docstring
    if isinstance(stmt, (ast.Import, ast.ImportFrom)): return True
    if isinstance(stmt, ast.For): return all(setup_only(s) for s in stmt.body)
    cs = calls(stmt)
    if not cs: return isinstance(stmt, (ast.Assign, ast.AnnAssign))  # 定数
    return all(pure(c) for c in cs)

def body_parses_first(body, funcs, depth=0):
    for st in body:
        if parses(st) or handles_help(st):
            return True
        # main(...) / sys.exit(main()) / raise SystemExit(main())：枝の外で呼ぶ関数の頭だけ見る
        if isinstance(st, (ast.Expr, ast.Assign, ast.Return, ast.Raise)):
            for c in calls(st):
                n = meth(c)
                if n in funcs and depth < 2 and body_parses_first(funcs[n].body, funcs, depth + 1):
                    return True
        if not setup_only(st):
            return False
    return False

def module_problems(body, bad):
    for n in body:
        if is_main_guard(n) or isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            continue
        if isinstance(n, (ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)):
            bad.append(f"{n.lineno}: 読み込みのときに回す {type(n).__name__}")
            continue
        if isinstance(n, ast.Try):
            module_problems(n.body + n.orelse + n.finalbody + [s for h in n.handlers for s in h.body], bad)
            continue
        if isinstance(n, ast.If):
            module_problems(n.body + n.orelse, bad)
            targets = [n.test]
        else:
            targets = [n]
        for c in (c for t in targets for c in calls(t)):
            s = ast.unparse(c.func)
            if not s.startswith(MODULE_SETUP) and not pure(c):
                bad.append(f"{n.lineno}: 読み込みのときに呼ぶ {s}()")

def problems(text: str) -> list[str] | None:
    """入口でなければ None、入口なら当たった箇所の一覧。"""
    tree = ast.parse(text)
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    LOCAL.clear()
    LOCAL.update({n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))})
    guards = [n for n in tree.body if is_main_guard(n)]
    if not guards: return None
    bad = []
    module_problems(tree.body, bad)
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
        bad = {str(p.relative_to(SCRIPTS)): r for p in sorted(p for p in SCRIPTS.rglob("*.py") if "__pycache__" not in p.parts and not any(x.startswith("_probe_") for x in p.parts)) if (r := problems(p.read_text(encoding="utf-8")))}
        self.assertEqual(bad, {}, "引数を読む前に処理が走る入口がある。python3 -m scripts.new_script で作った雛形の形にする")

    def test_past_mistake_fails(self):
        # #234 の直前の parse_cabinet.py と同じ形（argparse なしで main() が書き込む）
        self.assertTrue(problems(PAST_MISTAKE))
        # argparse はあるが、読む前に書き込む形も落ちる
        late = PAST_MISTAKE.replace("def main():\n", "def main():\n    import argparse\n").replace(
            'csv.writer(f).writerow(["x"])', 'csv.writer(f).writerow(["x"])\n    argparse.ArgumentParser().parse_args()')
        self.assertTrue(problems(late))
        self.assertTrue(problems("print(1)\nif __name__ == '__main__':\n    import argparse\n    argparse.ArgumentParser().parse_args()\n"))

    def test_known_bypasses_fail(self):
        # 2026-11-20 の /code-review で見つかった抜け道。どれも --help で書き込みや通信が走る
        guard = 'if __name__ == "__main__":\n'
        cases = {
            "枝の中でだけ読む": guard + '    if len(sys.argv) > 5:\n        argparse.ArgumentParser().parse_args()\n    open("x", "w").write("y")\n',
            "抜けない --help の枝": guard + '    if sys.argv[1:] == ["--help"]:\n        pass\n    open("x", "w").write("y")\n',
            "受け手を見ない get": guard + '    requests.get("http://x")\n    argparse.ArgumentParser().parse_args()\n',
            "代入の中の呼び出し": 'R = subprocess.run(["rm", "x"])\n' + guard + '    argparse.ArgumentParser().parse_args()\n',
            "try の中の呼び出し": 'try:\n    open("x", "w").write("y")\nexcept Exception:\n    pass\n' + guard + '    argparse.ArgumentParser().parse_args()\n',
            "if の中の呼び出し": 'if True:\n    open("x", "w").write("y")\n' + guard + '    argparse.ArgumentParser().parse_args()\n',
            "副作用のある自前の関数": 'def f():\n    open("x", "w").write("y")\n\nX = f()\n' + guard + '    argparse.ArgumentParser().parse_args()\n',
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertTrue(problems(text), name)

    def test_help_branch_that_exits_passes(self):
        ok = 'if __name__ == "__main__":\n    if "--help" in sys.argv:\n        print(__doc__)\n        sys.exit(0)\n    main()\n'
        self.assertEqual(problems(ok), [])

    def test_reading_args_first_passes(self):
        ok = 'if __name__ == "__main__":\n    import argparse\n    argparse.ArgumentParser(description=__doc__).parse_args()\n    main()\n'
        self.assertEqual(problems(ok), [])
        self.assertIsNone(problems("# python -m は入口を __main__ としても読む\n"))


if __name__ == "__main__":
    unittest.main()
