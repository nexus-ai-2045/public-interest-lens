"""抜き取り検証の突き合わせ。2系統の独立判定（verification-raw/lineA.json・lineB.json）とサイトの評価（ledger.csv）を比べ、
sample-verdicts.csv（id・判定・食い違い）と opus-queue.json（系統が割れて Opus の裁定が要る行）を出す。

項目：類型／分類（評価対象か）／分野／範囲（産業全体か一部か）。
  合格   2系統が一致した項目が、すべてサイトと合う。
  不合格 2系統が一致した項目のどれかが、サイトと合わない。
  割れ   2系統が割れ、それが合否を左右する → Opus が裁定（opus-verdicts.json を読み込めば反映）。
範囲の規則：参考額（産業の付加価値の差）が付いた法律は、法律の対象が「その産業全体」のときだけ額が合う。
  「産業の一部」なら過大、「産業を特定できない」のに産業を指定していれば分野の取り違え。
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
L = ROOT / "data" / "derived" / "evaluation-ledger-v1"
RAW = L / "verification-raw"
WHOLE = {"経済全体", "対応表なし", ""}


FIELDS = ("農林水産", "労働市場", "金融", "医療・福祉", "交通・移動", "教育", "通信・ネット", "専門サービス・研究開発",
          "文化・娯楽・生活サービス", "エネルギー", "行政のデジタル化", "建設", "製造業", "住宅・不動産", "商業",
          "宿泊・観光", "半導体・電子", "鉱業・採石")


def norm_field(x: str) -> str:
    """名前の表記ゆれ（医療／医療・福祉 など）は先頭の語で同じ分野とみなす。"""
    x = (x or "").split("（")[0].strip()
    if x in WHOLE:
        return "経済全体"
    for f in FIELDS:
        if x == f or x.split("・")[0] == f.split("・")[0]:
            return f
    return x


def judge(site: dict, a: dict, b: dict) -> tuple[str, list[str], list[str]]:
    """(判定, 食い違い項目, 割れ項目)"""
    diffs, splits = [], []
    # 類型
    if site["類型"]:
        if a["類型"] == b["類型"]:
            if a["類型"] != site["類型"]:
                diffs.append(f"類型：サイト{site['類型']}／独立判定{a['類型']}")
        else:
            splits.append("類型")
    # 分類（経済に効くか）：評価対象外・効果なしは「制度のみ」と読み替える
    site_inst = site["分類"] == "評価対象外" or site["到達点"] == "効果なし（定例）"
    ea, eb = a["経済に効くか"], b["経済に効くか"]
    if ea == eb and ea != "判定不能":
        if site_inst != (ea == "制度のみ"):
            diffs.append(f"分類：サイト{'対象外' if site_inst else '対象'}／独立判定{ea}")
    elif ea != eb:
        splits.append("分類")
    # 分野と範囲（額が付いたものだけ。額の前提だから）
    if site["到達点"].startswith(("参考額", "額")):
        fa, fb = norm_field(a["主な産業分野"]), norm_field(b["主な産業分野"])
        sf = norm_field(site["分野"])
        if fa == fb:
            if fa != sf:
                diffs.append(f"分野：サイト{sf}／独立判定{fa}")
        else:
            splits.append("分野")
        ra, rb = a["範囲"], b["範囲"]
        if ra == rb:
            if ra == "産業の一部（狭い特例）":
                diffs.append("範囲：法律の対象は産業の一部なのに、産業全体の差を額に当てている")
            elif ra == "産業を特定できない" and sf != "経済全体":
                diffs.append(f"範囲：産業を特定できない法律に産業「{sf}」を当てている")
        else:
            splits.append("範囲")
    verdict = "不合格" if diffs else ("割れ" if splits else "合格")
    return verdict, diffs, splits


def main() -> int:
    A = {x["id"]: x for x in json.loads(Path(RAW / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads(Path(RAW / "lineB.json").read_text(encoding="utf-8"))}
    ledger = {r["id"]: r for r in csv.DictReader(Path(L / "ledger.csv").read_text(encoding="utf-8").splitlines())}
    opus_path = RAW / "opus-verdicts.json"
    opus = json.loads(Path(opus_path).read_text(encoding="utf-8")) if opus_path.exists() else {}
    rows, queue = [], []
    for i, a in A.items():
        v, diffs, splits = judge(ledger[i], a, B[i])
        if v == "割れ":
            if i in opus:
                v, diffs = opus[i]["判定"], [opus[i]["理由"]] if opus[i]["判定"] == "不合格" else []
            else:
                queue.append({"id": i, "題名": ledger[i]["題名"], "割れ": splits, "A": a, "B": B[i], "サイト": {k: ledger[i][k] for k in ("類型", "分類", "到達点", "分野", "額（円）")}})
        rows.append({"id": i, "判定": v, "食い違い": "／".join(diffs + [f"割れ:{s}" for s in splits if v == "割れ"])})
    with (L / "sample-verdicts.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["id", "判定", "食い違い"])
        w.writeheader()
        w.writerows(rows)
    (L / "opus-queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=1), encoding="utf-8")
    from collections import Counter
    print(Counter(r["判定"] for r in rows), "Opus待ち", len(queue))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
