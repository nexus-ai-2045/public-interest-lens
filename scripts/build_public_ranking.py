"""公開用の法律ランキング `app/public/distribution/ranking.json` を作る。

入力はリポジトリ内の派生データだけ（publish.csv・loss.csv・impact.csv と件数の元の CSV）。
非公開フォルダ（議員への配分）は読まない。人物の名前・配分額はこのファイルに入れない。

`laws` に入るのは publish.csv が「公開可」で、かつ `--approve-law` で名指しされた法律だけ。
承認リストは手で JSON に書かず、承認カードの結果をこの引数で渡す。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
ACQUIRED = ROOT / "data" / "acquired"
OUTPUT = ROOT / "app" / "public" / "distribution" / "ranking.json"

INPUTS = {
    "enacted": ACQUIRED / "bill-census-full" / "enacted.csv",
    "triage": DERIVED / "bill-triage-v1" / "triage.csv",
    "dated": DERIVED / "bill-triage-v2" / "agreement.csv",
    "impact": DERIVED / "impact-v1-triage-v2" / "impact.csv",
    "loss": DERIVED / "loss-v1-triage-v2" / "loss.csv",
    "publish": DERIVED / "publish-v1-triage-v2" / "publish.csv",
    "enforcement": ACQUIRED / "enforcement-dates" / "enforcement.csv",
}
RULES = ["bill-triage-v2", "impact-rule-v1", "loss-rule-v1", "benefit-rule-v1.2"]
LAW_ID = re.compile(r"(閣法|衆法|参法)-(\d+)-(\d+)\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
AMOUNT = re.compile(r"中央値=(-?\d+);第1四分位=(-?\d+);第3四分位=(-?\d+)")
WINDOW = re.compile(r"（円、(\d{4})〜(\d{4})年")
COUNTRIES = re.compile(r"比較国：\d+か国（([A-Z・]+)）")
REASONS = {
    "R1": "参考の行や保留の判定を含むため、額を公開しない",
    "R3": "損失の窓が新型コロナの時期と重なり、分けて測れない",
    "R4": "便益を減らしうる項目が未測定で、純額を出せない",
    "APPROVAL": "公開可の判定。公開の承認待ちのため、額は承認後に表示する",
    "SOURCE": "出典チェックで一次資料と食い違いがあったため、確認がとれるまで額を公開しない",
}
# 出典チェック（scripts/source_check.py）が公開から外した法律。承認済みでも額を出さない。
SOURCE_HELD = DERIVED / "source-check" / "summary.json"


def source_held() -> set[str]:
    if not SOURCE_HELD.exists():
        return set()
    return set(json.loads(SOURCE_HELD.read_text(encoding="utf-8"))["heldOut"])


def _rows(name: str) -> list[dict[str, str]]:
    with INPUTS[name].open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _counts(publish: list[dict[str, str]], loss: list[dict[str, str]]) -> dict[str, int]:
    impact = _rows("impact")
    return {
        "enacted": len(_rows("enacted")),
        "evaluated": sum(1 for row in _rows("triage") if row["結果"] == "評価対象"),
        "dated": len(_rows("dated")),
        "staged": sum(1 for row in impact if re.fullmatch(r"段階[123]", row["判定"])),
        "amounted": sum(1 for row in loss if row["損失または便益の額"] and row["参考フラグ"] != "参考"),
        "publishable": sum(1 for row in publish if row["公開可否"] == "公開可"),
    }


def _sources(law_id: str, enacted: dict[str, dict[str, str]], enforcement: dict[str, dict[str, str]]) -> list[str]:
    urls = []
    census = enacted.get(law_id)
    if census and census["経過URL"].startswith("https://www.shugiin.go.jp/"):
        urls.append(census["経過URL"])
    dated = enforcement.get(law_id)
    if dated:
        for url in dated["出典URL"].split(";"):
            match = re.fullmatch(r"https://laws\.e-gov\.go\.jp/api/2/law_revisions/([0-9A-Z]+)", url)
            if match:
                urls.append(f"https://laws.e-gov.go.jp/law/{match.group(1)}")
    if not urls:
        raise ValueError(f"一次資料の URL がありません: {law_id}")
    return urls


def _law(row: dict[str, str], loss_row: dict[str, str], sources: list[str], enforced: str) -> dict:
    amount = AMOUNT.search(row["損失または便益"])
    window = WINDOW.search(row["損失または便益"])
    if not amount or not window:
        raise ValueError(f"額または窓を読めません: {row['id']}")
    values = [int(value) for value in amount.groups()]
    side = "benefit" if row["側"].startswith("国士側") else "loss"
    # 元の値は「正が失った額、負が得た額」。画面には側ごとの大きさで出す。
    if side == "benefit":
        values = [-value for value in values]
    if min(values) <= 0:
        raise ValueError(f"額の向きが側と一致しません: {row['id']}")
    median, *quartiles = values
    countries = COUNTRIES.search(loss_row["計算式の要素"])
    if not countries:
        raise ValueError(f"比較国を読めません: {row['id']}")
    return {
        "id": row["id"],
        "title": row["題名"],
        "side": side,
        "field": loss_row["分野"],
        "indicator": loss_row["指標"],
        "stage": loss_row["段階"],
        "enforcedOn": enforced,
        "amountMedianYen": median,
        "amountLowYen": min(quartiles),
        "amountHighYen": max(quartiles),
        "lowerBound": row["損失または便益"].startswith("下限"),
        "window": f"{window.group(1)}〜{window.group(2)}年",
        "comparisonCountries": countries.group(1).split("・"),
        "benefitStatus": row["便益の状態"],
        "group": loss_row["観測グループ"],
        "sources": sources,
    }


def build(approved: list[str], approved_at: str, held_by_check: set[str] | None = None) -> dict:
    if approved and not DATE.fullmatch(approved_at):
        raise ValueError("承認日は YYYY-MM-DD で渡してください")
    if len(set(approved)) != len(approved) or any(not LAW_ID.fullmatch(item) for item in approved):
        raise ValueError("承認する法律の id が不正です")
    publish = _rows("publish")
    loss = {row["id"]: row for row in _rows("loss")}
    publishable = {row["id"] for row in publish if row["公開可否"] == "公開可"}
    unknown = sorted(set(approved) - publishable)
    if unknown:
        raise ValueError(f"公開可でない法律は承認できません: {unknown}")
    enacted = {f"{row['種別']}-{row['提出回次']}-{row['番号']}": row for row in _rows("enacted")}
    enforcement = {row["id"]: row for row in _rows("enforcement")}
    held_by_check = source_held() if held_by_check is None else held_by_check
    approved = [law_id for law_id in approved if law_id not in held_by_check]
    laws, held = [], []
    for row in publish:
        if row["公開可否"] == "公開可" and row["id"] in approved:
            enforced = enforcement[row["id"]]["施行日"]
            if not DATE.fullmatch(enforced):
                raise ValueError(f"施行日がありません: {row['id']}")
            laws.append(_law(row, loss[row["id"]], _sources(row["id"], enacted, enforcement), enforced))
            continue
        code = row["判定表の行"]
        if row["公開可否"] == "公開可":
            code = "SOURCE" if row["id"] in held_by_check else "APPROVAL"
        if code not in REASONS:
            raise ValueError(f"理由コードが不明です: {row['id']} {code}")
        held.append({
            "id": row["id"],
            "title": row["題名"],
            "side": "benefit" if row["側"].startswith("国士側") else "loss",
            "reasonCode": code,
            "reason": REASONS[code],
        })
    return {
        "schema": "public-ranking/v1",
        "generatedFrom": {
            "rules": RULES,
            "inputs": {name: _digest(path) for name, path in INPUTS.items()},
        },
        "approval": {"approvedAt": approved_at if approved else None, "approvedLaws": sorted(approved)},
        "laws": sorted(laws, key=lambda law: -law["amountMedianYen"]),
        "held": held,
        "counts": {**_counts(publish, list(loss.values())), "published": len(laws)},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-law", action="append", default=[], help="承認カードで名指しされた法律の id（繰り返し可）")
    parser.add_argument("--approved-at", default="", help="承認日（YYYY-MM-DD）")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build(args.approve_law, args.approved_at)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
