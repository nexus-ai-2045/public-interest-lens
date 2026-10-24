"""毎日の自動更新：事前チェック → 取得 → 振り分けの確認 → 再計算 → 公開ランキング → 出典チェック → 検査 → 片付け。

定期実行（Claude の定期ルーチン）から `python3 scripts/daily_update.py --all` で呼ぶ。手元でも同じ入口で動く。
各段階は独立に落ちてよく、落ちた段階と理由を報告に残して次へ進む（ただし再計算が落ちたら公開ランキングは作らない）。

- 事前チェック：最初に scripts/preflight.py を回し、止まる原因（構文・入口・通信先・権限・Vercel の枠・個人名義）を
  先に測って報告に載せる（設計決定0010）。失敗があれば再計算と公開ランキングは作らない。
- 取得：一次資料のサイトに届くときだけ取る。届かなければ「届かない」と記録して飛ばす（0や空で埋めない）。
  Mac で取った原本と表は `--incoming <フォルダ>` で渡す（中身は data/acquired/<task-id>/ と同じ形）。
- 振り分け：成立法のうち、AI の振り分け（2系統）がまだ無い法律を一覧にする。定期ルーチンの Claude が2系統で付ける。
- 再計算：判定ルール（triage v2 の2系統 → 影響 → 損失 → 便益と公開判定 → 全件の結果 → 全体指標の額）を順に回す。
- 評価ループ：AI の判定がまだ要る法律（A・B が割れた振り分け、分野ラベルの無い全体指標の法律）と出典チェックの不一致を
  queue.json に出す。定期ルーチンの Claude がこれを Haiku 2系統 → Sonnet → Opus の木で判定し、誤りの型を
  docs/学習記録/ に記録して判定ルールを直す（docs/自動更新.md の「評価ループ」）。
- 公開ランキング：公開可の法律は全件公開（2026-10-17 の常時承認）。出典チェックの不一致は外す。
- 議員ページ：同じ派生データから作り直し、出典チェックで照合する（不一致があれば取り込まない）。
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
    "political-funds": "www.soumu.go.jp",
    "fiscal": "www.mof.go.jp",
    # fetch_fiscal_more.py（特別会計・国債・地方財政の過去分・国策の数値目標）。毎朝の段は財務省に届くかで回すかを決め、
    # 内閣府・デジタル庁は事前チェック（preflight の通信の確かめ）で見る。段ごとに落ちても残りを回し、落ちた段は1週間後に取り直す。
    "fiscal-policies": "www5.cao.go.jp",
    "fiscal-digital": "www.digital.go.jp",
    # fetch_target_series.py（数値目標の達成状況を測る系列）。毎朝の段は内閣府 経済社会総合研究所に届くかで回すかを決め、
    # ほかの取得先（厚労省・JNTO・観光庁・財務省・農水省・総務省・国環研）は段ごとに落ちても残りを回す。
    "target-series": "www.esri.cao.go.jp",
}
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


def _line_inputs(derived: Path) -> dict[str, tuple[str, str, str]]:
    """法律ごとの今の系統1・系統2の値と会議録の要約の指紋（eval_loop.prepare が inputs.json に書くのと同じ式）。"""
    from scripts import eval_loop  # eval_loop は daily_update を読むので、ここで読む

    line1 = {r["id"]: r for r in _read(derived / "bill-triage-v2" / "labels-line1.csv")}
    line2 = {r["id"]: r for r in _read(derived / "bill-triage-v2" / "labels-line2.csv")}
    overviews = derived / "law-overviews-v1" / "overviews.csv"
    overview = {r["id"]: r for r in _read(overviews)} if overviews.exists() else {}
    return {law: (eval_loop.value1(line1.get(law)), eval_loop.value2(line2.get(law)),
                  eval_loop.overview_value(overview.get(law, {}).get("何をする", ""), overview.get(law, {}).get("狙い", "")))
            for law in set(line1) | set(line2)}


def _line_record_is_current(stored: dict[str, str] | None, current: tuple[str, str, str], title: str) -> bool:
    """記録した入力が今と同じなら、同じ判定を引き直さない。題名が空の古い行は3つの指紋だけで見る。"""
    if stored is None:
        return False
    recorded = (stored.get("系統1の値", ""), stored.get("系統2の値", ""), stored.get("概要の値", ""))
    if recorded != current:
        return False
    stored_title = stored.get("題名", "")
    return not stored_title or stored_title == title


def evaluation_queue(derived: Path = DERIVED) -> dict[str, list[dict[str, str]]]:
    """AI の判定がまだ要る法律（毎日の評価ループの入力）。

    - 振り分けの決着：系統1で A・B が割れて種類か分野が空のまま（規則 D5）で、第3の判定者（tiebreak.csv）の値も無い法律
    - 分野ラベル：全体指標の額で、振り分けの分野が空か対応表なしで、AI 2系統（ai-field-v1）のラベルも無い法律
      （エネルギー・労働市場などは産業の節が決まっていて全産業にしているので、ラベルを足しても変わらず対象外）
    - 出典チェック：公開から外した法律（翌日も照合し直す。直らなければ原因を学習記録に残す）
    - 系統の決着：振り分け v2 の一致表が保留で、第3の判定者の記録が無いか、記録した入力（系統1・系統2の値、会議録の要約、題名）が今と違う法律。同じ入力は判定し直さない
    """
    def rows(path: Path) -> list[dict[str, str]]:
        return _read(path) if path.exists() else []

    tiebreak = {row["id"] for row in rows(derived / "bill-triage-v1" / "tiebreak.csv")}
    triage = {row["id"]: row for row in rows(derived / "bill-triage-v1" / "triage.csv")}
    needs_tiebreak = [
        {"id": row["id"], "題名": row["題名"], "決める項目": "・".join(k for k in ("種類", "分野") if not triage.get(row["id"], {}).get(k))}
        for row in rows(derived / "bill-triage-v2" / "labels-line1.csv")
        if row["規則"].split("／")[0] == "D5" and row["id"] not in tiebreak
    ]
    labeled = {row["id"] for row in rows(derived / "ai-field-v1" / "labels.csv")}
    needs_field = [{"id": row["id"], "題名": row["題名"]} for row in rows(derived / "macro-v1" / "macro.csv")
                   if row["分野の由来"] == "対応表なし" and row["分野"] in ("", "経済全体") and row["id"] not in labeled
                   and triage.get(row["id"], {}).get("分野", "") in ("", "対応表なし")]
    summary = derived / "source-check" / "summary.json"
    held = json.loads(summary.read_text(encoding="utf-8")).get("heldOut", []) if summary.exists() else []
    # 同じ入力（題名、系統1・系統2の値、会議録の要約）を毎朝判定し直すと、2系統がたまたま一致するまで引き直す
    # （2026-10-18、前日に保留だった閣法-155-14 などが新しい資料なしに一致へ変わった）
    judged = {row["id"]: row for row in rows(derived / "bill-triage-v2" / "tiebreak-lines.csv")}
    now = _line_inputs(derived)
    needs_line = [{"id": row["id"], "題名": row["題名"]} for row in rows(derived / "bill-triage-v2" / "agreement.csv")
                  if row["結果"] == "保留" and not _line_record_is_current(judged.get(row["id"]), now.get(row["id"], ("", "", "")), row["題名"])]
    return {"振り分けの決着": needs_tiebreak, "分野ラベル": needs_field, "出典チェックの不一致": [{"id": i} for i in held],
            "系統の決着": needs_line}


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
        ("取得：国会会議録の会議一覧", HOSTS["diet-minutes"], [sys.executable, "scripts/fetch_diet_minutes.py", "meeting_list", "--session-from", str(session), "--session-to", str(session + 1), "--output-dir", str(ROOT / ".local" / "diet" / f"daily-{today}"), "--all-pages"]),
        # 新しく成立した法律の分だけ取る（済みの行は飛ばす）。1行要約は AI の読み手をまとめて回して足す。
        ("取得：提案理由の説明と反対討論（国会会議録）", HOSTS["diet-minutes"], [sys.executable, "scripts/fetch_bill_speeches.py"]),
        ("取得：まとめて説明された法案の部分を発言の全文から切り出す（国会会議録）", HOSTS["diet-minutes"], [sys.executable, "scripts/split_shared_speeches.py"]),
        # 報告書は年1回の公表なので月1回だけ取る（前回から28日未満なら中で飛ばす）。県選管の分は sources.csv の始点から。
        ("取得：政治資金収支報告書（総務省・都道府県選管、月1回）", HOSTS["political-funds"], [sys.executable, "scripts/political_funds.py", "all", "--monthly"]),
        # 為替介入・予算・決算・地方財政・骨太の方針。公表は年数回なので月1回だけ取り直す（前回から28日未満なら中で飛ばす）。
        ("取得：財政と為替介入（財務省・総務省・内閣府、月1回）", HOSTS["fiscal"], [sys.executable, "scripts/fetch_fiscal.py", "update", "--monthly"]),
        # 特別会計・国債・地方財政の2017年度以前・骨太の2013〜14年・デジタル重点計画・数値目標。段ごとに前回から28日たったものだけ取る。
        # 数値目標の読み手（AI の2系統）は新しい本文が入ったときに回し、結果を .local/fiscal-more/targets/ に置く。
        ("取得：特別会計・国債・地方財政の過去分・国策の数値目標（財務省・総務省・内閣府・デジタル庁、月1回）", HOSTS["fiscal"],
         [sys.executable, "scripts/fetch_fiscal_more.py", "all", "--monthly"]),
        # 数値目標の達成状況：PB・GDP・最低賃金・訪日客・消費額・宿泊・対日直接投資・農林水産物の輸出・研究費・GHG を段ごとに月1回取り、
        # 目標と結び付け直す（数値目標は上の段が作るので、その後に回す）
        ("取得：数値目標の達成状況を測る系列（内閣府・厚労省・JNTO・観光庁・財務省・農水省・総務省・国環研、月1回）", HOSTS["target-series"],
         [sys.executable, "scripts/fetch_target_series.py", "all", "--monthly"]),
    ]:
        if reachable(host):
            run.command(step, args)
        else:
            run.record(step, "届かない", host)
            if host == HOSTS["political-funds"]:
                # 届かない日も、公表期間の切れた個人の支払先は手元のデータで伏せ直す（通信しない段だけ回す）
                run.command("再計算：政治資金収支報告書（公表期間の切れた個人の支払先を伏せ直す）", [sys.executable, "scripts/political_funds.py", "link"])
            if host == HOSTS["target-series"]:
                # 届かない日も、数値目標が変わったら手元の系列で結び付け直す（通信しない段だけ回す）
                run.command("再計算：数値目標と系列の結び付け", [sys.executable, "scripts/fetch_target_series.py", "link", "--offline"])


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
    # 公開データの作り直しは scripts/rebuild_public.py の1本に任せる（全ページが同じ段階のデータを読むように）。
    from scripts import rebuild_public

    return rebuild_public.rebuild(run.record)


def tests(run: Run) -> bool:
    ok = run.command("検査：Python", [sys.executable, "-m", "pytest", "-q", "tests"])
    ok = run.command("検査：画面のテスト", ["npm", "test", "--silent"], cwd=ROOT / "app") and ok
    ok = run.command("検査：画面のビルド", ["npm", "run", "build", "--silent"], cwd=ROOT / "app") and ok
    return ok


def cleanup(run: Run, delete_remote: bool) -> None:
    run.command("片付け：ワークツリーの記録", ["git", "worktree", "prune"])
    cutoff = datetime.now(timezone.utc) - timedelta(days=KEEP_WORK_DAYS)
    removed = 0
    diet = ROOT / ".local" / "diet"
    # 作業フォルダと、会議録の取得で日ごとに作る .local/diet/daily-* を同じ保持期限で消す
    folders = [*(WORK.iterdir() if WORK.is_dir() else []), *(diet.glob("daily-*") if diet.is_dir() else [])]
    for folder in folders:
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


def report(run: Run, unlabeled: list[dict[str, str]], path: Path, queue: dict | None = None) -> None:
    lines = [f"# 自動更新の記録（{date.today()}）", "", "| 段階 | 結果 | 内容 |", "|---|---|---|"]
    lines += [f"| {s['step']} | {s['status']} | {s['detail'].replace('|', '／')} |" for s in run.steps]
    lines += ["", f"振り分けがまだ無い成立法：{len(unlabeled)}本"]
    lines += [f"- {row['id']} {row['題名']}" for row in unlabeled[:50]]
    if queue is not None:
        lines += ["", "評価ループの入力（queue.json）：" + "・".join(f"{name} {len(items)}本" for name, items in queue.items())]
    path.parent.mkdir(parents=True, exist_ok=True)
    if queue is not None:
        (path.parent / "queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
    # 事前チェックは飛ばせない（設計決定0010）。個人名義・権限の検査を経ずに再計算やリモート操作をしない。
    from scripts import preflight

    items = preflight.run_all()
    preflight_ok = not any(i.status == "失敗" for i in items)
    for item in items:
        if item.status != "合格":
            run.record(f"事前チェック（{item.check}）", "失敗" if item.status == "失敗" else "注意", item.detail)
    saved = preflight.save(items)
    run.record("事前チェック", "完了" if preflight_ok else "失敗", f"{preflight.summary(items)}（全項目：{saved.relative_to(ROOT)}）")
    if args.fetch:
        fetch(run, today)
    if args.incoming:
        take_incoming(run, args.incoming)
    unlabeled = unlabeled_laws()
    run.record("振り分けの確認", "要対応" if unlabeled else "完了", f"振り分けが無い成立法 {len(unlabeled)}本")
    ok = preflight_ok
    if args.rebuild and ok:
        ok = rebuild(run)
    if args.test and ok:
        ok = tests(run)
    queue = evaluation_queue()
    run.record("評価ループの入力", "要対応" if any(queue.values()) else "完了",
               "・".join(f"{name} {len(items)}本" for name, items in queue.items()))
    if args.cleanup:
        # 事前チェック（個人名義・権限）が赤のときは、リモートを変える削除はしない。
        if args.delete_merged_branches and not preflight_ok:
            run.record("片付け：リモートのブランチ", "飛ばした", "事前チェックが失敗しているため")
        cleanup(run, args.delete_merged_branches and preflight_ok)
    report(run, unlabeled, args.report or WORK / today / "report.md", queue)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
