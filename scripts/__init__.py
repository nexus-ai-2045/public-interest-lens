"""公益レンズのローカル運用スクリプト。

`python -m scripts.X --help` の守り：パッケージの読み込みは入口のモジュールより先に走るので、
入口が argparse を持たないときは、モジュールを実行せずに docstring を出して終える。
--help を渡して本番の処理が走る事故（#217・#234・2026-11-20 の台帳の作り直し）を、
入口の書き方に頼らずに止める。argparse を持つ入口は、その入口の詳しい説明に任せる。
新しい入口は `python3 -m scripts.new_script 名前 "説明"` で雛形から作る。
"""

import sys as _sys


def _help_guard() -> None:
    import ast
    from pathlib import Path

    if _sys.argv[:1] != ["-m"] or not {"-h", "--help"} & set(_sys.argv[1:]):
        return
    orig = getattr(_sys, "orig_argv", [])
    if "-m" not in orig[:-1]:
        return
    name = orig[orig.index("-m") + 1]
    if not name.startswith(__name__ + "."):
        return
    parts = name.split(".")[1:]
    path = Path(__file__).parent.joinpath(*parts[:-1], parts[-1] + ".py")
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8")
    if "ArgumentParser" in text:
        return
    print(ast.get_docstring(ast.parse(text)) or f"{name}：説明はありません")
    raise SystemExit(0)


_help_guard()
