"""法律の概要が読む会議録の事実だけを、小さな表（speech-facts.csv）に取り出す。

会議録の発言の全文（speeches.csv）は Mac にしか無く、Git に入れない（設計決定0022）。
法律の一覧 laws.json の概要が使うのは、発言の URL・発言者・日付と、「ほかの法案と同じ発言で区別できない」かどうかだけなので、
それを1法案1行の表にして Git に置く。作り直すのは speeches.csv のある Mac で、結果は単独の PR で入れる。

使い方（speeches.csv のある環境で）：python3 -m scripts.build_speech_facts
"""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEECH_DIR = ROOT / "data" / "acquired" / "bill-speeches"
SEGMENTS = SPEECH_DIR / "segments.csv"
OUTPUT = ROOT / "data" / "derived" / "law-overviews-v1" / "speech-facts.csv"
KINDS = (("説明のURL", "説明"), ("反対のURL", "反対"))
FIELDS = ["id", "説明のURL", "説明の発言者", "説明の日付", "反対のURL", "反対の発言者", "反対の日付", "区別できない"]


def derive(speeches: dict[str, dict[str, str]], split: set[tuple[str, str, str]]) -> list[dict[str, str]]:
    """speeches：id → 行。split：いまの発言 URL から切り出せた (id, 区分, URL)。区別できない＝複数の法案が同じ発言を材料にし、この法案の部分を切り出せなかった区分。"""
    uses = Counter(row[source] for row in speeches.values() for source, _ in KINDS if row.get(source))
    rows = []
    for law_id in sorted(speeches):
        row = speeches[law_id]
        if not any(row.get(source) for source, _ in KINDS):
            continue
        shared = [kind for source, kind in KINDS if row.get(source) and uses[row[source]] > 1 and (law_id, kind, row[source]) not in split]
        rows.append({"id": law_id, **{field: row.get(field, "") for field in FIELDS[1:7]}, "区別できない": "・".join(shared)})
    return rows


def load_inputs(speech_dir: Path = SPEECH_DIR, segments: Path = SEGMENTS) -> tuple[dict[str, dict[str, str]], set[tuple[str, str, str]]]:
    speeches = {row["id"]: row for path in sorted(speech_dir.glob("speeches*.csv")) for row in csv.DictReader(path.open(encoding="utf-8"))}
    split = {(row["id"], row["区分"], row["URL"]) for row in csv.DictReader(segments.open(encoding="utf-8"))} if segments.exists() else set()
    return speeches, split


def main() -> int:
    speeches, split = load_inputs()
    if not speeches:
        print("speeches*.csv が無い。会議録のある環境で回す")
        return 1
    rows = derive(speeches, split)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)}行を {OUTPUT.relative_to(ROOT)} に書いた")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
