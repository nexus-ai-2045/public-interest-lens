"""公開サイトが読むデータ（app/public/distribution/）を、派生データから決まった順で全部作り直す入口。

どのページも同じ最新データを出すように、作り直しはこの1本だけから行う（毎朝の自動更新 daily_update.py も、手で直すときも同じ）。
途中を飛ばすと、ページごとに古い段階のデータが残る（例：額の表を変えたのに議員ページや一覧を作り直さない）。
tests/test_public_sync.py が、公開データ同士の照合値（SHA-256）と件数がそろっていることを毎回確かめる。

順番（前の出力が後の入力になる）：
  0. 人物ID の台帳 persons.csv と、関与の一覧への人物ID・役職の照合（scripts/person_ids.py --annotate-involvements）。
     関与の一覧は氏名ではなく人物IDで数えるので、議員ページ（6.）より前に回す。関与の一覧そのものの作り直し（allocation_involvements.py）は
     非公開の作業データが要るので入口に含めない。そちらを回したときも、続けてこの入口を回せば人物IDがそろう
  1. 振り分け v2 系統2（scripts/triage_v2_line2.py）
  2. 判定ルール（app/scripts）：振り分け v2 系統1 → 影響 → 損失 → 便益と公開判定
  3. 全法律の結果（scripts/build_all_laws_outcomes.py）
  4. コロナ対応の費用便益（scripts/build_covid_benefit.py）→ 全体指標の参考の額（scripts/build_macro_amounts.py）
  5. 公開ランキング ranking.json と出典チェック（scripts/source_check.rebuild）
  6. 閣法の所管の省庁（scripts/build_ministry_bills.py build）→ 税の帳簿（scripts/build_tax_ledger.py）→ 団体の帳簿（scripts/build_org_ledger.py）→ 経済界の帳簿（scripts/build_business_ledger.py）→ 背後の力の結び付け（scripts/build_backing_forces.py）→ 自動の関与（scripts/build_auto_involvements.py）→ 修正案の提出者（scripts/build_committee_amend_involvements.py）→ 反対票の一覧（scripts/build_opposing_votes.py）→ 採決ごとの会派（scripts/build_vote_parties.py）→ 議員ページ members.json（scripts/build_public_members.mjs）→ もう一度出典チェック
  7. 全議員の表 members-reference.json（参考の額を印つきの別の欄で配る。scripts/build_reference_members.mjs）
  8. 法律の一覧 laws.json と laws-detail/、法律の「何をする」の一文の表 law-names.json（scripts/build_laws_catalog.py）→ 暫定評価 provisional.json（scripts/build_provisional.py）
  9. 物価の換算表 price-index.json（scripts/build_price_index.py）→ データベース data/db/kokuzoku.sqlite（Git に入れない）と、グラフ用の集計 charts.json（scripts/build_database.py）。
     計算式の清書 docs/計算式.md が正本（app/src/method-spec.ts）と一致するかも確かめる

使い方（リポジトリのルートで）：python3 scripts/rebuild_public.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RULES = [
    ["node", "scripts/run-triage-v2-line1.mjs"],
    ["node", "scripts/run-impact-v1.mjs", "--triage", "v2"],
    ["node", "scripts/run-loss-v1.mjs", "--triage", "v2"],
    ["node", "scripts/run-benefit-v1.mjs", "--triage", "v2"],
]
# 法律単位は全件公開（2026-10-17 の常時承認）。承認日は記録済みの日付を引き継ぎ、毎日の差分を作らない。
DEFAULT_APPROVED_AT = "2026-10-17"

Record = Callable[[str, str, str], None]


def _print(step: str, status: str, detail: str = "") -> None:
    print(f"[{status}] {step} {detail}", flush=True)


def _command(record: Record, step: str, args: list[str], cwd: Path = ROOT, timeout: int = 3600) -> bool:
    start = time.time()
    try:
        done = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as error:
        record(step, "失敗", str(error)[:300])
        return False
    tail = (done.stdout + done.stderr).strip().splitlines()[-3:]
    record(step, "完了" if done.returncode == 0 else "失敗", f"{time.time() - start:.0f}秒 " + " / ".join(tail)[:400])
    return done.returncode == 0


def rebuild(record: Record = _print) -> bool:
    """0〜9 を順に回す。どこかで落ちたら、その先は作らずに False を返す。"""
    py = sys.executable
    if not _command(record, "人物ID：台帳と関与の一覧", [py, "scripts/person_ids.py", "--annotate-involvements"]):
        return False
    if not _command(record, "再計算：振り分け v2 系統2", [py, "scripts/triage_v2_line2.py"]):
        return False
    for args in RULES:
        if not _command(record, f"再計算：{args[1]}", args, cwd=ROOT / "app"):
            return False
    if not _command(record, "再計算：全法律の結果", [py, "scripts/build_all_laws_outcomes.py"]):
        return False
    # コロナ対応の費用便益（支出の規模 × 帰属 × 乗数）。macro.csv のコロナ対応の行がこの出力を読むので、先に回す。
    if not _command(record, "再計算：コロナ対応の費用便益", [py, "scripts/build_covid_benefit.py"]):
        return False
    if not _command(record, "再計算：全体指標の参考の額", [py, "-m", "scripts.build_macro_amounts"]):
        return False

    from scripts import build_public_ranking, source_check

    # ranking.json は Git に置かない派生物（設計決定0022）。まだ無ければ既定の承認日で作る
    output = build_public_ranking.OUTPUT
    current = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"approval": {"approvedAt": ""}}
    approved_at = current["approval"]["approvedAt"] or DEFAULT_APPROVED_AT
    summary = source_check.rebuild(True, approved_at)
    detail = f"照合{summary['items']}項目・一致{summary['match']}・不一致{summary['mismatch']}・対象外{summary['notApplicable']}"
    if summary["heldOut"]:
        detail += "・公開から外した法律 " + "、".join(summary["heldOut"])
    record("出典チェック", "完了" if not summary["mismatch"] else "外した", detail)
    # 議員ページは出典チェック後の公開ランキングと同じ派生データから作り、作り直したあとにもう一度照合する。
    # 関与の一覧が無い法律の機械的な関与と、反対票の一覧（参議院の個人別の投票から）を先に作る（設計決定0014）。
    if not _command(record, "閣法の所管の省庁", [sys.executable, "scripts/build_ministry_bills.py", "build"]):
        return False
    if not _command(record, "税の帳簿", [sys.executable, "scripts/build_tax_ledger.py"]):
        return False
    if not _command(record, "団体の帳簿・省庁の抵抗の件数", [sys.executable, "scripts/build_org_ledger.py"]):
        return False
    if not _command(record, "経済界の帳簿", [sys.executable, "scripts/build_business_ledger.py"]):
        return False
    if not _command(record, "背後の力の結び付け", [sys.executable, "scripts/build_backing_forces.py"]):
        return False
    if not _command(record, "自動の関与", [sys.executable, "scripts/build_auto_involvements.py"]):
        return False
    if not _command(record, "修正案の提出者（委員会の審議）", [sys.executable, "scripts/build_committee_amend_involvements.py"]):
        return False
    if not _command(record, "反対票の一覧", [sys.executable, "scripts/build_opposing_votes.py"]):
        return False
    if not _command(record, "採決ごとの会派", [sys.executable, "scripts/build_vote_parties.py"]):
        return False
    if not _command(record, "議員ページ：members.json", ["node", "scripts/build_public_members.mjs"]):
        return False
    summary = source_check.rebuild(True, approved_at)
    if summary.get("memberMismatch"):
        record("出典チェック（議員ページ）", "失敗", f"不一致{summary['memberMismatch']}件。取り込まない")
        return False
    # 全議員の表は公開ランキングの参考の額から作る（確かな額の議員ページとは別のファイル）。
    attributions = ROOT / ".local" / "reference-attributions.csv"
    attributions.parent.mkdir(exist_ok=True)
    if not _command(record, "全議員の表：members-reference.json", ["node", "scripts/build_reference_members.mjs", "--attributions", str(attributions)]):
        return False
    # 全議員の表の全員・全法律の配り先（提出者・参議院の賛成）を、別の実装で一次資料と照らし合わせる。合わなければ取り込まない。
    if not _command(record, "出典チェック（全議員の表）", [py, "scripts/check_reference_members.py", "--attributions", str(attributions)]):
        return False
    # 全法律の一覧（/ranking）は、公開ランキングと議員ページを作り直したあとに並べ直す。
    if not _command(record, "法律の一覧：laws.json", [py, "scripts/build_laws_catalog.py"]):
        return False
    # 暫定評価（provisional-v1）。直近の法律の件数と政策カードを、laws.json に合わせて作り直す。
    if not _command(record, "暫定評価：provisional.json", [py, "scripts/build_provisional.py"]):
        return False
    # 未成立の提出法案の暫定規模点（R61）。公開ファイル unenacted.json にする。
    if not _command(record, "未成立の提出法案：unenacted.json", [py, "scripts/build_public_unenacted.py"]):
        return False
    # 物価の換算表（price-v1）。法律の額を最新年の円に直して並べるのに使う。
    if not _command(record, "物価の換算表：price-index.json", [py, "scripts/build_price_index.py"]):
        return False
    # データベースとグラフ用の集計は、ほかの公開データがそろってから作る（全部を入力にする）。
    if not _command(record, "データベース：kokuzoku.sqlite と charts.json", [py, "scripts/build_database.py"]):
        return False
    return _command(record, "計算式の清書：docs/計算式.md", ["node", "scripts/build_formula_doc.mjs", "--check"], cwd=ROOT / "app")


def main() -> int:
    return 0 if rebuild() else 1


if __name__ == "__main__":
    sys.exit(main())
