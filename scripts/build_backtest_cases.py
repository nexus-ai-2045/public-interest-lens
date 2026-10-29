#!/usr/bin/env python3
"""答えの分かっている事例集から、バックテストの正解データ data/evidence/backtest_cases.json を作る。

入力：
  --csv     事例集の CSV（共有フォルダの文献調査。照合欄が「一致」の行だけを使う）
  --labels2 系統2（Haiku）が独立に付けたラベル data/evidence/backtest_labels_line2.json

ラベル（識別の強さ・結果指標の種類・便益の向き・研究の国）は2系統が独立に付け、
一致したものだけを採用する。割れたものは「保留」にして採点から外す（理由を残す）。
系統1（このファイルの LINE1）は、結果（現行計算の向き）を見る前に付けた。
法律との結び付け（link）は系統1だけが付けた（バックテストの限界として docs に書く）。

使い方: python3 scripts/build_backtest_cases.py --csv <事例集.csv>
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "evidence" / "backtest_cases.json"
LABELS2 = ROOT / "data" / "evidence" / "backtest_labels_line2.json"
VERSION = "backtest-cases-v1"

# 事例集の政策名 → 政策グループ（backtest_mapping.json のキー）。日本の法律に当たらないものは None。
GROUPS = {
    "通信の自由化（1985年電電公社民営化・NTT）": "ntt",
    "電力小売全面自由化（2016年）と卸・発送電の自由化": "electricity-retail",
    "民泊（住宅宿泊事業法2018年・Airbnb）": "minpaku",
    "労働者派遣法（1999年原則自由化・2004年製造業解禁・2012/2015年改正）": "haken",
    "郵政民営化（2007年）": "yusei",
    "航空規制緩和（日本の2000年運賃自由化・参入規制緩和・LCC参入）": "koku",
    "大規模小売店舗法の廃止（2000年）と大店立地法": "daiten",
    "国鉄民営化（1987年）": "kokutetsu",
    "タクシー規制緩和（2002年）と再規制（2009年）": "taxi",
    "金融ビッグバン（1996-2001年）": "bigbang",
    "最低賃金の引き上げの雇用効果（日本）": "minwage",
}

# 系統1のラベル。キーは「通し番号|年」（事例集の照合「一致」の行を順に0から数える）。
# (識別, 結果指標, 便益の向き, 研究の国, 法律との結び付き)
#   識別: strong 対照群つきの差の差・操作変数・RCT・合成対照 / medium マッチング・固定効果・構造推定 / weak 前後比較・記述・サーベイ・対照なしの事象研究
#   結果指標: output 産業の生産量・付加価値・TFP・売上 / employment 雇用 / wage 賃金 / price_surplus 価格・手数料・余剰 / other
#   便益の向き: +1 経済に良い / -1 悪い / 0 有意でない・向きが定まらない・記述のみ（効果欄の数値と向きだけで決める）
#   結び付き: event 研究の対象が、その法律の出来事そのもの / broad 同じ政策分野だが出来事とずれる / None 日本の法律に当てられない
LINE1 = {
    "00|2003": ("medium", "output", 1, "日本", "event"),
    "01|2015": ("weak", "price_surplus", 1, "日本", "event"),
    "02|2019": ("strong", "other", 0, "日本", "event"),
    "03|2017": ("strong", "output", -1, "米国", None),
    "04|2021": ("strong", "other", 0, "米国", None),
    "05|2020": ("strong", "other", 0, "その他", None),
    "06|2018": ("medium", "price_surplus", 1, "米国", None),
    "07|2011": ("weak", "other", 0, "日本", "event"),
    "08|2011": ("medium", "employment", 0, "日本", "broad"),
    "09|2011": ("weak", "other", 0, "日本", "event"),
    "10|2010": ("weak", "price_surplus", 0, "日本", "broad"),
    "11|2019": ("weak", "other", 0, "日本", "broad"),
    "12|2013": ("medium", "price_surplus", 1, "日本", "event"),
    "13|2009": ("medium", "output", 1, "日本", "broad"),
    "14|2009": ("medium", "price_surplus", 1, "日本", "broad"),
    "15|2005": ("weak", "output", 1, "日本", "event"),
    "16|2020": ("medium", "other", 0, "日本", "broad"),
    "17|2019": ("weak", "other", 0, "日本", "broad"),
    "18|2009": ("strong", "price_surplus", 1, "日本", "broad"),
    "19|2011": ("weak", "other", 0, "日本", "broad"),
    "20|1999": ("weak", "price_surplus", 1, "日本", "broad"),
    "21|2009": ("medium", "employment", -1, "日本", "broad"),
    "22|2023": ("medium", "employment", -1, "日本", "broad"),
    "23|2019": ("medium", "output", 0, "日本", "broad"),
    "24|2026": ("strong", "employment", -1, "日本", "broad"),
    "25|2026": ("strong", "employment", -1, "日本", "broad"),
    # 以下は外国の研究。日本の計算の対象ではないので、便益の向きは付けない（None）
    "26|2014": ("weak", "price_surplus", None, "米国", None),
    "27|1996": ("medium", "wage", None, "米国", None),
    "28|2011": ("weak", "output", None, "米国", None),
    "29|2014": ("medium", "price_surplus", None, "米国", None),
    "30|2004": ("weak", "other", None, "米国", None),
    "31|2001": ("weak", "output", None, "その他", None),
    "32|1989": ("medium", "output", None, "その他", None),
    "33|2021": ("strong", "price_surplus", None, "その他", None),
    "34|2021": ("strong", "other", None, "その他", None),
    "35|2022": ("strong", "other", None, "その他", None),
    "36|2021": ("strong", "other", None, "その他", None),
    "37|2004": ("strong", "employment", None, "米国", None),
    "38|2011": ("strong", "output", None, "米国", None),
    "39|2017": ("strong", "output", None, "米国", None),
    "40|2015": ("medium", "price_surplus", None, "米国", None),
    "41|2013": ("medium", "other", None, "その他", None),
    "42|2021": ("medium", "other", None, "その他", None),
    "43|2013": ("weak", "other", None, "その他", None),
    "44|2014": ("strong", "other", None, "その他", None),
    "45|2025": ("strong", "output", None, "その他", None),
    "46|2021": ("strong", "output", None, "その他", None),
    "47|1995": ("medium", "output", None, "その他", None),
    "48|2025": ("strong", "output", None, "その他", None),
}


def key_of(index: int, row: dict) -> str:
    """行の通し番号（照合が「一致」の行だけを事例集の順に数える）と年。"""
    return f"{index:02d}|{row['年']}"


def merge(a, b):
    """2系統が一致したらその値、割れたら None（保留）。"""
    return a if a == b else None


def build(csv_path: Path) -> dict:
    with csv_path.open(encoding="utf-8-sig") as handle:
        rows = [r for r in csv.DictReader(handle) if r["照合"] == "一致"]
    line2 = {x["key"]: x for x in json.loads(LABELS2.read_text(encoding="utf-8"))["labels"]}
    cases = []
    for index, row in enumerate(rows):
        key = key_of(index, row)
        design, outcome, sign, country, link = LINE1[key]
        other = line2[key]
        agreed = {
            "design": merge(design, other["design"]),
            "outcome_class": merge(outcome, other["outcome_class"]),
            # 外国の研究は便益の向きを日本の計算と比べないので、2系統の照合も要らない
            "benefit_sign": sign if sign is None else merge(sign, other["benefit_sign"]),
            "country": merge(country, other["evidence_country"]),
        }
        held = sorted(name for name, value in agreed.items() if value is None and not (name == "benefit_sign" and sign is None))
        cases.append({
            "id": f"bt-{index + 1:03d}",
            "key": key,
            "policy": row["事例"],
            "group": GROUPS.get(row["事例"]),
            "link": link,
            "source": {"authors": row["著者"], "year": int(row["年"]), "title": row["題名"], "doi": row["DOI"], "url": row["URL"], "grade": row["等級"], "verified": row["照合"]},
            "method": row["手法"],
            "outcome": row["結果指標"],
            "effect": row["効果"],
            "interval": row["区間"],
            "unit": row["単位"],
            "labels": {
                "line1": {"design": design, "outcome_class": outcome, "benefit_sign": sign, "country": country},
                "line2": {"design": other["design"], "outcome_class": other["outcome_class"], "benefit_sign": other["benefit_sign"], "country": other["evidence_country"]},
                "agreed": agreed,
                "held": held,
            },
        })
    return {"schema": "backtest-cases/v1", "version": VERSION, "source_file": "答えの分かっている事例集_2026-10-29（照合が「一致」の49件）", "cases": cases}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--csv", required=True, type=Path)
    args = parser.parse_args()
    data = build(args.csv)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(data['cases'])} 件 → {OUT.relative_to(ROOT)}（保留あり {sum(1 for c in data['cases'] if c['labels']['held'])} 件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
