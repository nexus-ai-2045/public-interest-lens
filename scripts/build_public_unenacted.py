"""未成立の提出法案の暫定規模点を、公開サイト用の配布ファイルにする。

入力：data/derived/unenacted-bills-v1/scale.csv（scripts/build_unenacted_bills_scale.py）、data/acquired/bill-census-full/listing.csv（経過URL）
出力：app/public/distribution/unenacted.json（点が付いた法案だけ。評価対象外は件数だけ）
規模点は「触れる産業が日本の付加価値の何%か」で、円の額・良い悪いの向きは無い。確かさは常に参考。
使い方（リポジトリのルートで）：python3 scripts/build_public_unenacted.py
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCALE = ROOT / "data" / "derived" / "unenacted-bills-v1" / "scale.csv"
LISTING = ROOT / "data" / "acquired" / "bill-census-full" / "listing.csv"
OUTPUT = ROOT / "app" / "public" / "distribution" / "unenacted.json"
VERSION = "public-unenacted/v1"


def main() -> None:
    with LISTING.open(encoding="utf-8-sig", newline="") as f:
        urls = {(r["種別"], r["提出回次"], r["番号"]): r["経過URL"] for r in csv.DictReader(f)}
    with SCALE.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    bills, excluded = [], Counter()
    for r in rows:
        if r["判定"] != "評価対象" or not r["規模点"]:
            excluded[r["判定"] or "点なし"] += 1
            continue
        number = r["id"].rsplit("-", 1)[1]
        url = urls.get((r["種別"], r["提出回次"], number), "")
        if url and not url.startswith("https://"):
            raise SystemExit(f"経過URLが https でない: {r['id']}")
        bills.append({
            "id": r["id"], "title": r["題名"], "kind": r["種別"], "session": int(r["提出回次"]), "status": r["審議状況"] or "不明",
            "field": r["分野"], "indicator": r["指標"], "scale": float(r["規模点"]), "certainty": r["確かさ"], "url": url,
        })
    bills.sort(key=lambda b: (-b["scale"], b["id"]))
    out = {
        "schema": VERSION,
        "notes": [
            "成立しなかった提出法案（未了・撤回・廃案など）の暫定の規模点です。題名から分野を決め、その分野の産業が日本の付加価値の何%かを点にしています。",
            "円の額と、良い・悪いの向きは付けていません。確かさは参考です。成立した法律の額とは別の表で、足し合わせません。",
        ],
        "counts": {"total": len(rows), "scored": len(bills), "excluded": dict(excluded)},
        "bills": bills,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"unenacted.json: 点つき {len(bills)} 本 / 全 {len(rows)} 本")


if __name__ == "__main__":
    main()
