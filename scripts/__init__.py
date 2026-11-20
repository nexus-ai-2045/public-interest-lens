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
    # `-m scripts.X` と、間を空けない `-mscripts.X` の両方
    at = next((i for i, a in enumerate(orig) if a.startswith("-m")), None)
    if at is None:
        return
    name = orig[at][2:] or (orig[at + 1] if at + 1 < len(orig) else "")
    if not name.startswith(__name__ + "."):
        return
    parts = name.split(".")[1:]
    path = Path(__file__).parent.joinpath(*parts[:-1], parts[-1] + ".py")
    if not path.is_file():
        return
    tree = ast.parse(path.read_text(encoding="utf-8"))
    # 文字列や注釈に書いてあるだけでなく、実際に ArgumentParser を呼んでいる入口だけ、その入口の説明に任せる
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if (f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)) == "ArgumentParser":
                return
    print(ast.get_docstring(tree) or f"{name}：説明はありません")
    raise SystemExit(0)


_help_guard()
