"""額の出ていない法律に、産業の付加価値（全体指標を含む）で参考の額を付ける（macro-v1）。

ユーザーの指示（2026-10-17）：全3,415本に額か理由を付ける。産業の無い法律は GDP などの全体指標で、確かさ低めの印を付けて額を出す。

対象：施行日があり、all-laws-v1 で「額あり」「評価対象外」「効果なし（定例）」のどれでもない法律。
産業の決め方（この順。1本ごとの人の判断は入れない）：
  1. 振り分け（all-laws-v1 の分野）が産業の分野なら、その分野の ISIC の節。
     ただし v2 の一致が採用でない行は、AI 2系統が産業の分野を持っていれば 1 を使わない
  2. 対応表の無い法律は、AI 2系統の振り分け（data/derived/ai-field-v1/labels.csv、Haiku 2系統→Sonnet 突き合わせ→Opus 確認）
  3. どちらも無い、または「経済全体」なら全産業（OECD 表6 の _T）
  4. 同じ法律の改正（題名から「の一部を改正する法律」などを除いた元の題名が同じもの）は、1〜3で産業の分野が付いた本の
     最も多い分野にそろえる（同数なら1本ごとのまま。振り分けで決まった本は変えない）。由来は「同じ題名にそろえた」（学習記録 ai-field-v1 の誤りの型1）
額は loss-rule-v1 と同じ定義（scripts/source_check.recompute：開始前の伸びの差を織り込んだ反実仮想との差、累積、円）。
影響の段階を経ていないので、すべて「参考（全体指標）」。議員への配分には使わない。
比較国は OECD 表6 で日本以外の取得済みの国のうち、窓の年の観測がそろう国（3か国以上）。
施行日が台帳に無い法律は、公布日を施行日とみなして推定する（判定は年単位。印「施行日は推定（公布日）」を付ける）。
窓は施行後最大10年。2020年より前に始まる窓は2019年で切る（新型コロナの年を入れない）。2020年以降に始まる窓はそのまま使い、注意を付ける。
コロナ対応の法律（data/derived/covid-response-v1/labels.csv、Haiku 2系統→Sonnet 突き合わせ→Opus 点検）は額を付けず理由にする。
全体指標の差はコロナの落ち込みそのもので、その法律の効果ではない。比べるべきは「コロナはあったがその法律が無かった場合」で、
定説（財政乗数・雇用維持の効果）では落ち込みを和らげる向き。支出の規模の一次資料が未取得なので額はまだ出さない（設計決定0014、ユーザー 2026-10-24）。

出力：data/derived/macro-v1/macro.csv
使い方：python3 scripts/build_macro_amounts.py
"""
from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

from scripts.source_check import Oecd, recompute

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
OUTCOMES = DERIVED / "all-laws-v1" / "outcomes.csv"
AI_LABELS = DERIVED / "ai-field-v1" / "labels.csv"
AGREEMENT = DERIVED / "bill-triage-v2" / "agreement.csv"
ENFORCEMENT = ROOT / "data" / "acquired" / "enforcement-dates" / "enforcement.csv"
OECD = ROOT / "data" / "acquired" / "oecd-industry" / "industry_va.csv"
OUT = DERIVED / "macro-v1" / "macro.csv"
COVID_LABELS = DERIVED / "covid-response-v1" / "labels.csv"
# 全産業で測っていた法律の産業への結び直し（AI 3段の判定。ai-field-v1 の後の再判定）。根拠の判定は docs/学習記録/macro-sector-v2.md。
SECTOR_OVERRIDES = DERIVED / "macro-v1" / "sector-overrides.csv"
OVERRIDE_ORIGIN = "AI 3段の再判定"
COVID_REASON = "コロナ対応の法律（{kind}）：全体指標の差はコロナの落ち込みそのもので、この法律の効果ではない。定説（財政乗数・雇用維持の効果）では落ち込みを和らげる向き（便益）。支出の規模の一次資料が未取得のため額は未計算"

HEADER = ["id", "題名", "分野", "分野の由来", "産業", "施行日", "施行日の由来", "窓", "中央値", "第1四分位", "第3四分位",
          "比較国", "計算式の要素", "結果", "理由"]
