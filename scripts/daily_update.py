"""毎日の自動更新：取得 → 振り分けの確認 → 再計算 → 公開ランキング → 出典チェック → 検査 → 片付け。

定期実行（Claude の定期ルーチン）から `python3 scripts/daily_update.py --all` で呼ぶ。手元でも同じ入口で動く。
各段階は独立に落ちてよく、落ちた段階と理由を報告に残して次へ進む（ただし再計算が落ちたら公開ランキングは作らない）。

- 取得：一次資料のサイトに届くときだけ取る。届かなければ「届かない」と記録して飛ばす（0や空で埋めない）。
  Mac で取った原本と表は `--incoming <フォルダ>` で渡す（中身は data/acquired/<task-id>/ と同じ形）。
- 振り分け：成立法のうち、AI の振り分け（2系統）がまだ無い法律を一覧にする。定期ルーチンの Claude が2系統で付ける。
- 再計算：app/scripts の判定ルール（triage v2 → 影響 → 損失 → 便益と公開判定）を順に回す。
- 公開ランキング：公開可の法律は全件公開（2026-10-17 の常時承認）。出典チェックの不一致は外す。
- 片付け：main に取り込み済みで2日以上動きのない claude/ と report/ のリモートブランチと、古い作業ファイルを消す。
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import socket
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ACQUIRED = ROOT / "data" / "acquired"
DERIVED = ROOT / "data" / "derived"
WORK = ROOT / ".local" / "daily-update"
CENSUS_KEY = ("種別", "提出回次", "番号")
# 取得先ごとに、届くかを先に確かめるホスト。
HOSTS = {
    "bill-census": "www.shugiin.go.jp",
    "enforcement-dates": "laws.e-gov.go.jp",
    "oecd-industry": "sdmx.oecd.org",
    "intl-stats": "api.worldbank.org",
    "diet-minutes": "kokkai.ndl.go.jp",
}
PIPELINE = [
    ["node", "scripts/run-triage-v2-line1.mjs"],
    ["node", "scripts/run-impact-v1.mjs", "--triage", "v2"],
    ["node", "scripts/run-loss-v1.mjs", "--triage", "v2"],
    ["node", "scripts/run-benefit-v1.mjs", "--triage", "v2"],
]
STALE_DAYS = 2
KEEP_WORK_DAYS = 14


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write(path: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)


def reachable(host: str, timeout: float = 8.0) -> bool:
    """HTTPS で届くか。プロキシ経由の環境では CONNECT を試す。"""
    import os
    import urllib.request

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        try:
            socket.create_connection((host, 443), timeout=timeout).close()
            return True
        except OSError:
            return False
    try:
        urllib.request.urlopen(f"https://{host}/", timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True  # 届いたうえでのエラー（404 など）は「届く」
    except Exception:
        return False


def merge_rows(old: list[dict[str, str]], new: list[dict[str, str]], key: tuple[str, ...]) -> tuple[list[dict[str, str]], int, int]:
    """キーが同じ行は新しい値で置き換え、新しいキーは末尾に足す。消えた行は消さない（取得の失敗で台帳が減らないように）。"""
    index = {tuple(row[k] for k in key): i for i, row in enumerate(old)}
    merged = list(old)
    added = updated = 0
    for row in new:
        k = tuple(row[c] for c in key)
        if k in index:
            if merged[index[k]] != row:
                merged[index[k]] = row
                updated += 1
        else:
            index[k] = len(merged)
            merged.append(row)
            added += 1
    return merged, added, updated


def latest_session(enacted: Path = ACQUIRED / "bill-census-full" / "enacted.csv") -> int:
    return max(int(row["回次"]) for row in _read(enacted))


def unlabeled_laws(acquired: Path = ACQUIRED, derived: Path = DERIVED) -> list[dict[str, str]]:
    """成立法のうち、振り分け（系統1・系統2を並べた triage.csv）が無い法律。"""
    labeled = {row["id"] for row in _read(derived / "bill-triage-v1" / "triage.csv")}
    out = []
    for row in _read(acquired / "bill-census-full" / "enacted.csv"):
        law_id = f"{row['種別']}-{row['提出回次']}-{row['番号']}"
        if law_id not in labeled:
            out.append({"id": law_id, "題名": row["題名"], "回次": row["回次"], "経過URL": row.get("経過URL", "")})
    return out


def standing_approvals(publish: Path = DERIVED / "publish-v1-triage-v2" / "publish.csv") -> list[str]:
    """公開可の法律は全件公開する（ユーザーの常時承認、2026-10-17）。"""
    return sorted(row["id"] for row in _read(publish) if row["公開可否"] == "公開可")


class Run:
    def __init__(self) -> None:
        self.steps: list[dict] = []

    def record(self, step: str, status: str, detail: str = "") -> None:
        self.steps.append({"step": step, "status": status, "detail": detail})
        print(f"[{status}] {step} {detail}", flush=True)

    def command(self, step: str, args: list[str], cwd: Path = ROOT, timeout: int = 3600) -> bool:
        started = time.monotonic()
        try:
            done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as error:
            self.record(step, "失敗", str(error)[:300])
            return False
        tail = (done.stdout + done.stderr).strip().splitlines()[-3:]
        seconds = f"{time.monotonic() - started:.0f}秒"
        self.record(step, "完了" if done.returncode == 0 else "失敗", f"{seconds} " + " / ".join(tail)[:400])
        return done.returncode == 0


def fetch(run: Run, today: str) -> None:
    work = WORK / today
    session = latest_session()
    if reachable(HOSTS["bill-census"]):
        tmp = work / "bill-census"
        if run.command("取得：成立法（衆議院 議案情報）", [sys.executable, "scripts/fetch_shugiin_bill_census.py", "--out", str(tmp), "--from", str(session), "--to", str(session + 1), "--keika"]):
            target = ACQUIRED / "bill-census-full" / "enacted.csv"
            if (tmp / "enacted.csv").exists():
                old = _read(target)
                merged, added, updated = merge_rows(old, _read(tmp / "enacted.csv"), CENSUS_KEY)
                _write(target, list(old[0].keys()), merged)
                run.record("取り込み：成立法", "完了", f"新規{added}本・更新{updated}本")
    else:
        run.record("取得：成立法（衆議院 議案情報）", "届かない", HOSTS["bill-census"])
    for step, host, args in [
        ("取得：施行日（e-Gov 法令）", HOSTS["enforcement-dates"], [sys.executable, "scripts/fetch_enforcement_dates.py"]),
        ("取得：OECD 産業別付加価値", HOSTS["oecd-industry"], [sys.executable, "scripts/fetch_oecd_industry.py", "--out", "data/acquired/oecd-industry"]),
        ("取得：国際統計（世界銀行など）", HOSTS["intl-stats"], [sys.executable, "scripts/fetch_intl_stats.py", "--out", "data/acquired/intl-stats"]),
        ("取得：国会会議録の会議一覧", HOSTS["diet-minutes"], [sys.executable, "scripts/fetch_diet_minutes.py", "meeting_list", "--session-from", str(session), "--session-to", str(session + 1), "--output-dir", str(work / "diet-minutes"), "--all-pages"]),
    ]:
        if reachable(host):
            run.command(step, args)
        else:
            run.record(step, "届かない", host)


def take_incoming(run: Run, incoming: Path) -> None:
    """Mac で取った data/acquired/<task-id>/*.csv（と manifest.csv）を取り込む。原本（raw）は .local に置く。"""
    if not incoming.is_dir():
        run.record("取り込み：Mac の取得分", "なし", "フォルダが無い")
        return
    count = 0
    for task in sorted(p for p in incoming.iterdir() if p.is_dir()):
        target = ACQUIRED / task.name
        if not target.is_dir():
            run.record(f"取り込み：{task.name}", "飛ばした", "data/acquired に無い task-id")
            continue
        for csv_path in sorted(task.glob("*.csv")):
            if task.name == "bill-census-full" and csv_path.name == "enacted.csv":
                old = _read(target / "enacted.csv")
                merged, added, updated = merge_rows(old, _read(csv_path), CENSUS_KEY)
                _write(target / "enacted.csv", list(old[0].keys()), merged)
                run.record("取り込み：成立法（Mac）", "完了", f"新規{added}本・更新{updated}本")
            else:
                shutil.copyfile(csv_path, target / csv_path.name)
            count += 1
        raw = task / "raw"
        if raw.is_dir():
            shutil.copytree(raw, ROOT / ".local" / task.name / "raw", dirs_exist_ok=True)
    run.record("取り込み：Mac の取得分", "完了", f"{count}ファイル")


def rebuild(run: Run) -> bool:
    for args in PIPELINE:
        if not run.command(f"再計算：{args[1]}", args, cwd=ROOT / "app"):
            return False
    from scripts import build_public_ranking, source_check

    approved = standing_approvals()
    current = json.loads(build_public_ranking.OUTPUT.read_text(encoding="utf-8"))
    # 承認日は公開する法律の組が変わった日にだけ進める（毎日の差分を作らない）。
    same = sorted(current["approval"]["approvedLaws"]) == sorted(set(approved) - build_public_ranking.source_held())
    approved_at = current["approval"]["approvedAt"] if same and current["approval"]["approvedAt"] else str(date.today())
    summary = source_check.rebuild(approved, approved_at if approved else "")
    detail = f"照合{summary['items']}項目・一致{summary['match']}・不一致{summary['mismatch']}・対象外{summary['notApplicable']}"
    if summary["heldOut"]:
        detail += "・公開から外した法律 " + "、".join(summary["heldOut"])
    run.record("出典チェック", "完了" if not summary["mismatch"] else "外した", detail)
    return True


def tests(run: Run) -> bool:
    ok = run.command("検査：Python", [sys.executable, "-m", "pytest", "-q", "tests"])
    ok = run.command("検査：画面のテスト", ["npm", "test", "--silent"], cwd=ROOT / "app") and ok
    ok = run.command("検査：画面のビルド", ["npm", "run", "build", "--silent"], cwd=ROOT / "app") and ok
    return ok


def cleanup(run: Run, delete_remote: bool) -> None:
    run.command("片付け：ワークツリーの記録", ["git", "worktree", "prune"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_WORK_DAYS)
    removed = 0
    if WORK.is_dir():
        for folder in WORK.iterdir():
            if folder.is_dir() and datetime.fromtimestamp(folder.stat().st_mtime, timezone.utc) < cutoff:
                shutil.rmtree(folder)
                removed += 1
    run.record("片付け：古い作業フォルダ", "完了", f"{removed}件")
    if not delete_remote:
        return
    subprocess.run(["git", "fetch", "--prune", "origin"], cwd=ROOT, capture_output=True)
    listed = subprocess.run(["git", "branch", "-r", "--merged", "origin/main", "--format=%(refname:short) %(committerdate:unix)"],
                            cwd=ROOT, capture_output=True, text=True).stdout.split("\n")
    stale_before = time.time() - STALE_DAYS * 86400
    current = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    deleted = []
    for line in filter(None, listed):
        ref, stamp = line.rsplit(" ", 1)
        branch = ref.removeprefix("origin/")
        if not branch.startswith(("claude/", "report/")) or branch == current or float(stamp) > stale_before:
            continue
        if subprocess.run(["git", "push", "origin", "--delete", branch], cwd=ROOT, capture_output=True).returncode == 0:
            deleted.append(branch)
    run.record("片付け：取り込み済みのブランチ", "完了", f"{len(deleted)}本 " + "、".join(deleted))


def report(run: Run, unlabeled: list[dict[str, str]], path: Path) -> None:
    lines = [f"# 自動更新の記録（{date.today()}）", "", "| 段階 | 結果 | 内容 |", "|---|---|---|"]
    lines += [f"| {s['step']} | {s['status']} | {s['detail'].replace('|', '／')} |" for s in run.steps]
    lines += ["", f"振り分けがまだ無い成立法：{len(unlabeled)}本"]
    lines += [f"- {row['id']} {row['題名']}" for row in unlabeled[:50]]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (path.with_suffix(".json")).write_text(json.dumps({"steps": run.steps, "unlabeled": unlabeled}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fetch", action="store_true", help="一次資料のサイトから取る（届くものだけ）")
    parser.add_argument("--incoming", type=Path, help="Mac で取った data/acquired と同じ形のフォルダ")
    parser.add_argument("--rebuild", action="store_true", help="再計算・公開ランキング・出典チェック")
    parser.add_argument("--test", action="store_true", help="Python と画面の検査")
    parser.add_argument("--cleanup", action="store_true", help="古い作業ファイルを消す")
    parser.add_argument("--delete-merged-branches", action="store_true", help="main に取り込み済みの古い claude/・report/ ブランチをリモートから消す")
    parser.add_argument("--all", action="store_true", help="--fetch --rebuild --test --cleanup")
    parser.add_argument("--report", type=Path, default=None)
    args = parser.parse_args()
    if args.all:
        args.fetch = args.rebuild = args.test = args.cleanup = True
    today = str(date.today())
    run = Run()
    if args.fetch:
        fetch(run, today)
    if args.incoming:
        take_incoming(run, args.incoming)
    unlabeled = unlabeled_laws()
    run.record("振り分けの確認", "要対応" if unlabeled else "完了", f"振り分けが無い成立法 {len(unlabeled)}本")
    ok = True
    if args.rebuild:
        ok = rebuild(run)
    if args.test and ok:
        ok = tests(run)
    if args.cleanup:
        cleanup(run, args.delete_merged_branches)
    report(run, unlabeled, args.report or WORK / today / "report.md")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
