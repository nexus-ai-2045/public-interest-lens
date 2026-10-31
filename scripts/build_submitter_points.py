"""提出者ごとの「提出の点」（未成立の提出法案。もし成立していたら、の別欄）。

入力：direction.csv（build_unenacted_direction.py）、submitters.csv（筆頭提出者の人物ID・会派。#132 の出力）
出力：data/derived/unenacted-bills-v1/submitter-points.csv（人物ごと）、submitter-points-party.csv（会派ごと）
使い方：python3 scripts/build_submitter_points.py
- 点は ±1 の件数の合計。「失わせた額」とは混ぜない。合計順位に入れる重み SUBMISSION_WEIGHT は控えめ（成立していないため）。
- 筆頭の人物IDが結べない法案は人物では数えず、会派だけで数える。向き不明の法案は点0（件数にだけ入る）。
"""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

D = Path("data/derived/unenacted-bills-v1")
SUBMISSION_WEIGHT = 0.1  # 成立した法律の点 1 に対する未成立法案の点の重み（おすすめ。ねくが変えられる）


def aggregate(direction: list[dict], submitters: list[dict]) -> tuple[list[dict], list[dict]]:
    sub = {r["id"]: r for r in submitters}
    person: dict[str, dict] = defaultdict(lambda: {"プラス": 0, "マイナス": 0, "向き不明": 0})
    party: dict[str, dict] = defaultdict(lambda: {"プラス": 0, "マイナス": 0, "向き不明": 0})
    for d in direction:
        s = sub.get(d["id"])
        if not s:
            continue
        key = d["向き"] if d["向き"] in ("プラス", "マイナス") else "向き不明"
        if s.get("筆頭の人物ID"):
            person[s["筆頭の人物ID"]][key] += 1
        if s.get("提出会派"):
            party[s["提出会派"]][key] += 1

    def rows(m: dict) -> list[dict]:
        out = [{"キー": k, **v, "提出の点": v["プラス"] - v["マイナス"], "重みつき": round(SUBMISSION_WEIGHT * (v["プラス"] - v["マイナス"]), 2)}
               for k, v in m.items()]
        return sorted(out, key=lambda r: (r["提出の点"], r["キー"]))

    return rows(person), rows(party)


def main() -> None:
    direction = list(csv.DictReader((D / "direction.csv").open(encoding="utf-8")))
    sp = D / "submitters.csv"
    if not sp.exists():
        raise SystemExit("submitters.csv がまだ無い（#132 のマージ後に実行）")
    submitters = list(csv.DictReader(sp.open(encoding="utf-8-sig")))
    p, g = aggregate(direction, submitters)
    for name, rs in (("submitter-points.csv", p), ("submitter-points-party.csv", g)):
        with (D / name).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, ["キー", "プラス", "マイナス", "向き不明", "提出の点", "重みつき"], lineterminator="\n")
            w.writeheader()
            w.writerows(rs)
        print(f"{len(rs)} 行 → {D / name}")


if __name__ == "__main__":
    main()
