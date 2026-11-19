"""全法律の結果一覧 `app/public/distribution/law-outcomes.json` を作る（/history の「この期間に施行された法律・政策と評価」用）。

入力：data/derived/all-laws-v1/outcomes.csv（成立した全法律 3,415 本の結果台帳。1本に必ず1つの結果と理由）。
出力は表示に要る列だけ。額は中央値だけ（幅は法律ランキング /ranking で見る）。参考（確かさ「参考」・公開不可）の額は印を付けるだけで、合計には使わない。
額と向きは公開ランキング（ranking.json）に合わせる：ranking.json が1本ごとの額を出さない法律（共有額の参考など）は額を出さず、
向き未確定の印がある法律は side を undetermined にする（国賊側・国士側に分けない。リリース前レビュー指摘1）。
Git に置かない派生物（設計決定0022）。scripts/generate_artifacts.py が入力から作る。
"""
from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_public_ranking import direction_undetermined  # noqa: E402

RANKING = ROOT / "app" / "public" / "distribution" / "ranking.json"
WITHHELD = "1本ごとの額は公開ランキングで出していません（{outcome}）。法律ランキングで見てください"
SOURCE = ROOT / "data" / "derived" / "all-laws-v1" / "outcomes.csv"
OUTPUT = ROOT / "app" / "public" / "distribution" / "law-outcomes.json"
RESULTS = ("額あり", "保留", "測定できない", "評価対象外", "効果なし（定例）")


def parse_amount(text: str) -> tuple[str | None, float | None]:
    match = re.match(r"(便益|損失)：中央値=(-?[0-9.]+)", text)
    return (("benefit" if match.group(1) == "便益" else "loss"), float(match.group(2))) if match else (None, None)


def build() -> dict:
    ranking = json.loads(RANKING.read_text(encoding="utf-8"))
    published = {law["id"]: law for law in ranking["laws"]}
    others = {law["id"]: law for law in ranking["others"]}
    items = []
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["結果"] not in RESULTS:
                raise ValueError(f"結果が想定外: {row['id']} {row['結果']}")
            side, median = parse_amount(row["損失または便益の額"])
            withheld = None
            if median is not None:
                law = published.get(row["id"])
                if law is None:
                    # 公開ランキングが1本ごとの額を出さない法律は、ここでも額を出さない（画面どうしで食い違わせない）
                    side, median = None, None
                    withheld = WITHHELD.format(outcome=others.get(row["id"], {}).get("outcome", "結果なし"))
                elif direction_undetermined(law["notes"]):
                    side = "undetermined"
            items.append({
                "id": row["id"], "title": row["題名"], "field": row["分野"], "indicator": row["指標"], "certainty": row["確かさ"],
                "result": row["結果"], "reason": row["理由"], "route": row["経路"], "enforced": row["施行日"], "kind": row["種類"],
                "stage": row["段階"], "direction": row["向き"], "side": side, "median": median, "unit": row["単位"],
                "publishable": row["公開可否"] == "公開可",
                **({"amountWithheld": withheld} if withheld else {}),
            })
    counts = Counter(item["result"] for item in items)
    return {"schema": "law-outcomes/v1", "counts": {key: counts.get(key, 0) for key in RESULTS}, "items": items}


def main() -> int:
    data = build()
    lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in data["items"]]
    head = {key: data[key] for key in ("schema", "counts")}
    text = json.dumps(head, ensure_ascii=False, separators=(",", ":"))[:-1] + ',"items":[\n' + ",\n".join(lines) + "\n]}\n"
    OUTPUT.write_text(text, encoding="utf-8")
    print(f"{OUTPUT.name}: {len(data['items'])} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
