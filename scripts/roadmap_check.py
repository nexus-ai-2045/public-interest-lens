#!/usr/bin/env python3
"""docs/ロードマップ.md の「残りの項目」表と docs/adr/ の形を検査し、残りの件数を出す。

- 各行に担当と状態があり、状態は決まった4つのどれか。
- 「済」の行には根拠がある。
- ADR は 0001 から欠番なしで並び、本文に日付と状態がある。
- ゴール指標 G1〜G8 の表の「いま」は、データから数えた値の印（<!--m:キー-->値<!--/m-->）で書く。
  印の値がデータの実測とずれたら落とす。手書きの数字が古くなる問題をここで断つ。

使い方：python3 scripts/roadmap_check.py            （問題があれば終了コード1）
        python3 scripts/roadmap_check.py --update   （印の値を実測に書き換える。ずれの直し方はこれだけ）
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROADMAP = ROOT / "docs" / "ロードマップ.md"
ADR_DIR = ROOT / "docs" / "adr"
STATES = ("済", "進行中", "未着手", "ねくさん待ち")
GOALS = tuple(f"G{n}" for n in range(1, 9))
MARK = re.compile(r"<!--m:([a-z0-9_]+)-->(.*?)<!--/m-->")


def _table_lines(text: str) -> list[str]:
    """残りの項目の表のデータ行（見出し行と区切り行を除く）。"""
    if "## 残りの項目" not in text:
        return []
    section = text.split("## 残りの項目", 1)[1].split("\n## ", 1)[0]
    # 見出し行から節の終わりまでを表とみなし、空でない行はすべて行として扱う（先頭の | が欠けた行や、空行の後の行も拾う）
    lines, in_table = [], False
    for raw in section.splitlines():
        line = raw.strip()
        in_table = in_table or line.startswith("|")
        if in_table and line:
            lines.append(line)
    return [l for l in lines[1:] if not re.fullmatch(r"[|\s:-]+", l)]


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip("|").split("|")]


def roadmap_rows(text: str) -> list[dict[str, str]]:
    rows = []
    for line in _table_lines(text):
        cells = _cells(line)
        if line.startswith("|") and line.endswith("|") and len(cells) == 5 and re.fullmatch(r"R\d+", cells[0]):
            rows.append(dict(zip(("id", "item", "owner", "state", "evidence"), cells)))
    return rows


def check_roadmap(text: str) -> list[str]:
    problems = []
    for line in _table_lines(text):
        cells = _cells(line)
        framed = line.startswith("|") and line.endswith("|")
        if not framed or len(cells) != 5 or not re.fullmatch(r"R\d+", cells[0]):
            problems.append(f"形の崩れた行（| で始まり | で終わる、列は5つ、番号は R+数字）：{line}")
    rows = roadmap_rows(text)
    if not rows:
        return ["残りの項目の表が見つからない"]
    ids = [r["id"] for r in rows]
    for dup in {i for i in ids if ids.count(i) > 1}:
        problems.append(f"{dup}：番号が重複")
    numbers = sorted({int(i[1:]) for i in ids})
    # 末尾の行が消えても気づけるよう、最後の番号は表とは別の行で宣言する。
    declared = re.search(r"最後の番号\s*[:：]\s*R(\d+)", text)
    if not declared:
        problems.append("「最後の番号：R…」の行が無い（末尾の行が消えたことを検出するために要る）")
        last = numbers[-1]
    else:
        last = int(declared.group(1))
        if numbers[-1] != last:
            problems.append(f"最後の番号の宣言 R{last} と表の最後 R{numbers[-1]} が違う（行を足したら宣言も上げる）")
    missing = sorted(set(range(1, max(last, numbers[-1]) + 1)) - set(numbers))
    if missing:
        problems.append("欠番（消えた行）：" + "・".join(f"R{n}" for n in missing))
    for r in rows:
        if not r["owner"]:
            problems.append(f"{r['id']}：担当が空")
        if r["state"] not in STATES:
            problems.append(f"{r['id']}：状態「{r['state']}」は {'・'.join(STATES)} のどれでもない")
        if r["state"] == "済" and not r["evidence"]:
            problems.append(f"{r['id']}：済なのに根拠が空")
    return problems


def check_adrs(adr_dir: Path) -> list[str]:
    problems = []
    files = sorted(adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    for stray in sorted(set(adr_dir.glob("*.md")) - set(files)):
        if stray.name.lower() not in {"readme.md", "template.md"}:
            problems.append(f"{stray.name}：ADR のファイル名は「4桁の番号-名前.md」にする")
    numbers = [int(f.name[:4]) for f in files]
    if not files:
        problems.append("ADR が1件も無い")
    if numbers != list(range(1, len(numbers) + 1)):
        problems.append(f"ADR の番号が欠番か重複：{numbers}")
    for f in files:
        # 題の直後（先頭6行以内）に「日付：」で始まる行を置き、同じ行に「状態：」を書く
        meta = [l for l in f.read_text(encoding="utf-8").splitlines()[:6] if re.match(r"日付\s*[:：]", l)]
        if not meta:
            problems.append(f"{f.name}：題の直後に「日付：」の行が無い")
        elif not re.match(r"日付\s*[:：]\s*[^。、\s]", meta[0]):
            problems.append(f"{f.name}：「日付：」の値が空")
        elif not re.search(r"状態\s*[:：]\s*[^。、\s]", meta[0]):
            problems.append(f"{f.name}：「日付：」の行に「状態：」とその値が無い")
    return problems


def _csv(root: Path, rel: str) -> list[dict[str, str]]:
    with (root / rel).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _head(path: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[:6])


def goal_metrics(root: Path = ROOT) -> dict[str, int]:
    """ゴール指標の「いま」を、リポジトリ内のデータから数える（手書きにしない）。

    入力はすべて追跡されたファイル。議員ページの members.json はビルド生成物なので使わず、
    その入力の関与の一覧から数える。
    """
    laws = _csv(root, "data/derived/all-laws-v1/outcomes.csv")
    old_listed = _csv(root, "data/derived/bill-triage-old/triage.csv")
    old_done = _csv(root, "data/derived/all-laws-old/outcomes.csv")
    involvements = _csv(root, "data/derived/allocation-v1/involvements.csv")
    ranking = json.loads((root / "app/public/distribution/ranking.json").read_text(encoding="utf-8"))["counts"]
    workflows = list((root / ".github" / "workflows").glob("*.yml"))
    scheduled = [w for w in workflows if re.search(r"^\s*-?\s*cron\s*:", w.read_text(encoding="utf-8"), re.M)]
    exists = lambda rel: int((root / rel).exists())  # noqa: E731
    return {
        # G1 母数
        "laws_enacted": len(laws),
        "old_laws_listed": len(old_listed),
        "old_laws_judged": len(old_done),
        # G2 全件に額か理由（結果が空の行が残っていれば未達）
        "laws_unresolved": sum(1 for r in laws if not r["結果"].strip()),
        "laws_with_amount": sum(1 for r in laws if r["結果"] == "額あり"),
        # G3 議員（算入された関与のある人物ID）
        "members_with_involvement": len({r["人物ID"] for r in involvements if r["算入"] == "はい" and r["人物ID"]}),
        # G4 公開
        "laws_published": ranking["published"],
        "laws_confirmed": ranking["confirmed"],
        # G5 公開前検査（ファイルが在る本数）
        "pre_publish_guards": exists("tests/test_public_members_safety.py") + exists("scripts/source_check.py")
        + exists(".repo-preflight/hooks") + exists("scripts/preflight.py"),
        # G6 定期更新・訂正窓口・改善ループ
        "scheduled_workflows": len(scheduled),
        "correction_channel": exists("docs/corrections.md") + exists(".github/ISSUE_TEMPLATE/correction.yml"),
        # G7・G8 実装の有無（未実装は0。実装が入ったら数が動き、ロードマップの更新を促す）
        "adr_0015_adopted": int(not re.search(r"状態\s*[:：]\s*検討案", _head(root / "docs/adr/0015-provisional-evaluation-by-foreign-evidence.md"))),
        "pledge_rate_parties": len(list((root / "data/derived").glob("pledge-rate*"))),
        "loop_levels": len(re.findall(r"^\| L\d ", (root / "docs/フィードバックループ.md").read_text(encoding="utf-8"), re.M)),
    }


def _fmt(n: int) -> str:
    return f"{n:,}"


def goal_rows(text: str) -> list[tuple[str, str]]:
    """ゴール条件の表の (番号, 「いま」の列)。"""
    out = []
    for line in text.splitlines():
        m = re.match(r"\|\s*(G\d+)\s*\|(.*)\|\s*(.*?)\s*\|\s*$", line)
        if m:
            out.append((m.group(1), m.group(3)))
    return out


def check_goal_metrics(text: str, metrics: dict[str, int]) -> list[str]:
    problems = []
    rows = dict(goal_rows(text))
    for g in GOALS:
        if g not in rows:
            problems.append(f"{g}：ゴール条件の表に行が無い")
        elif not MARK.search(rows[g]):
            problems.append(f"{g}：「いま」にデータから数えた値の印（<!--m:キー-->値<!--/m-->）が1つも無い（手書きだけにしない）")
    for key, shown in MARK.findall(text):
        if key not in metrics:
            problems.append(f"指標「{key}」は定義に無い（goal_metrics のキー：{'・'.join(metrics)}）")
        elif shown != _fmt(metrics[key]):
            problems.append(f"指標「{key}」が実測とずれている：書いてある {shown}、データから数えた値 {_fmt(metrics[key])}（--update で直す）")
    return problems


def update_goal_metrics(text: str, metrics: dict[str, int]) -> str:
    return MARK.sub(lambda m: f"<!--m:{m.group(1)}-->{_fmt(metrics[m.group(1)]) if m.group(1) in metrics else m.group(2)}<!--/m-->", text)


def main() -> int:
    text = ROADMAP.read_text(encoding="utf-8")
    metrics = goal_metrics()
    if "--update" in sys.argv[1:]:
        ROADMAP.write_text(update_goal_metrics(text, metrics), encoding="utf-8")
        text = ROADMAP.read_text(encoding="utf-8")
    problems = check_roadmap(text) + check_adrs(ADR_DIR) + check_goal_metrics(text, metrics)
    counts = Counter(r["state"] for r in roadmap_rows(text))
    print("ロードマップ：" + "、".join(f"{s} {counts.get(s, 0)}" for s in STATES))
    print("ゴール指標（実測）：" + "、".join(f"{k} {_fmt(v)}" for k, v in metrics.items()))
    for p in problems:
        print(f"問題：{p}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