SKIP = {"額あり", "評価対象外", "効果なし（定例）"}
WHOLE = "経済全体"
# 分野 → OECD 表6 の節（ISIC Rev.4）。取得していない節（E・O）や1つの節に決まらない分野は全産業にする。
# エネルギーは D（電気・ガス・蒸気・空調供給）で測る。D の外のエネルギー（石油・石炭・原子力規制）も含めた代理で、確かさは「参考」のまま。
INDUSTRY = {
    "交通・移動": "H", "宿泊・観光": "I", "通信・ネット": "J", "金融": "K", "半導体・電子": "C",
    "農林水産": "A", "建設": "F", "住宅・不動産": "L", "教育": "P", "医療・福祉": "Q", "製造業": "C",
    "商業": "G", "専門サービス・研究開発": "M", "文化・娯楽・生活サービス": "R",
    "エネルギー": "D", "鉱業・採石": "B",
}
INDUSTRY_LABEL = {"_T": "全産業", "H": "運輸・保管", "I": "宿泊・飲食", "J": "情報通信", "K": "金融・保険", "C": "製造業",
                  "A": "農林水産業", "F": "建設業", "L": "不動産業", "P": "教育", "Q": "保健衛生・社会事業", "G": "卸売・小売業",
                  "M": "専門・科学技術サービス業", "R": "芸術・娯楽",
                  "D": "電気・ガス・蒸気・空調供給業", "B": "鉱業・採石業"}
COVID_START = 2020
ESTIMATED = "推定（公布日）"


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def pick(field: str, ai: str) -> tuple[str, str, str]:
    """(分野, 分野の由来, 産業コード)"""
    if field in INDUSTRY:
        return field, "振り分け", INDUSTRY[field]
    if ai in INDUSTRY:
        return ai, "AI 2系統", INDUSTRY[ai]
    if ai == WHOLE:
        return WHOLE, "AI 2系統", "_T"
    return WHOLE, "対応表なし", "_T"


def publication_field(field: str, ai: str, agreement: str | None) -> tuple[str, str, str]:
    """採用していない行は、AI 2系統が産業の分野を持っていればそちらを公開する。

    一致しなかった単系統の分野を振り分けとして出さない。AI の産業分野が無い行は、
    この交付では既存の pick のままにする。
    """
    if agreement not in (None, "", "採用") and ai in INDUSTRY:
        return pick("", ai)
    return pick(field, ai)


ALIGNED = "同じ題名にそろえた"
# 節 → 分野の名前（結び直しで使う。C は製造業に寄せる）
SECTION_FIELD = {"A": "農林水産", "B": "鉱業・採石", "C": "製造業", "D": "エネルギー", "F": "建設", "G": "商業", "H": "交通・移動",
                 "I": "宿泊・観光", "J": "通信・ネット", "K": "金融", "L": "住宅・不動産", "M": "専門サービス・研究開発", "P": "教育",
                 "Q": "医療・福祉", "R": "文化・娯楽・生活サービス"}


def apply_sector_overrides(picks: dict[str, tuple[str, str, str]], overrides: list[dict[str, str]]) -> dict[str, tuple[str, str, str]]:
    """結び直しの表（id, 節）を、振り分けで産業が決まっていない行にだけ当てる。振り分けで決まった行は変えない。"""
    out = dict(picks)
    for row in overrides:
        law_id, section = row["id"], row["節"]
        if law_id in out and section in SECTION_FIELD and out[law_id][1] != "振り分け":
            out[law_id] = (SECTION_FIELD[section], OVERRIDE_ORIGIN, section)
    return out


def base_title(title: str) -> str:
    """改正法の題名から元の法律の題名を取り出す。"""
    title = re.sub(r"(の一部|等の一部)?を改正する法律(案)?$", "", title)
    return re.sub(r"法律案$", "法律", title)


