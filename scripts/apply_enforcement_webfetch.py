"""施行日が空欄の行を、クラウドから WebFetch で取った一次資料で補う（暫定値）。

入力: data/acquired/enforcement-dates/shugiin-fusoku-extract.json
- 「附則」: 衆議院「制定法律」の本文ページから、2系統（A・B）が別々に引用した附則の施行期日の条。
- 「省庁資料の候補」: 所管省庁の発表・通知に書かれた施行日の文（1回目の取得）。
- 「候補の再取得」: 別のエージェントが同じ URL を開き直して引用した文（2回目の取得）。

採る規則（推測で埋めない）:
1. 附則: A と B の本文（ただし書より前）が一致し、本文冒頭の「法律第◯号（平◯・◯・◯）」が法令番号・公布日と一致するときだけ、
   中黒は全角（U+30FB）と半角（U+FF65）を同じ区切りとする。元号・番号・年月日が違えば一致しない。
   fetch_enforcement_fusoku.parse_koryoku で読む。明示の日・公布の日・「公布の日から起算して◯を経過した日」（計算）だけを施行日にする。
   「政令で定める日」は施行日を空欄のまま、空だった「施行期日の原文」だけを埋める。
2. 省庁資料: 2回の取得で日付が一致し、文中の法律が対象と一致し、附則の「◯を超えない範囲内」に収まるときだけ施行日にする。
3. 既に施行日がある行は変えない。WebFetch は要約モデル経由で原本のバイトが無いため、取得方法に「暫定」と書く。
4. 施行日を新たに採用するときだけ、索引が今も不採用だと読ませる3つの句と、e-Gov 文の「一つに絞れない」を現在の備考から外す。
   外した事実は、現行の施行日を否定しない一文にする。「確定できず」と「無い」は残す。
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from scripts.fetch_enforcement_fusoku import (
    CAND_COL, NEW_COL, NUM, add_period, kanji_num, own_key, parse_koryoku,
)

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "acquired" / "enforcement-dates"
CSV_PATH = DIR / "enforcement.csv"
EXTRACT = DIR / "shugiin-fusoku-extract.json"

METHOD_FUSOKU = "衆議院 制定法律の附則（2系統一致、WebFetch 経由の暫定値）"
METHOD_FUSOKU_CALC = "計算（衆議院 制定法律の附則：公布日＋期間、2系統一致、WebFetch 経由の暫定値）"
METHOD_DECREE = "施行期日政令の省庁発表（2回取得で一致、WebFetch 経由の暫定値）"
# 全角中黒と半角中黒だけを同じ区切りにする。NFKC は全角括弧まで半角にし、見出しの形を壊す。
HEADER_DOT = r"[\u30fb\uff65]"
HEADER_RE = re.compile(rf"法律第({NUM})号（平({NUM}){HEADER_DOT}({NUM}){HEADER_DOT}({NUM})）")
WITHIN_RE = re.compile(rf"公布の日から起算して(?:({NUM})年)?(?:({NUM})(?:月|箇月|か月|ヶ月|カ月))?(?:({NUM})日)?を超えない範囲内")


def main_sentence(quote: str) -> tuple[str, str]:
    """引用から本文（ただし書より前）と残りを取り出し、見出し・条番号・括弧書きの注記を外す。"""
    q = (quote or "").replace("\n", "").replace("「", "").replace("」", "")
    q = re.sub(r"^(?:（施行期日）)?\s*(?:第一条|[１1])?\s*", "", q.strip())
    q = re.sub(r"\s+", "", q)
    m = re.search(r"から施行(?:する|し)[。、]", q)
    if not m:
        return "", q
    end = m.end()
    body = q[:end]
    rest = q[end:]
    rest = re.sub(r"（[^（）]*(?:WebFetch|引用|取得|要約|ページ)[^（）]*）", "", rest)
    return body, rest


def header_matches(header: str, law_num: str, promulgation: str) -> bool:
    m = HEADER_RE.search(re.sub(r"\s", "", header or ""))
    own = own_key(law_num)
    if not m or not own or own[0] != "平成":
        return False
    try:
        number, year, month, day = (kanji_num(g) for g in m.groups())
        y, mo, d = (int(x) for x in promulgation.split("-"))
    except ValueError:
        return False
    return number == own[2] and year == own[1] and (1988 + year, month, day) == (y, mo, d)


# 索引が施行日を空にした時点の句。採用後の備考へは残さない。似た否定や「確定できず」は対象にしない。
STALE_INDEX_NOTES = frozenset({
    "ページ冒頭の法律番号・公布日が台帳と合わないため使わない",
    "附則の施行期日の文を読めない",
    "各号ごとに施行（本則の施行日が1つに決まらない）",
})
STALE_EGOV_NARROWING = "附則の期限が読めず、改正履歴の日から一つに絞れない。"
PAST_INDEX_NOTE = "過去の索引転記で施行日を空にした記録は、現行の施行日を否定しない"


def remarks_after_adoption(previous: str) -> str:
    """採用するとき、上の句だけを外し、履歴の一文に替える。何も外さなければ文は増やさない。"""
    kept: list[str] = []
    dropped = False
    for part in (previous or "").split("；"):
        text = part.strip()
        if not text:
            continue
        if text in STALE_INDEX_NOTES:
            dropped = True
            continue
        if STALE_EGOV_NARROWING in text:
            text = text.replace(STALE_EGOV_NARROWING, "").strip()
            dropped = True
        if text:
            kept.append(text)
    if dropped and PAST_INDEX_NOTE not in kept:
        kept.append(PAST_INDEX_NOTE)
    return "；".join(kept)


def decree_deadline(fusoku: str, promulgation: str) -> str | None:
    m = WITHIN_RE.search(re.sub(r"\s", "", fusoku or ""))
    if not m or not promulgation:
        return None
    y, mo, d = (kanji_num(g) if g else 0 for g in m.groups())
    return add_period(promulgation, y, mo, d)


def judge_fusoku(row: dict, quotes: dict) -> dict | None:
    a, b = quotes.get("A"), quotes.get("B")
    if not a or not b:
        return None
    body_a, rest_a = main_sentence(a["fusoku_quote"])
    body_b, _ = main_sentence(b["fusoku_quote"])
    if not body_a or body_a != body_b:
        return None
    if not (header_matches(a["header"], row["法令番号"], row["公布日"]) and header_matches(b["header"], row["法令番号"], row["公布日"])):
        return None
    got = parse_koryoku(body_a, rest_a, row["公布日"])
    return {"parsed": got, "text": body_a + rest_a, "url": a["honbun_url"]}


def judge_candidate(row: dict, first: dict, second: dict | None) -> str | None:
    if not re.match(r"https?://[^/]*\.go\.jp[/:]", first.get("出典URL", "")):
        return None
    if not second or not second.get("fetched") or not second.get("law_matches"):
        return None
    if not first["施行日"] or first["施行日"] != second.get("date"):
        return None
    deadline = decree_deadline(row[NEW_COL], row["公布日"])
    if not deadline or not (row["公布日"] <= first["施行日"] <= deadline):
        return None
    return first["施行日"]


def apply(rows: list[dict], extract: dict) -> list[str]:
    log = []
    fus: dict[str, dict] = {}
    for q in extract["附則"]:
        fus.setdefault(q["id"], {})[q["系統"]] = q
    first = {c["id"]: c for c in extract["省庁資料の候補"]}
    second = {c["id"]: c for c in extract.get("候補の再取得", [])}
    for row in rows:
        if row["施行日"]:
            continue
        rid = row["id"]
        res = judge_fusoku(row, fus.get(rid, {}))
        if res:
            p = res["parsed"]
            filled = not row[NEW_COL]
            if filled:
                row[NEW_COL] = f"【衆議院 制定法律】{res['text']}"
            if p["kind"] in ("date", "promulgation", "computed") and p["date"]:
                row["施行日"] = p["date"]
                row["取得方法"] = METHOD_FUSOKU_CALC if p["kind"] == "computed" else METHOD_FUSOKU
                row["出典URL"] = res["url"]
                others = [d for d in p["others"] if d not in row[CAND_COL].split("; ")]
                if others:
                    row[CAND_COL] = "; ".join(filter(None, [row[CAND_COL], *others]))
                row["備考"] = "；".join(filter(None, ["衆議院 制定法律の附則で確定（2系統の引用が一致）", *p["notes"], remarks_after_adoption(row["備考"])]))
                log.append(f"{rid}: 附則で確定 {p['date']}（{p['kind']}）")
                continue
            if filled:
                log.append(f"{rid}: 附則の原文を補った（{p['kind']}、施行日は空欄のまま）")
        c = first.get(rid)
        if c:
            d = judge_candidate(row, c, second.get(rid))
            if d:
                row["施行日"] = d
                row["取得方法"] = METHOD_DECREE
                row["出典URL"] = c["出典URL"]
                row["施行期日の原文"] = f"{row[NEW_COL]}【省庁発表】{c['原文の引用']}"
                row["備考"] = "；".join(filter(None, ["省庁の発表で確定（2回の取得で日付が一致、附則の期間内）", remarks_after_adoption(row["備考"])]))
                log.append(f"{rid}: 省庁発表で確定 {d}")
            elif c["施行日"] not in row[CAND_COL]:
                row[CAND_COL] = "; ".join(filter(None, [row[CAND_COL], c["施行日"]]))
                row["備考"] = "；".join(filter(None, [f"候補 {c['施行日']}（{c['出典URL']}）は、公的機関の資料・2回目の取得・附則の期間のいずれかで確かめられず施行日に採らない", row["備考"]]))
                log.append(f"{rid}: 候補 {c['施行日']} に留めた")
    return log


def main() -> None:
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    log = apply(rows, json.loads(EXTRACT.read_text(encoding="utf-8")))
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for line in log:
        print(line)
    print(f"施行日あり {sum(1 for r in rows if r['施行日'])} / {len(rows)} 本")


if __name__ == "__main__":
    main()
