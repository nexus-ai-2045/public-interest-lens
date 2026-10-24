"""施行日が空欄の行を、e-Gov 法令 API v2 の照合結果（ブラウザ経由で取得）で埋める（暫定値）。

入力: data/acquired/enforcement-dates/egov-fill/results.jsonl（1行1法律）
- 取得: クラウドから e-Gov に届かないため、ブラウザ（e-Gov のページ上の fetch）で法令 API v2 を引き、
  1法律ごとに次の2系統を集めた。原本のバイトは保存していない。結果ファイルの sha256 を manifest.csv に記録する。
  A（施行期日政令）: `keyword`（law_type=CabinetOrder）で法令番号を含み「施行」を含む文。
  B（改正履歴）: 改正法は題名の「〜の一部を改正する法律」の〜から現行法令を引き、`law_revisions` のうち
     amendment_law_num が法令番号に一致する版の施行日。新規法は法令番号で引き、初めの版の日。
  T: Bで引いた法令の XML から、当該法律の附則（改正法は AmendLawNum が一致する附則）の最初の条の文。

採る規則（推測で埋めない。既に施行日がある行は変えない）:
1. A の文に fetch_enforcement_decrees.decree_statements を当て、pick_decree_main で主な施行日が一つに決まり、
   B に同じ日があれば「2系統一致」として採る。B に版が無ければ（e-Gov の保持範囲外）、A だけで採る（従来の施行期日政令と同じ）。
   A と B が食い違う（B に期限内の日があり、A の日を含まない）ときは採らず、理由を書く。
2. 附則の文（台帳の原文、無ければ T）が「公布の日」「日付」「公布の日から起算して◯を経過した日」なら
   parse_koryoku でその日を置く。経過した日で応当日が無い月は、民法143条2項により月の末日で期間が満了するので翌月1日。
   衆議院の附則の種別（台帳）と e-Gov の附則の種別が食い違うときは採らない。
3. B の日は「施行日の候補」に入れ、apply_enforcement_year_window の規則（期限内でただ1つなら置く、
   公布日と期限が同じ年・同じ年度なら期限の日）を当てる。新規法は初めの版の日がただ1つなら置く。
4. それ以外は空欄のまま、理由を備考に書く。
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from scripts.apply_enforcement_webfetch import decree_deadline
from scripts.apply_enforcement_year_window import METHOD_CANDIDATE, METHOD_WINDOW, same_year
from scripts.fetch_enforcement_decrees import DATE_PAT, decree_statements, pick_decree_main, window_end
from scripts.fetch_enforcement_fusoku import (
    CAND_COL, NEW_COL, PERIOD_UNIT, add_period, find_dates, kanji_num, parse_koryoku,
)

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "acquired" / "enforcement-dates"
CSV_PATH = DIR / "enforcement.csv"
RESULTS = DIR / "egov-fill" / "results.jsonl"
MANIFEST = DIR / "manifest.csv"

API = "https://laws.e-gov.go.jp/api/2/"
MARK = "e-Gov 照合（ブラウザ経由）"
METHOD_BOTH = "施行期日政令と改正履歴が一致（2系統、ブラウザ経由の e-Gov、暫定値）"
METHOD_DECREE = "施行期日政令（e-Gov の政令の附則、ブラウザ経由、暫定値）"
METHOD_TEXT = "施行期日条文（e-Gov の附則、ブラウザ経由、暫定値）"
METHOD_ORIGINAL = "新規法令の初めの版（e-Gov 改正履歴、ブラウザ経由、暫定値）"
METHOD_SUB_BOTH = "施行令と施行規則の附則が一致（2系統、ブラウザ経由の e-Gov、暫定値）"
METHOD_SUB_ONE = "施行令または施行規則の附則（1文書、附則の期限内、ブラウザ経由の e-Gov、暫定値）"
SUB_RE = re.compile(rf"この(?:政令|省令|府令|規則)は、法の施行の日（({DATE_PAT})）から施行する")
METHOD_MONTH_END = "計算（公布日＋期間。応当日が無い月は民法143条2項で末日満了、翌日を施行日）"
TEXT_RE = re.compile(rf"公布の日から起算して{PERIOD_UNIT}を経過した日から施行")


def month_end_next(promulgation: str, text: str) -> str | None:
    """「公布の日から起算して◯月を経過した日」で応当日が無いとき、満了日（その月の末日）の翌日。"""
    m = TEXT_RE.search(re.sub(r"\s", "", text or ""))
    if not m or not promulgation or add_period(promulgation, *(kanji_num(g) if g else 0 for g in m.groups())):
        return None
    y, mo, d = (kanji_num(g) if g else 0 for g in m.groups())
    p = date.fromisoformat(promulgation)
    total = p.year * 12 + (p.month - 1) + y * 12 + mo + 1  # 満了月の翌月
    nxt = date(total // 12, total % 12 + 1, 1)
    return (nxt + timedelta(days=d)).isoformat()


def split_body(text: str) -> tuple[str, str]:
    t = re.sub(r"\s", "", text or "")
    t = re.sub(r"^【[^】]*】", "", t)
    t = re.sub(r"^(?:（[^）]*）)?第[一二三四五六七八九十百]+条", "", t)
    m = re.search(r"ただし", t)
    return (t[: m.start()], t[m.start():]) if m else (t, "")


LATER_RE = re.compile(rf"({DATE_PAT})又は(?:この法律の)?公布の日のいずれか遅い日|公布の日又は({DATE_PAT})のいずれか遅い日")


def original_ok(d: str, prom: str, end: str | None, body: str, row: dict, cands: list[str]) -> bool:
    """初めの版の日を施行日に使えるか。e-Gov は古い版を持たないことがあり、初めの版が後年の版になる"""
    if not prom or d < prom:
        return False
    if any(c != d for c in cands):
        return False  # 施行令・施行規則などの日と食い違う
    if end:
        return d <= end
    if "政令で定める日" in (body or "") or "政令で定める日" in row[NEW_COL]:
        return False  # 期限が読めない政令委任
    return date.fromisoformat(d) <= date.fromisoformat(prom) + timedelta(days=730)


def b_dates(res: dict) -> tuple[list[str], list[str]]:
    ex, orig = set(), set()
    for b in (res.get("B") or {}).values():
        ex |= set(b.get("ex") or []) | set(b.get("sch") or [])  # sch は未施行の改正の施行予定日
        if b.get("own"):
            orig |= set(b.get("orig") or [])
    return sorted(ex), sorted(orig)


def judge(row: dict, res: dict) -> dict:
    """返り値: date, method, cands, notes, quote, urls, reason。"""
    num, prom = row["法令番号"], row["公布日"]
    got = {"date": "", "method": "", "cands": [], "notes": [], "quote": "", "urls": [], "reason": ""}
    quote = row[NEW_COL] or (f"【e-Gov 附則】{res['T']}" if res.get("T") else "")
    if not row[NEW_COL] and res.get("T"):
        got["quote"] = f"【e-Gov 附則】{res['T']}"
    body, rest = split_body(quote)
    # 期限は本文（ただし書より前）が政令委任のときだけ使う。ただし書の期限を本文に当てない
    end = None
    if "政令で定める日" in body and prom:
        end = decree_deadline(body, prom) or window_end(body, prom)
    if not end and not body:
        m = re.search(r"期限 (\d{4}-\d{2}-\d{2})", row["備考"])
        end = m.group(1) if m else None
    ex, orig = b_dates(res)
    for lid in res.get("B") or {}:
        got["urls"].append(f"{API}law_revisions/{lid}")
    if res.get("A"):
        got["urls"].append(f"{API}keyword?keyword={num}&law_type=CabinetOrder")

    # 1. 施行期日政令（A）
    stmts = []
    for lid, title, _pos, text in res.get("A") or []:
        for st in decree_statements(text, num):
            stmts.append({**st, "law_id": lid, "title": title})
    d_a, why_a, notes_a = pick_decree_main(stmts, prom, end)
    got["notes"] += notes_a
    if d_a:
        inside = [d for d in ex if prom <= d <= (end or "9999")]
        src = "、".join(sorted({f"{s['title']}（{s['law_id']}）" for s in stmts if s["kind"] == "main" and s["date"] == d_a})[:3])
        if d_a in ex:
            got.update(date=d_a, method=METHOD_BOTH)
            got["notes"].append(f"政令の附則（{src}）が {d_a} を明示し、改正履歴の版の日にも {d_a} がある")
        elif inside:
            got["reason"] = f"政令の附則の日 {d_a} と改正履歴の期限内の日（{'、'.join(inside)}）が一致しない"
            got["cands"] += [d_a] + inside
            return got
        else:
            got.update(date=d_a, method=METHOD_DECREE)
            got["notes"].append(f"政令の附則（{src}）が {d_a} を明示（改正履歴は e-Gov の保持範囲外で版が無い）")
        return got
    if why_a:
        got["notes"].append(f"政令の附則: {why_a}")
    for s in stmts:
        if s["kind"] != "main" and s["date"] not in got["cands"]:
            got["cands"].append(s["date"])

    # 1b. 施行令・施行規則の制定時の附則「法の施行の日（日付）から施行する」（新規法だけ）
    subs = {}
    for item in res.get("C") or []:
        if len(item) < 4:
            continue
        lid, title, _num, text = item
        m = SUB_RE.search(text)
        if m:
            subs[f"{title}（{lid}）"] = find_dates(m.group(1))[0]
    sub_dates = sorted(set(subs.values()))
    if sub_dates:
        ok = [d for d in sub_dates if (not prom or d >= prom) and (not end or d <= end)]
        src = "、".join(subs)
        if len(sub_dates) > 1 or not ok:
            got["notes"].append(f"施行令・施行規則の附則の日が一つに決まらないか期限外（{src}: {'、'.join(sub_dates)}）")
            got["cands"] += [d for d in sub_dates if d not in got["cands"]]
        elif len(subs) >= 2:
            got.update(date=ok[0], method=METHOD_SUB_BOTH)
            got["notes"].append(f"{src} の附則がともに「法の施行の日（{ok[0]}）から施行する」")
            return got
        elif end:
            got.update(date=ok[0], method=METHOD_SUB_ONE)
            got["notes"].append(f"{src} の附則が「法の施行の日（{ok[0]}）から施行する」。附則の期限 {end} 以内")
            return got
        else:
            got["cands"].append(ok[0])
            got["notes"].append(f"{src} の附則に法の施行の日 {ok[0]}（1文書だけで期限も読めないため候補）")

    # 2. 附則の文から決まる日
    kind_ledger = "decree" if "政令で定める日" in (row[NEW_COL] or row["備考"]) else ""
    if body:
        later = LATER_RE.search(body)
        if later and prom:
            fixed = find_dates(later.group(1) or later.group(2))[0]
            got.update(date=max(fixed, prom), method=METHOD_TEXT)
            got["notes"].append(f"附則は {fixed} と公布の日のいずれか遅い日。公布日 {prom} と比べて遅い方")
            return got
        p = parse_koryoku(body, rest, prom)
        if p["kind"] in ("date", "promulgation", "computed") and p["date"]:
            if kind_ledger == "decree" and not row[NEW_COL].startswith("【e-Gov"):
                got["notes"].append("衆議院の附則は政令で定める日、e-Gov の附則は日が決まる形で食い違う")
            else:
                got.update(date=p["date"], method=METHOD_TEXT)
                got["notes"] += p["notes"]
                got["cands"] += [d for d in p["others"] if d != p["date"]]
                return got
        nxt = month_end_next(prom, body)
        if nxt:
            got.update(date=nxt, method=METHOD_MONTH_END)
            got["notes"].append("応当日が無い月のため、その月の末日で期間が満了し、翌日を施行日とした")
            return got
        got["cands"] += [d for d in p["others"] if d not in got["cands"]]

    # 3. 改正履歴の候補と年の確定
    got["cands"] += [d for d in ex if d not in got["cands"]]
    if not ex and len(orig) == 1 and original_ok(orig[0], prom, end, body, row, got["cands"]):
        got.update(date=orig[0], method=METHOD_ORIGINAL)
        got["notes"].append(f"e-Gov で当該法律の初めの版の施行日が {orig[0]}")
        return got
    if orig:
        got["cands"] += [d for d in orig if d not in got["cands"]]
    if end and prom:
        allc = {c for c in (row[CAND_COL] or "").split(";") if c} | set(got["cands"])
        inside = sorted(d for d in allc if prom < d <= end)
        if len(inside) == 1:
            got.update(date=inside[0], method=METHOD_CANDIDATE + "（e-Gov 照合、ブラウザ経由）")
            got["notes"].append(f"改正履歴などの候補のうち附則の期限（{end}）以内の日は {inside[0]} だけ")
            return got
        if same_year(prom, end):
            got.update(date=end, method=METHOD_WINDOW + "（e-Gov 照合、ブラウザ経由）")
            got["notes"].append(f"施行日は {prom} から {end} の間（同じ年・同じ年度）。年単位の判定のため期限の日を置いた")
            return got
    if not res.get("B"):
        got["reason"] = "改正対象・当該法令が e-Gov で見つからない（改称・廃止・保持範囲外）"
    elif not ex:
        got["reason"] = "改正履歴に当該法律の版が無い（e-Gov の保持範囲外、または版の統合）"
    elif end:
        got["reason"] = f"改正履歴の日（{'、'.join(ex)}）のうち附則の期限 {end} 以内の日が一つに絞れず、年も決まらない"
    else:
        got["reason"] = "附則の期限が読めず、改正履歴の日から一つに絞れない"
    if not stmts and res.get("A") is not None:
        got["reason"] += "。施行期日を明示した政令の附則も無い"
    return got


def merge(old: str, add: list[str]) -> str:
    parts = [p for p in (old or "").split("；") if p and not p.startswith(MARK)]
    return "；".join(parts + [a for a in add if a])


def apply(rows: list[dict], results: dict[str, dict]) -> dict:
    stats = {"filled": 0, "methods": {}, "reasons": {}}
    for row in rows:
        if row["施行日"] or row["id"] not in results:
            continue
        got = judge(row, results[row["id"]])
        cands = sorted({c for c in (row[CAND_COL] or "").split(";") if c} | set(got["cands"]) - {got["date"]})
        row[CAND_COL] = ";".join(cands)
        if got["quote"] and not row[NEW_COL]:
            row[NEW_COL] = got["quote"]
        if got["date"]:
            row["施行日"] = got["date"]
            row["取得方法"] = got["method"]
            row["備考"] = merge(row["備考"], [f"{MARK}: 施行日を確定（{got['method']}）"] + got["notes"])
            stats["filled"] += 1
            stats["methods"][got["method"]] = stats["methods"].get(got["method"], 0) + 1
        else:
            row["備考"] = merge(row["備考"], got["notes"] + [f"{MARK}: 確定できず。{got['reason']}"])
            stats["reasons"][got["reason"]] = stats["reasons"].get(got["reason"], 0) + 1
        urls = [u for u in got["urls"] if u not in row["出典URL"].split(";")]
        row["出典URL"] = ";".join(x for x in [row["出典URL"], *dict.fromkeys(urls)] if x)
    return stats


def main() -> None:
    raw = RESULTS.read_bytes()
    results = {}
    for line in raw.decode("utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            results[o["id"]] = o
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    stats = apply(rows, results)
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    rel = "egov-fill/results.jsonl"
    with MANIFEST.open(encoding="utf-8", newline="") as f:
        known = {r["local_path"] for r in csv.DictReader(f)}
    sha = hashlib.sha256(raw).hexdigest()
    if f"{rel}#{sha[:12]}" not in known:
        with MANIFEST.open("a", encoding="utf-8", newline="") as f:
            csv.writer(f, lineterminator="\n").writerow(
                [API + "（ブラウザ経由で keyword・laws・law_revisions・law_file）", f"{rel}#{sha[:12]}", sha, 200, len(raw),
                 datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")])
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    print(f"施行日あり {sum(1 for r in rows if r['施行日'])} / {len(rows)} 本")


if __name__ == "__main__":
    main()
