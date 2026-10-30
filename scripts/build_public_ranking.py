"""公開用の法律ランキング `app/public/distribution/ranking.json` を作る。

入力はリポジトリ内の派生データだけ（publish.csv・loss.csv・impact.csv と件数の元の CSV）。
非公開フォルダ（議員への配分）は読まない。人物の名前・配分額はこのファイルに入れない。

額のある法律は全件を `laws` に載せる（2026-10-17 のユーザー承認、法律単位だけ。議員の実名は別承認）。
承認は `--approve-all-laws --approved-at YYYY-MM-DD` で渡し、承認の記録（日付・範囲・メモ）を `approval` に残す。
承認を渡さないと額は載せず、すべて「公開承認待ち」として `others` に入れる。
額のない法律も `others` に結果と理由つきで全件載せる（成立した法律の全件が画面で見える）。
各法律の 確かさ（高・中・低・参考）は CSV に 確かさ 列があればそれを使い、無ければ 段階 と 参考フラグ から決める。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import io
import re
from collections import Counter
from pathlib import Path

try:
    from scripts.generation_provenance import generation_metadata
    from scripts.build_all_laws_outcomes import crowded_ids, narrow_measure
except ModuleNotFoundError:
    from generation_provenance import generation_metadata
    from build_all_laws_outcomes import crowded_ids, narrow_measure

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
ACQUIRED = ROOT / "data" / "acquired"
INDUSTRY_VA = ACQUIRED / "oecd-industry" / "industry_va.csv"
OUTPUT = ROOT / "app" / "public" / "distribution" / "ranking.json"

INPUTS = {
    "covidLabels": DERIVED / "covid-response-v1" / "labels.csv",
    "industryVa": INDUSTRY_VA,
    "enacted": ACQUIRED / "bill-census-full" / "enacted.csv",
    "triage": DERIVED / "bill-triage-v1" / "triage.csv",
    "dated": DERIVED / "bill-triage-v2" / "agreement.csv",
    "impact": DERIVED / "impact-v1-triage-v2" / "impact.csv",
    "loss": DERIVED / "loss-v1-triage-v2" / "loss.csv",
    "publish": DERIVED / "publish-v1-triage-v2" / "publish.csv",
    "enforcement": ACQUIRED / "enforcement-dates" / "enforcement.csv",
    "macro": DERIVED / "macro-v1" / "macro.csv",
    "covidBenefit": DERIVED / "covid-benefit-v1" / "benefit.csv",
    "covidRules": DERIVED / "covid-benefit-v1" / "rules.csv",
    "covidSpending": ACQUIRED / "covid-spending" / "spending.csv",
    "covidParams": ACQUIRED / "covid-spending" / "params.csv",
}
RULES = ["bill-triage-v2", "impact-rule-v1", "loss-rule-v1", "benefit-rule-v1.2", "macro-v1", "covid-benefit-v1"]
# 全体指標（macro-v1）の額の印。影響の段階を経ていない参考の額で、合計・議員への配分に使わない。
MACRO_GROUP = "全体指標"
ESTIMATED = "推定（公布日）"
MACRO_NOTE = "全体指標で測った参考の額（影響の段階を経ていない。結果論の差）"
# コロナ対応の法律（covid-benefit-v1）の額。全体指標の差ではなく、支出の規模（一次資料）×帰属×乗数の費用便益。
COVID_ORIGIN = "コロナ対応の費用便益"
COVID_NOTE = "コロナ対応の費用便益で出した参考の額（支出の規模は官公庁の一次資料、帰属と乗数は仮定の幅。財源調達の超過負担は未控除。議員への配分に使わない）"
LAW_ID = re.compile(r"(閣法|衆法|参法)-(\d+)-(\d+)\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
AMOUNT = re.compile(r"中央値=(-?\d+);第1四分位=(-?\d+);第3四分位=(-?\d+)")
WINDOW = re.compile(r"（円、(?:[^）]*?、)?(\d{4})〜(\d{4})年")
UNIT_WINDOW = re.compile(r"開始後(\d+)年の累積、名目は開始前最後の年(\d{4})年")
COUNTRIES = re.compile(r"比較国：\d+か国（([A-Z・]+)）")
APPROVAL_NOTE = "法律単位の結果を全件公開（2026-10-17 ユーザー承認、議員の実名は別承認）"
APPROVAL_SCOPE = "all-laws"
CERTAINTY = ("高", "中", "低", "参考")
# 判定表の行に応じた、額の読み方の注意（機械的に付ける）。
ROW_NOTES = {
    "R3": "コロナ期と重なる",
    "R4": "便益側の一部が未測定",
}
# R3（コロナ期と分離できない）の行は、元の窓の額がコロナ期の落ち込みをそのまま含む。確かさを参考にし、議員への配分に使わない
# （ユーザー 2026-10-24「コロナのマイナスはその法律のせいではない」、設計決定0014）。
COVID_HELD = "コロナ期と分離できない（元の窓の額。議員への配分に使わない）"
# コロナ対応の法律（covid-response-v1）は、施行が2020年以降で窓がコロナ期そのもの。判定表の行に関わらず同じ扱いにする。
COVID_LABELS = INPUTS["covidLabels"]
# コロナ対応の法律で額が付かないものには、元の理由の前にこの一文を出す（設計決定0014 決定4）。
COVID_NO_AMOUNT = "コロナ対応のため額を付けない"
OUTCOMES = {
    "pending": "公開承認待ち",
    "source": "出典チェックで食い違い（確認中）",
    "excluded": "評価対象外",
    "triage_hold": "保留（振り分け）",
    "undated": "施行日が未確定",
    "no_series": "未測定（系列・比較群が足りない）",
    "impact_hold": "保留（影響の判定）",
    "amount_hold": "保留（額の計算・公開条件）",
    "covid_scale": "額は未計算（コロナ対応・規模のみ記録）",
}
REASON_LIMIT = 140
# 出典チェック（scripts/source_check.py）が公開から外した法律。承認済みでも額を出さない。
SOURCE_HELD = DERIVED / "source-check" / "summary.json"


def source_held() -> set[str]:
    if not SOURCE_HELD.exists():
        raise ValueError("出典チェックの記録が無いため公開用の生成を停止します")
    return set(json.loads(SOURCE_HELD.read_text(encoding="utf-8"))["heldOut"])


def covid_response(raw: bytes | None = None) -> frozenset[str]:
    if raw is None:
        if not COVID_LABELS.exists():
            return frozenset()
        raw = COVID_LABELS.read_bytes()
    return frozenset(r["id"] for r in csv.DictReader(io.StringIO(raw.decode("utf-8"))) if r["コロナ対応"] == "はい")


def _rows(name: str, captured: dict[str, bytes] | None = None) -> list[dict[str, str]]:
    raw = INPUTS[name].read_bytes() if captured is None else captured[name]
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _counts(captured: dict[str, bytes]) -> dict[str, int]:
    impact = _rows("impact", captured)
    return {
        "enacted": len(_rows("enacted", captured)),
        # 施行日のある法律のうち、振り分け v2 の両系統が「評価対象外」で一致せず、影響の判定に回った本数。
        "evaluated": len(impact),
        "dated": len(_rows("dated", captured)),
        "staged": sum(1 for row in impact if re.fullmatch(r"段階[123]", row["判定"])),
    }


HOUSEI_URL = re.compile(r"https://www\.shugiin\.go\.jp/internet/itdb_housei\.nsf/html/housei/[0-9A-Za-z]+\.htm")


def _sources(law_id: str, enacted: dict[str, dict[str, str]], enforcement: dict[str, dict[str, str]]) -> list[str]:
    urls = []
    census = enacted.get(law_id)
    if census and census["経過URL"].startswith("https://www.shugiin.go.jp/"):
        urls.append(census["経過URL"])
    dated = enforcement.get(law_id)
    if dated:
        for url in dated["出典URL"].split(";"):
            url = url.strip()
            match = re.fullmatch(r"https://laws\.e-gov\.go\.jp/api/2/law_revisions/([0-9A-Z]+)", url)
            if match:
                urls.append(f"https://laws.e-gov.go.jp/law/{match.group(1)}")
            elif HOUSEI_URL.fullmatch(url):
                urls.append(url)
    if not urls:
        raise ValueError(f"一次資料の URL がありません: {law_id}")
    return list(dict.fromkeys(urls))


# 費用便益で使った係数（params.csv）。型ごとに、帰属の根拠になったグループ。消費に回る割合（限界消費性向）はどの型でも使う。
COVID_PARAM_GROUPS = {"給付の差押禁止": "A", "雇用の維持": "B", "納税の猶予": "", "保険料の引下げ": "B"}
COVID_MPC = "限界消費性向"
ITEM_ID = re.compile(r"\[([^\]]+)\]")


def _covid_sources(rule: dict[str, str], spending: dict[str, dict[str, str]], params: list[dict[str, str]]) -> list[str]:
    """費用便益の支出（spending.csv の項目）と係数（params.csv のグループ）の一次資料 URL。"""
    ids = {i for q in ("下", "中", "上") for col in ("支出", "帰属") for i in ITEM_ID.findall(rule[f"{col}_{q}"])}
    urls = [spending[i]["出典URL"] for i in sorted(ids)]
    groups = COVID_PARAM_GROUPS[rule["型"]]
    urls += [row["出典URL"] for row in params if (groups and row["グループ"] == groups) or COVID_MPC in row["名前"]]
    return list(dict.fromkeys(url for url in urls if url))


def _short(text: str, limit: int = REASON_LIMIT) -> str:
    """理由の文は「／」区切りの頭から、収まる分だけ使う（途中で切るときは … を付ける）。"""
    text = text.removeprefix("公開不可：").strip()
    out = ""
    for part in text.split("／"):
        candidate = f"{out}／{part}" if out else part
        if len(candidate) > limit:
            return out if out else candidate[: limit - 1] + "…"
        out = candidate
    return out


def certainty(publish_row: dict[str, str], loss_row: dict[str, str]) -> str:
    """確かさ。CSV に 確かさ 列があればその先頭の語、無ければ 参考フラグ と 段階 から決める。"""
    for row in (publish_row, loss_row):
        label = (row.get("確かさ") or "").strip()
        if label:
            if label[0] == "参" or label[0] in CERTAINTY[:3]:
                return "参考" if label[0] == "参" else label[0]
            raise ValueError(f"確かさの値が不明です: {publish_row['id']} {label}")
    if loss_row["参考フラグ"] == "参考":
        return "参考"
    return {"段階3": "高", "段階2": "中", "段階1": "低"}[loss_row["段階"]]


def _law(row: dict[str, str], loss_row: dict[str, str], sources: list[str], enforced: str, covid_ids: frozenset[str] | None = None) -> dict:
    amount = AMOUNT.search(row["損失または便益"])
    window = WINDOW.search(row["損失または便益"])
    if window:
        years = f"{window.group(1)}〜{window.group(2)}年"
    else:
        # 「元の窓」の行は、損失表の単位（開始後N年の累積、名目は開始前最後の年Y）から窓を決める。
        unit = UNIT_WINDOW.search(loss_row["単位"])
        years = f"{int(unit.group(2)) + 1}〜{int(unit.group(2)) + int(unit.group(1))}年" if unit else ""
    if not amount or not years:
        raise ValueError(f"額または窓を読めません: {row['id']}")
    values = [int(value) for value in amount.groups()]
    side = "benefit" if row["側"].startswith("国士側") else "loss"
    # 元の値は「正が失った額、負が得た額」。画面には側ごとの大きさで出す。
    if side == "benefit":
        values = [-value for value in values]
    level = certainty(row, loss_row)
    median, *quartiles = values
    # 中央値は側の向きに正でなければならない。四分位の幅は0をまたぐことがある（そのまま見せる）。
    if median <= 0:
        raise ValueError(f"額の向きが側と一致しません: {row['id']}")
    countries = COUNTRIES.search(loss_row["計算式の要素"])
    if not countries:
        raise ValueError(f"比較国を読めません: {row['id']}")
    notes = [ROW_NOTES[row["判定表の行"]]] if row["判定表の行"] in ROW_NOTES else []
    if row["判定表の行"] == "R3" or row["id"] in (covid_response() if covid_ids is None else covid_ids):
        level = "参考"
        notes.append(COVID_HELD)
    return {
        "id": row["id"],
        "title": row["題名"],
        "side": side,
        "certainty": level,
        "notes": notes,
        "field": loss_row["分野"],
        "indicator": loss_row["指標"],
        "stage": loss_row["段階"],
        "enforcedOn": enforced,
        "amountMedianYen": median,
        "amountLowYen": min(quartiles),
        "amountHighYen": max(quartiles),
        "lowerBound": row["損失または便益"].startswith("下限"),
        "window": years,
        "comparisonCountries": countries.group(1).split("・"),
        "benefitStatus": row["便益の状態"],
        "group": loss_row["観測グループ"],
        "sources": sources,
    }


def _macro_law(row: dict[str, str], sources: list[str]) -> dict:
    """macro-v1 の行。元の値は正が損失・負が便益なので、中央値の符号で側を決め、側ごとの大きさで出す。"""
    values = [int(row["中央値"]), int(row["第1四分位"]), int(row["第3四分位"])]
    side = "loss" if values[0] > 0 else "benefit"
    if side == "benefit":
        values = [-value for value in values]
    median, *quartiles = values
    if median <= 0:
        raise ValueError(f"全体指標の額が0です: {row['id']}")
    covid = row["分野の由来"] == COVID_ORIGIN
    notes = [COVID_NOTE if covid else MACRO_NOTE]
    if row.get("施行日の由来", "") == ESTIMATED:
        notes.append(f"施行日は{ESTIMATED}")
    if int(row["施行日"][:4]) >= 2020:
        notes.append("コロナ期と重なる")
    origin = {"振り分け": "振り分けの分野", "AI 2系統": "AI 2系統の分野", "対応表なし": "対応表なしのため全産業", "同じ題名にそろえた": "同じ法律の改正の分野にそろえた", COVID_ORIGIN: "", "AI 3段の再判定": "AI 3段の再判定による産業"}[row["分野の由来"]]
    return {
        "id": row["id"],
        "title": row["題名"],
        "side": side,
        "certainty": "参考",
        "notes": notes,
        "field": row["分野"],
        "indicator": "支出の規模（一次資料）×帰属×乗数" if covid else f"{row['計算式の要素'].split('（')[0].removeprefix('OECD 表6 JPN ')}の実質付加価値（{origin}）",
        "stage": "なし（支出の規模から費用便益）" if covid else "なし（全体指標）",
        "enforcedOn": row["施行日"],
        "amountMedianYen": median,
        "amountLowYen": min(quartiles),
        "amountHighYen": max(quartiles),
        "lowerBound": False,
        "window": row["窓"],
        "comparisonCountries": row["比較国"].split("・") if row["比較国"] else [],
        "benefitStatus": "費用便益（財源調達の超過負担は未控除）" if covid else "未測定（全体指標の差だけ）",
        # 独立した支出から計算するので、同じ窓でも法律ごとに別の観測（グループに法律の id を付ける）。
        "group": f"{MACRO_GROUP}-コロナ費用便益-{row['id']}" if covid else f"{MACRO_GROUP}-{row['産業']}",
        "sources": sources,
    }


def _other(law_id: str, title: str, key: str, reason: str) -> dict:
    return {"id": law_id, "title": title, "outcome": OUTCOMES[key], "reason": _short(reason)}


def _no_amount(
    law_id: str,
    title: str,
    publish: dict[str, dict[str, str]],
    loss: dict[str, dict[str, str]],
    impact: dict[str, dict[str, str]],
    dated: dict[str, dict[str, str]],
    triage: dict[str, dict[str, str]],
) -> dict:
    """額の無い法律が、どの段で止まったか。前の段から順に当てる。"""
    if law_id in publish:
        return _other(law_id, title, "amount_hold", publish[law_id]["理由"].split("／")[0])
    row = impact.get(law_id)
    if row:
        if law_id in loss:
            return _other(law_id, title, "amount_hold", loss[law_id]["理由"])
        if row["判定"].startswith("保留（2系統"):
            if "点検R2" in row["理由"]:
                return _other(law_id, title, "triage_hold", "第3の判定者の分野を題名の語が上書きしていたため保留（点検R2）")
            return _other(law_id, title, "triage_hold", "振り分けの2系統が一致しない")
        if row["判定"] == "保留":
            return _other(law_id, title, "impact_hold", row["理由"])
        if row["判定"].endswith("なし"):
            return _other(law_id, title, "no_series", row["理由"])
        if row["判定"] == "段階1":
            # 段階1は損失額を出さない（段階2以上だけが額の対象）。判定は済んでいるので、額の保留として理由を残す。
            return _other(law_id, title, "amount_hold", row["理由"])
        raise ValueError(f"影響の判定が不明です: {law_id} {row['判定']}")
    row = dated.get(law_id)
    if row:
        if row["結果"] != "採用":
            return _other(law_id, title, "triage_hold", row["理由"])
        return _other(law_id, title, "excluded", "2系統とも評価対象外で一致（対応表なし）")
    row = triage[law_id]
    result = row["結果"]
    if result == "評価対象外":
        return _other(law_id, title, "excluded", row["A_理由"] or "評価対象外")
    if result == "評価対象":
        return _other(law_id, title, "undated", "施行日を原文で確定できていないため、影響の判定に進めない")
    return _other(law_id, title, "triage_hold", f"{result}：系統1は{row['A_種類']}・{row['A_判定']}、系統2は{row['B_種類']}・{row['B_判定']}")


def japan_value_added_max(raw: bytes | None = None) -> int:
    """日本の全産業の名目付加価値1年分の最大値。計算時は捕捉済み入力を使う。"""
    raw = INPUTS["industryVa"].read_bytes() if raw is None else raw
    values = [int(float(r["値"]) * 1_000_000) for r in csv.DictReader(io.StringIO(raw.decode("utf-8")))
              if r["国"] == "JPN" and r["産業"] == "_T" and r["価格"] == "V" and r["単位"] == "百万JPY"]
    if not values:
        raise ValueError("日本の全産業の名目付加価値がありません")
    return max(values)


def _reading_notes(laws: list[dict], ceiling: int | None = None) -> None:
    """額の読み方の注意を機械的に足す。
    - 同じ観測グループ・同じ期間・同じ額の法律が複数ある：1つの観測を分け合っている（足し合わせない）。
    - 額が日本の全産業の付加価値1年分を超える：累積の額だが、仮定の影響が大きいので大きさをそのまま読まない。"""
    shared = Counter((law["group"], law["window"], law["amountMedianYen"]) for law in laws)
    ceiling = japan_value_added_max() if ceiling is None else ceiling
    for law in laws:
        n = shared[(law["group"], law["window"], law["amountMedianYen"])]
        if n > 1:
            law["notes"].append(f"同じ額の系列・同じ期間の{n}本が同じ額（1つの観測を共有。足し合わせない）")
        if law["amountMedianYen"] > ceiling:
            law["notes"].append("日本の全産業の付加価値1年分を超える額（仮定の影響が大きい）")


def build(approve_all: bool, approved_at: str, held_by_check: set[str] | None = None) -> dict:
    if approve_all and not DATE.fullmatch(approved_at):
        raise ValueError("承認日は YYYY-MM-DD で渡してください")
    held_by_check = source_held() if held_by_check is None else held_by_check
    if any(not isinstance(law, str) or not LAW_ID.fullmatch(law) for law in held_by_check):
        raise ValueError("出典による保留対象の識別子が不正です")
    # 各入力を一度だけ捕捉し、計算と照合値が別時点の内容を指さないようにする。
    captured = {name: path.read_bytes() for name, path in INPUTS.items()}
    covid_ids = covid_response(captured["covidLabels"])
    publish_rows = _rows("publish", captured)
    publish = {row["id"]: row for row in publish_rows}
    loss = {row["id"]: row for row in _rows("loss", captured)}
    impact = {row["id"]: row for row in _rows("impact", captured)}
    dated = {row["id"]: row for row in _rows("dated", captured)}
    triage = {row["id"]: row for row in _rows("triage", captured)}
    census = _rows("enacted", captured)
    enacted = {f"{row['種別']}-{row['提出回次']}-{row['番号']}": row for row in census}
    enforcement = {row["id"]: row for row in _rows("enforcement", captured)}
    macro = {row["id"]: row for row in _rows("macro", captured) if row["結果"] == "額"}
    # コロナ対応で規模は取れたが額にしない法律は、規模つきの理由を出す（covid-benefit-v1）。
    covid_scale = {row["id"]: row["理由"] for row in _rows("covidBenefit", captured) if row["結果"] == "理由"}
    covid_rules = {row["id"]: row for row in _rows("covidRules", captured) if row["結果"] == "額"}
    covid_spending = {row["項目ID"]: row for row in _rows("covidSpending", captured)}
    covid_params = _rows("covidParams", captured)
    crowded = crowded_ids(loss.values())
    laws, others = [], []
    for law_id, census_row in enacted.items():
        row = publish.get(law_id)
        title = census_row["題名"]
        # コロナ対応の法律は、市場の損失の額が付いていても使わず、費用便益（covid-benefit-v1）か規模つきの理由で出す（全法律の結果と同じ扱い）
        if not row or row["損失または便益"] == "保留" or law_id in covid_ids or law_id in crowded or (narrow_measure(title) and loss.get(law_id, {}).get("段階") == "段階1"):
            if approve_all and law_id in macro and law_id not in held_by_check:
                extra = _covid_sources(covid_rules[law_id], covid_spending, covid_params) if law_id in covid_rules else []
                laws.append(_macro_law(macro[law_id], list(dict.fromkeys(_sources(law_id, enacted, enforcement) + extra))))
            elif law_id in covid_scale:
                others.append(_other(law_id, title, "covid_scale", covid_scale[law_id]))
            else:
                other = _no_amount(law_id, title, publish, loss, impact, dated, triage)
                if law_id in covid_ids:
                    other["reason"] = _short(f"{COVID_NO_AMOUNT}／{other['reason']}")
                others.append(other)
        elif not approve_all:
            others.append(_other(law_id, row["題名"], "pending", "額は計算できているが、公開の承認を受けるまで表示しない"))
        elif law_id in held_by_check:
            others.append(_other(law_id, row["題名"], "source", "出典チェックで一次資料と食い違いがあったため、確認がとれるまで額を公開しない"))
        else:
            enforced = enforcement[law_id]["施行日"]
            if not DATE.fullmatch(enforced):
                raise ValueError(f"施行日がありません: {law_id}")
            laws.append(_law(row, loss[law_id], _sources(law_id, enacted, enforcement), enforced, covid_ids))
    missing = sorted(set(publish) - set(enacted))
    if missing:
        raise ValueError(f"成立法の台帳に無い法律があります: {missing}")
    _reading_notes(laws, japan_value_added_max(captured["industryVa"]))
    # 確かな額（高・中・低）を先、参考を後。どちらも額の大きい順。
    laws.sort(key=lambda law: (law["certainty"] == "参考", law["group"].startswith(MACRO_GROUP), -law["amountMedianYen"], law["id"]))
    reference = sum(1 for law in laws if law["certainty"] == "参考")
    return {
        "schema": "public-ranking/v3",
        "generatedFrom": {
            "rules": RULES,
            **generation_metadata(["scripts/build_public_ranking.py"]),
            "inputs": {name: hashlib.sha256(raw).hexdigest() for name, raw in captured.items()},
            "parameters": {"heldOut": sorted(held_by_check)},
        },
        "approval": (
            {"approvedAt": approved_at, "scope": APPROVAL_SCOPE, "note": APPROVAL_NOTE}
            if approve_all
            else {"approvedAt": None, "scope": None, "note": None}
        ),
        "laws": laws,
        "others": others,
        "counts": {
            **_counts(captured),
            "published": len(laws),
            "confirmed": len(laws) - reference,
            "reference": reference,
            "others": len(others),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve-all-laws", action="store_true", help="法律単位の結果を全件公開する承認を記録する（議員の実名は含まない）")
    parser.add_argument("--approved-at", default="", help="承認日（YYYY-MM-DD）")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    payload = build(args.approve_all_laws, args.approved_at)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
