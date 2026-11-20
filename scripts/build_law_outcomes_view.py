"""全法律の結果一覧 `app/public/distribution/law-outcomes.json` を作る（/history の「この期間に施行された法律・政策と評価」用）。

入力：data/derived/all-laws-v1/outcomes.csv（成立した全法律 3,415 本の結果台帳。1本に必ず1つの結果と理由）。
出力は表示に要る列だけ。額は中央値だけ（幅は法律ランキング /ranking で見る）。参考（確かさ「参考」・公開不可）の額は印を付けるだけで、合計には使わない。
額と向きは公開ランキング（ranking.json）に合わせる：ranking.json が1本ごとの額を出さない法律（共有額の参考など）は額を出さず、
向き未確定の印がある法律は side を undetermined にする（国賊側・国士側に分けない。リリース前レビュー指摘1）。
Git に置かない派生物（設計決定0022）。scripts/generate_artifacts.py が入力から作る。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_public_ranking import OUTCOMES, direction_undetermined  # noqa: E402
from scripts.durable_write import write_text as atomic_write_text  # noqa: E402

RANKING = ROOT / "app" / "public" / "distribution" / "ranking.json"
WITHHELD = "1本ごとの額は公開ランキングで出していない（{outcome}）。法律ランキングで見る。全法律の台帳の結果は「{ledger}」"
# 公開ランキングの結果（others の outcome）を、この一覧の5つの結果に写す。写し先の無い結果が来たら止める。
RESULT_OF_OUTCOME = {
    OUTCOMES["excluded"]: "評価対象外",
    OUTCOMES["no_series"]: "測定できない",
    **{OUTCOMES[key]: "保留" for key in ("pending", "source", "triage_hold", "undated", "impact_hold", "amount_hold", "covid_scale",
                                         "hidden_failed", "hidden_shared", "hidden_oversize")},
}
SOURCE = ROOT / "data" / "derived" / "all-laws-v1" / "outcomes.csv"
OUTPUT = ROOT / "app" / "public" / "distribution" / "law-outcomes.json"
RESULTS = ("額あり", "保留", "測定できない", "評価対象外", "効果なし（定例）")


def parse_amount(text: str) -> tuple[str | None, float | None]:
    match = re.match(r"(便益|損失)：中央値=(-?[0-9.]+)", text)
    return (("benefit" if match.group(1) == "便益" else "loss"), float(match.group(2))) if match else (None, None)


def build(ranking: dict | None = None) -> dict:
    ranking = ranking if ranking is not None else json.loads(RANKING.read_text(encoding="utf-8"))
    published = {law["id"]: law for law in ranking["laws"]}
    others = {law["id"]: law for law in ranking["others"]}
    items = []
    with SOURCE.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row["結果"] not in RESULTS:
                raise ValueError(f"結果が想定外: {row['id']} {row['結果']}")
            side, median = parse_amount(row["損失または便益の額"])
            result, reason, certainty, direction = row["結果"], row["理由"], row["確かさ"], row["向き"]
            indicator, stage, unit = row["指標"], row["段階"], row["単位"]
            law = published.get(row["id"])
            if law is not None:
                # 公開ランキングに額がある法律は、額・向き・確かさをそちらに合わせる（/ranking と /history で食い違わせない）
                side = "undetermined" if direction_undetermined(law["notes"]) else law["side"]
                median, certainty, result = law["amountMedianYen"], law["certainty"], "額あり"
                indicator, stage = law["indicator"], law["stage"]
                unit = row["単位"] or f"円（窓 {law['window']} の差）"
                if result != row["結果"] or side == "undetermined":
                    reason = "法律ランキングで出した額（" + "・".join(law["notes"][:2] or [law["certainty"]]) + f"）。全法律の台帳の結果は「{row['結果']}」"
                if side == "undetermined":
                    direction = ""  # 向きの欄も出さない（損失・便益の証拠が無い）
            elif median is not None or row["結果"] == "額あり":
                if row["id"] not in others:
                    raise ValueError(f"結果台帳に額があるのに公開ランキングに無い: {row['id']}")
                # 公開ランキングが1本ごとの額を出さない法律（共有額の参考・税収の見込みなど）は、額を出さず、ランキングの結果にそろえる
                outcome = others[row["id"]]["outcome"]
                if outcome not in RESULT_OF_OUTCOME:
                    raise ValueError(f"公開ランキングの結果をこの一覧の結果に写せない: {row['id']} {outcome}")
                # 額に付いていた向き・確かさ・段階・単位も出さない（出さない額の説明になるため）
                side, median, direction, certainty, stage, unit = None, None, "", "", "", ""
                result = RESULT_OF_OUTCOME[outcome]
                reason = WITHHELD.format(outcome=outcome, ledger=row["結果"])
            items.append({
                "id": row["id"], "title": row["題名"], "field": row["分野"], "indicator": indicator, "certainty": certainty,
                "result": result, "reason": reason, "route": row["経路"], "enforced": row["施行日"], "kind": row["種類"],
                "stage": stage, "direction": direction, "side": side, "median": median, "unit": unit,
                "publishable": row["公開可否"] == "公開可" and law is not None and law["certainty"] != "参考",
            })
    counts = Counter(item["result"] for item in items)
    return {"schema": "law-outcomes/v1", "counts": {key: counts.get(key, 0) for key in RESULTS}, "items": items}


def main() -> int:
    data = build()
    lines = [json.dumps(item, ensure_ascii=False, separators=(",", ":")) for item in data["items"]]
    head = {key: data[key] for key in ("schema", "counts")}
    text = json.dumps(head, ensure_ascii=False, separators=(",", ":"))[:-1] + ',"items":[\n' + ",\n".join(lines) + "\n]}\n"
    atomic_write_text(OUTPUT, text)
    print(f"{OUTPUT.name}: {len(data['items'])} 行")
    return 0


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    raise SystemExit(main())