def align_by_title(picks: dict[str, tuple[str, str, str]], titles: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    """同じ元の題名の法律の分野を、産業の分野が付いた本の最多の分野にそろえる。"""
    groups: dict[str, list[str]] = {}
    for law_id in picks:
        groups.setdefault(base_title(titles[law_id]), []).append(law_id)
    out = dict(picks)
    for ids in groups.values():
        counts = Counter(picks[i][0] for i in ids if picks[i][0] in INDUSTRY).most_common()
        if not counts or (len(counts) > 1 and counts[0][1] == counts[1][1]):
            continue
        field = counts[0][0]
        for i in ids:
            if picks[i][0] != field and picks[i][1] != "振り分け":
                out[i] = (field, ALIGNED, INDUSTRY[field])
    return out


def controls_for(oecd: Oecd, industry: str) -> list[str]:
    return sorted({c for (c, ind, price) in oecd.series if c != "JPN" and ind == industry and price == "LR"})


def amount(oecd: Oecd, industry: str, start: str) -> tuple[dict | None, list[str], str]:
    start_year = int(start[:4])
    end_year = COVID_START - 1 if start_year < COVID_START else 9999
    candidates = controls_for(oecd, industry)
    jp = oecd.get("JPN", industry, "LR")
    pre = sorted(y for y in jp if f"{y}-12-31" < start)
    if len(pre) < 3:
        return None, [], "日本の系列に施行前の年が足りない"
    post = [y for y in sorted(jp) if f"{y}-12-31" >= start and y <= end_year][:10]
    if not post:
        return None, [], "施行後の年の観測がまだ無い" if start_year >= COVID_START or end_year == 9999 else "施行が2019年末より後で、コロナ前の窓が取れない"
    need = [pre[max(0, len(pre) - 5)], pre[-1], *post]
    countries = [c for c in candidates if all(y in oecd.get(c, industry, "LR") for y in need)]
    if len(countries) < 3:
        return None, countries, "窓の年の観測がそろう比較国が3か国に満たない"
    return recompute(oecd, industry, start, end_year, countries), countries, ""


def build() -> list[dict[str, str]]:
    oecd = Oecd(OECD)
    enforcement = {r["id"]: r for r in _read(ENFORCEMENT)}
    ai = {r["id"]: r["分野"] for r in _read(AI_LABELS)}
    agreement = {r["id"]: r.get("結果", "") for r in _read(AGREEMENT)}
    covid = {r["id"]: r for r in _read(COVID_LABELS) if r["コロナ対応"] == "はい"}
    laws = [law for law in _read(OUTCOMES) if law["結果"] not in SKIP]
    picks = align_by_title(
        {law["id"]: publication_field(law["分野"], ai.get(law["id"], ""), agreement.get(law["id"])) for law in laws},
        {law["id"]: law["題名"] for law in laws},
    )
    picks = apply_sector_overrides(picks, _read(SECTOR_OVERRIDES))
    rows = []
    for law in laws:
        dated = enforcement.get(law["id"], {})
        start, start_origin = dated.get("施行日", ""), "台帳"
        if not start and dated.get("公布日", ""):
            start, start_origin = dated["公布日"], ESTIMATED
        field, origin, industry = picks[law["id"]]
        row = {"id": law["id"], "題名": law["題名"], "分野": field, "分野の由来": origin, "産業": industry, "施行日": start,
               "施行日の由来": start_origin if start else "", "窓": "", "中央値": "", "第1四分位": "", "第3四分位": "", "比較国": "", "計算式の要素": "", "結果": "理由", "理由": ""}
        if not start:
            row["理由"] = "施行日も公布日も未取得"
            rows.append(row)
            continue
        if law["id"] in covid:
            row["理由"] = COVID_REASON.format(kind=covid[law["id"]]["種類"])
            rows.append(row)
            continue
        result, countries, why = amount(oecd, industry, start)
        if result is None:
            row["理由"] = why or "計算できない"
            rows.append(row)
            continue
        nominal = round(result["base_nominal_million"])
        row.update({
            "窓": f"{result['years'][0]}〜{result['years'][-1]}年", "中央値": str(result["median"]),
            "第1四分位": str(result["low"]), "第3四分位": str(result["high"]), "比較国": "・".join(countries), "結果": "額",
            "計算式の要素": (f"OECD 表6 JPN {INDUSTRY_LABEL[industry]}（{industry}）LR、比較国：{len(countries)}か国（{'・'.join(countries)}）、"
                         f"開始前最後の年（{result['base_year']}年）の名目付加価値 {nominal}百万円"),
        })
        rows.append(row)
    return rows


def main() -> int:
    rows = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(Counter(r["結果"] for r in rows), Counter(r["分野の由来"] for r in rows if r["結果"] == "額"))
    print(Counter(r["理由"] for r in rows if r["結果"] == "理由").most_common(6))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
