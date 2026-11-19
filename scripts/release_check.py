#!/usr/bin/env python3
"""リリース前の総点検（L4）。既存の検査を決まった順で回し、1つの結果にまとめる。

本番への配信はしない。配信の手順は docs/operations.md の「リリース」を正本とする。
順番：ループの点検 → 事前チェック（スモーク・E2E つき）→ CI と同じ検査（ローカル）→ ロジック検査
      → 設計の整合と完了の条件1〜3 → バックテストの判定 → 議員ページ（曝露ランキング）の検査。
結果は3つに分ける。合格・注意・失敗。
  注意：検査は通ったが、確かめる対象が無い（空振り）・件数が足りず判定できない・まだ測っていない。合格と混ぜない。
  失敗：1つでもあればリリースしない（終了コード1）。注意だけなら終了コード0だが、最後の行に注意の件数を出す。
結果は .local/release-check/<日付>.json に残る（step・ok・status・detail。ok は合格のときだけ真）。

使い方：python3 scripts/release_check.py [--offline] [--skip-verify]
  --offline：preflight の通信先確認を飛ばす。 --skip-verify：local_verify を飛ばす（直前に回したときだけ）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".local" / "release-check"
PASS, WARN, FAIL = "合格", "注意", "失敗"


def plan(offline: bool, skip_verify: bool) -> list[tuple[str, list[str]]]:
    """終了コードだけで合否が決まる手順。"""
    py = sys.executable
    steps = [
        ("ループの点検", [py, "scripts/loop_status.py"]),
        ("事前チェック（スモーク・E2E）", [py, "scripts/preflight.py", "--smoke"] + (["--offline"] if offline else [])),
    ]
    if not skip_verify:
        steps.append(("CI と同じ検査", [py, "scripts/local_verify.py"]))
    steps.append(("ロジック検査（tests/test_evaluation_logic.py）", [py, "-m", "unittest", "tests.test_evaluation_logic"]))
    return steps


def _json_from(cmd: list[str]) -> dict:
    """読むだけのスクリプトを --json で回して結果を受け取る。終了コードは見ない（中身で判定する）。
    JSON が読めないときは、原因が分かるように終了コードと標準エラーの末尾を付けて ValueError にする。"""
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False)
    try:
        return json.loads(proc.stdout)
    except ValueError as error:
        raise ValueError(f"終了コード {proc.returncode}：{proc.stderr.strip()[-200:]}") from error


def design_steps(report: dict) -> list[dict]:
    """scripts/check_design_consistency.py の結果 → 設計の整合と、完了の条件1〜3（4は総点検そのものなので入れない）。"""
    steps = [{"step": "設計の整合（定数・撤回した方式）", "status": PASS if report["ok"] else FAIL,
              "detail": "" if report["ok"] else "；".join(report.get("reasons", []))[:300]}]
    # 測れていない・一部しか測れていない条件は注意。測って届いていない条件は失敗。
    status_of = {"達成": PASS, "未達": FAIL}
    for row in report["completion"]:
        if row["no"] == 4:
            continue
        steps.append({"step": f"完了の条件{row['no']}：{row['name']}", "status": status_of.get(row["state"], WARN),
                      "detail": f"{row['state']}。{row['now']}"})
    return steps


def backtest_step(result: dict) -> dict:
    """バックテストの本命2つ（指標をそろえた M0・外国の研究から当てる T0）の判定。件数不足の「判定不能」は合格にしない。"""
    verdicts = {"M0": result["headline_aligned"]["verdict"], "T0": result["transplant"]["headline"]["verdict"]}
    status = FAIL if "未達" in verdicts.values() else (PASS if set(verdicts.values()) == {"達成"} else WARN)
    return {"step": "バックテストの判定", "status": status,
            "detail": "、".join(f"{k} {v}" for k, v in verdicts.items()) + f"（合格の線 {result['target'] * 100:.0f}%、判定に要る件数 {result['min_n']}）"}


def members_step(root: Path = ROOT) -> dict:
    """議員ページ＝曝露ランキングの検査。人物台帳（persons.csv）の全員が、曝露ランキングに「点あり」か「点なし＋理由」で1回ずつ載っているか。
    曝露ランキングの出力か台帳が無い・台帳が0人なら、確かめる対象が無いので未測定（注意）。全員そろわなければ失敗。0件を合格にしない。"""
    from scripts import check_design_consistency as design

    name = "議員ページ（曝露ランキング）の検査"
    d = root / "data" / "derived"
    exposure, persons = root / design.EXPOSURE, d / "person-ids" / "persons.csv"
    if not exposure.is_file():
        return {"step": name, "status": WARN, "detail": f"{design.EXPOSURE} がまだ無い（未測定）。python3 scripts/generate_artifacts.py で作る"}
    if not persons.is_file() or not any((r.get("人物ID") or "").strip() for r in design.read_csv(persons)):
        return {"step": name, "status": WARN, "detail": "人物台帳（persons.csv）が無いか0人で、照らす対象が無い（未測定）"}
    ok, detail = design._members_on_ledger(root, d)
    return {"step": name, "status": PASS if ok else FAIL, "detail": detail[:300]}


def measured_steps() -> list[dict]:
    """中身を読んで合格・注意・失敗を決める手順。読めないときは失敗にする（測れないものを合格にしない）。"""
    py = sys.executable
    steps: list[dict] = []
    for name, build in (
        ("設計の整合と完了の条件", lambda: design_steps(_json_from([py, "scripts/check_design_consistency.py", "--json"]))),
        ("バックテストの判定", lambda: [backtest_step(_json_from([py, "scripts/backtest.py", "--json"]))]),
        ("議員ページ（曝露ランキング）の検査", lambda: [members_step()]),
    ):
        try:
            steps += build()
        except Exception as error:  # noqa: BLE001 形の違う JSON なども含め、読めなければ失敗にして記録は必ず残す
            steps.append({"step": name, "status": FAIL, "detail": f"結果を読めない（{type(error).__name__}: {error}）"[:300]})
    return steps


def summary_line(results: list[dict]) -> str:
    bad = [r["step"] for r in results if r["status"] == FAIL]
    warn = [r["step"] for r in results if r["status"] == WARN]
    note = f"。注意 {len(warn)} 件（{'、'.join(warn)}）は合格ではない" if warn else ""
    if bad:
        return "リリース前の総点検：失敗あり、配信しない（" + "、".join(bad) + "）" + note
    return "リリース前の総点検：失敗なし" + (note + "。中身を確かめてから配信を決める" if warn else "。すべて合格。配信してよい")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args(argv)
    results: list[dict] = []
    for name, cmd in plan(args.offline, args.skip_verify):
        ok = subprocess.run(cmd, cwd=ROOT, check=False).returncode == 0
        results.append({"step": name, "status": PASS if ok else FAIL, "detail": ""})
        print(f"{PASS if ok else FAIL}  {name}", flush=True)
    for step in measured_steps():
        results.append(step)
        print(f"{step['status']}  {step['step']}" + (f"：{step['detail']}" if step["detail"] else ""), flush=True)
    for r in results:
        # 記録を読む側（scripts/check_design_consistency.py）は step・ok・status を見る。注意は合格ではないので ok に入れない。
        r["ok"] = r["status"] == PASS
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{date.today().isoformat()}.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(summary_line(results))
    return 1 if any(r["status"] == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
