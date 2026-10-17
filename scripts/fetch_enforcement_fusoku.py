#!/usr/bin/env python3
"""施行日が空欄の評価対象法について、現行法令の附則（施行期日の条）から施行日を補う。

入力:  data/acquired/enforcement-dates/enforcement.csv（scripts/fetch_enforcement_dates.py の出力）
出力:  同 enforcement.csv（施行日が空欄の行だけ埋める。確定済みの施行日は変えない）
       同 manifest.csv（取得した XML の sha256 を追記）
       docs/reports/enforcement-dates.md
原本: .local/enforcement-fusoku/raw/*.xml（git 管理外）

方針:
- 改正対象の現行法令（enforcement.csv の出典URLにある law_revisions の法令ID）の本文 XML を
  e-Gov 法令 API v2 の law_file/xml/{法令ID} で取る。
- XML の SupplProvision のうち AmendLawNum が当該改正法の法令番号に一致するものを探し、
  施行期日の条（通常は第一条）の文を読む。新規の法律は AmendLawNum を持たない最初の附則を読む。
- 本文に明示の日があればその日、「公布の日」なら公布日、「公布の日から起算して〇を経過した日」なら計算、
  「政令で定める日」なら空欄（備考に未確定と書く）。ただし書や各号の日は候補に回す。
- 文を解釈できないときは空欄のまま原文だけ残す。推測では埋めない。
"""
from __future__ import annotations

import csv
import hashlib
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://laws.e-gov.go.jp/api/2/"
USER_AGENT = "public-interest-lens/1.0 (enforcement-fusoku; research use)"
INTERVAL = 1.1

OUT_DIR = ROOT / "data/acquired/enforcement-dates"
ENFORCEMENT = OUT_DIR / "enforcement.csv"
MANIFEST = OUT_DIR / "manifest.csv"
RAW_DIR = ROOT / ".local/enforcement-fusoku/raw"
REPORT = ROOT / "docs/reports/enforcement-dates.md"

ERAS = {"明治": (1, 1867), "大正": (2, 1911), "昭和": (3, 1925), "平成": (4, 1988), "令和": (5, 2018)}
DIGITS = "〇一二三四五六七八九"
NUM = r"[元〇一二三四五六七八九十百]+"
MANIFEST_COLS = ["url", "local_path", "sha256", "http_status", "bytes", "fetched_at"]
NEW_COL = "施行期日の原文"
DECREE_NOTE = "政令で定める日（未確定）"
CAND_COL = "施行日の候補（; 区切り）"

DATE_RE = re.compile(rf"(明治|大正|昭和|平成|令和)({NUM})年({NUM})月({NUM})日")
PERIOD_UNIT = rf"(?:({NUM})年)?(?:({NUM})(?:月|箇月|か月|ヶ月|カ月))?(?:({NUM})日)?"
RELATIVE_RE = re.compile(rf"公布の日から(?:起算して)?{PERIOD_UNIT}を経過した日")


# ---------- 純粋関数 ----------

def kanji_num(text: str) -> int:
    """漢数字を整数にする。十・百を使う書き方（二十五）と位取り（二五）の両方を読む。"""
    text = text.strip()
    if text == "元":
        return 1
    if text.isdigit():
        return int(text)
    if not text or any(ch not in DIGITS + "十百" for ch in text):
        raise ValueError(text)
    if "十" in text or "百" in text:
        total, current = 0, 0
        for ch in text:
            if ch in "百十":
                total += (current or 1) * (100 if ch == "百" else 10)
                current = 0
            else:
                current = DIGITS.index(ch)
        return total + current
    return int("".join(str(DIGITS.index(ch)) for ch in text))


def era_to_iso(era: str, year: int, month: int, day: int) -> str | None:
    """和暦の年月日を YYYY-MM-DD にする。存在しない日付は None。"""
    try:
        return date(ERAS[era][1] + year, month, day).isoformat()
    except ValueError:
        return None


def find_dates(text: str) -> list[str]:
    """本文中の和暦の日付をすべて ISO にして出現順に返す（重複は除く）。"""
    out: list[str] = []
    for m in DATE_RE.finditer(text or ""):
        iso = era_to_iso(m.group(1), kanji_num(m.group(2)), kanji_num(m.group(3)), kanji_num(m.group(4)))
        if iso and iso not in out:
            out.append(iso)
    return out


def own_key(law_num: str) -> tuple[str, int, int] | None:
    """「平成十年法律第四号」や AmendLawNum「平成一〇年二月一八日法律第四号」を (元号, 年, 番号) にする。"""
    m = re.match(rf"(明治|大正|昭和|平成|令和)({NUM})年.*?法律第({NUM})号", law_num or "")
    if not m:
        return None
    return m.group(1), kanji_num(m.group(2)), kanji_num(m.group(3))


def add_period(iso: str, years: int, months: int, days: int) -> str | None:
    """年・月・日を足す。月を足して同じ日が無い月になるときは None（推測しない）。"""
    d = date.fromisoformat(iso)
    total = d.year * 12 + (d.month - 1) + years * 12 + months
    try:
        d = date(total // 12, total % 12 + 1, d.day)
    except ValueError:
        return None
    return (d + timedelta(days=days)).isoformat()


def parse_koryoku(body: str, rest: str, promulgation: str) -> dict:
    """施行期日の本文（body）と、ただし書・各号などの残り（rest）を読む。

    返り値: kind は date / promulgation / computed / decree / items / unparsed。
    date は主な施行日（空のことがある）、others は候補に回す日、notes は備考。
    """
    res = {"kind": "unparsed", "date": "", "others": [], "notes": []}
    body = body or ""
    rest = rest or ""
    main_dates = []
    if re.search(r"次の各号に掲げる", body) and not re.search(r"は、[^、]*から施行", body.split("次の各号")[0]):
        res["kind"] = "items"
        res["notes"].append("本文に単独の日がなく、各号の区分で施行（主な施行日は空欄）")
    else:
        m = re.search(r"は、(.+?)から施行(?:する|し)", body)
        x = re.sub(r"（[^（）]*）", "", m.group(1)) if m else ""  # 「（以下「施行日」という。）」を外す
        dm = DATE_RE.fullmatch(x)
        rm = RELATIVE_RE.fullmatch(x)
        if dm:
            iso = era_to_iso(dm.group(1), kanji_num(dm.group(2)), kanji_num(dm.group(3)), kanji_num(dm.group(4)))
            if iso:
                res.update(kind="date", date=iso)
                main_dates.append(iso)
        elif x == "公布の日":
            res.update(kind="promulgation", date=promulgation)
            main_dates.append(promulgation)
        elif "政令で定める日" in x:
            res["kind"] = "decree"
            res["notes"].append(DECREE_NOTE)
        elif rm and any(rm.groups()):
            y, mo, dd = (kanji_num(g) if g else 0 for g in rm.groups())
            iso = add_period(promulgation, y, mo, dd) if promulgation else None
            if iso:
                res.update(kind="computed", date=iso)
                res["notes"].append("公布日から起算して経過した日として計算（公布日に期間を足した日）")
                main_dates.append(iso)
            else:
                res["notes"].append("公布日に期間を足した日が存在しないため計算しない")
        if res["kind"] == "unparsed":
            res["notes"].append("施行期日の文を解釈できないため空欄")
    # ただし書・各号に出てくる日は候補にする
    for d in find_dates(rest if res["kind"] != "items" else body + rest):
        if d not in main_dates and d not in res["others"]:
            res["others"].append(d)
    if promulgation and re.search(r"公布の日(?!から起算)", rest if res["kind"] != "items" else body + rest):
        if promulgation not in main_dates and promulgation not in res["others"]:
            res["others"].append(promulgation)
    if re.search(r"政令で定める日", rest) and res["kind"] != "decree":
        res["notes"].append("ただし書または各号に政令で定める日あり（未確定）")
    return res


# ---------- XML ----------

SKIP_TAGS = {"Rt", "ArticleCaption", "ArticleTitle"}


def text_of(el: ET.Element) -> str:
    """要素の文字列（ふりがな Rt と見出しは除く）。号・項の番号の後ろに全角空白を入れる。"""
    parts: list[str] = []

    def walk(e: ET.Element) -> None:
        if e.tag in SKIP_TAGS:
            return
        if e.text:
            parts.append(e.text)
        for c in e:
            walk(c)
            if c.tag in ("ParagraphNum", "ItemTitle", "SubitemTitle", "Subitem1Title") and parts:
                parts.append("　")
            if c.tail:
                parts.append(c.tail)

    walk(el)
    return re.sub(r"[ \t\r\n]+", "", "".join(parts))


def paragraph_parts(par: ET.Element) -> tuple[str, str]:
    """項を (文の本体, 号などの字句) にする。"""
    sentences = "".join(text_of(s) for s in par.findall("ParagraphSentence/Sentence"))
    items = "　".join(text_of(i) for i in par.findall("Item"))
    return sentences, items


def koryoku_article(sp: ET.Element) -> dict | None:
    """附則 sp から施行期日の条（または項）を取り出す。"""
    arts = [c for c in sp if c.tag == "Article"]
    pars: list[ET.Element] = []
    title = ""
    if arts:
        pick = None
        for a in arts:
            if "施行期日" in (a.findtext("ArticleCaption") or ""):
                pick = a
                break
        if pick is None and (arts[0].findtext("ArticleTitle") or "").strip() == "第一条":
            pick = arts[0]
        if pick is None:
            return None
        title = (pick.findtext("ArticleTitle") or "").strip()
        pars = pick.findall("Paragraph")
    else:
        pars = [c for c in sp if c.tag == "Paragraph"][:1]  # 条のない附則は最初の項だけが施行期日
        if not pars:
            return None
    if not pars:
        return None
    first, first_items = paragraph_parts(pars[0])
    body, proviso = first, ""
    m = re.search(r"ただし", first)
    if m:
        body, proviso = first[: m.start()], first[m.start():]
    others = [x for p in pars[1:] for x in paragraph_parts(p)]
    quote = "　".join(x for x in [title, first, first_items, *others] if x)
    return {"body": body, "rest": "　".join(x for x in [proviso, first_items, *others] if x), "quote": quote}


def find_provision(root: ET.Element, own: tuple[str, int, int], is_new_law: bool) -> list[ET.Element]:
    found = []
    for sp in root.iter("SupplProvision"):
        amend = sp.get("AmendLawNum")
        if is_new_law:
            if not amend:
                return [sp]
        elif amend and own_key(amend) == own:
            found.append(sp)
    return found


# ---------- 取得 ----------

class Fetcher:
    def __init__(self) -> None:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        self.last = 0.0
        self.known: dict[str, int] = {}
        with MANIFEST.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                self.known[row["url"]] = int(row["http_status"])

    def xml(self, law_id: str) -> tuple[str, int, bytes]:
        url = f"{API}law_file/xml/{law_id}"
        path = RAW_DIR / f"{law_id}.xml"
        if path.exists() and url in self.known:
            return url, 200, path.read_bytes()
        if self.known.get(url) == 404:
            return url, 404, b""
        body, status = b"", 0
        for attempt in range(4):
            wait = self.last + INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/xml"})
            try:
                with urllib.request.urlopen(req, timeout=90) as resp:
                    body, status = resp.read(), resp.status
                break
            except urllib.error.HTTPError as err:
                body, status = err.read(), err.code
                if status < 500:
                    break
            except (urllib.error.URLError, TimeoutError, OSError):
                body, status = b"", 0
            time.sleep(2 * (attempt + 1))
        if status == 0 or status >= 500:
            raise RuntimeError(f"fetch failed: {url}")
        if status == 200:
            path.write_bytes(body)
        row = [url, f"../enforcement-fusoku/raw/{law_id}.xml" if status == 200 else "", hashlib.sha256(body).hexdigest(),
               status, len(body), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
        with MANIFEST.open("a", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerow(row)
        self.known[url] = status
        return url, status, body


# 改称・統合された法令（題名では引けない）。題名に含まれる旧題名 -> 現行法令の法令ID。
# ID を取り違えても、附則の AmendLawNum が当該改正法の番号と一致したときだけ採るので誤った日は入らない。
RENAMED = {
    "エネルギーの使用の合理化に関する法律": ["354AC0000000049"],
    "短時間労働者の雇用管理の改善等に関する法律": ["405AC0000000076"],
    "貸金業の規制等に関する法律": ["358AC0000000032"],
    "証券取引法": ["323AC0000000025"],
    "金融先物取引法": ["323AC0000000025"],
    "出資の受入れ、預り金及び金利等の取締りに関する法律": ["329AC0000000195"],
    "株式会社企業再生支援機構法": ["421AC0000000063"],
    "空港整備法": ["331AC0000000080"],
    "債権譲渡の対抗要件に関する民法の特例等に関する法律": ["410AC0000000104"],
    "金融機関等による顧客等の本人確認等に関する法律": ["419AC0000000022"],
    "雇用対策法": ["341AC0000000132"],
    "労働者派遣事業の適正な運営の確保及び派遣労働者の就業条件の整備等に関する法律": ["360AC0000000088"],
    "石油代替エネルギーの開発及び導入の促進に関する法律": ["355AC0000000071"],
    "情報通信技術の活用による行政手続等に係る関係者の利便性の向上並びに行政運営の簡素化及び効率化を図るための行政手続等における情報通信の技術の利用に関する法律": ["414AC0000000151"],
    "金融サービスの利用者の利便の向上及び保護を図るための金融商品の販売等に関する法律": ["412AC0000000101"],
    "特定目的会社による特定資産の流動化に関する法律": ["410AC0000000105"],
    "株券等の保管及び振替に関する法律": ["413AC0000000075"],
    "通訳案内業法": ["324AC1000000210"],
    "電子署名に係る地方公共団体の認証業務に関する法律": ["414AC0000000153"],
}


def law_id_of(own: tuple[str, int, int]) -> str:
    return f"{ERAS[own[0]][0]}{own[1]:02d}AC0000000{own[2]:03d}"


def is_amending(title: str) -> bool:
    return re.fullmatch(r"(.+?)の一部を改正する(?:等の)?法律案?", title.strip()) is not None


def resolve_row(fetcher: Fetcher, row: dict) -> dict:
    """1行分。返り値は main/others/notes/quotes/urls/kinds/reason。"""
    own = own_key(row["法令番号"])
    out = {"results": [], "quotes": [], "urls": [], "reason": ""}
    if own is None:
        out["reason"] = "法令番号が読めない"
        return out
    new_law = not is_amending(row["題名"])
    ids = []
    for lid in re.findall(r"law_revisions/(\w+)", row["出典URL"]):
        if lid not in ids:
            ids.append(lid)
    if new_law and not ids:
        ids = [law_id_of(own)]
    if not new_law:
        for old, mapped in RENAMED.items():
            if old in row["題名"]:
                ids += [x for x in mapped if x not in ids]
    if not ids:
        out["reason"] = "改正対象の現行法令を特定できないため附則を読めない"
        return out
    notes_status = []
    for lid in ids:
        url, status, body = fetcher.xml(lid)
        if status != 200:
            notes_status.append(f"{lid}: 本文 XML を取得できない（HTTP {status}）")
            continue
        root = ET.fromstring(body)
        if new_law:
            num = own_key(root.findtext("LawNum") or "")
            if num != own:
                notes_status.append(f"{lid}: 法令番号が一致しないため読まない")
                continue
        sps = find_provision(root, own, new_law)
        if not sps:
            continue
        art = koryoku_article(sps[0])
        if art is None:
            out["urls"].append(url)
            notes_status.append(f"{lid}: 当該附則に施行期日の条が抽出されていない")
            continue
        law_title = root.findtext("LawBody/LawTitle") or lid
        res = parse_koryoku(art["body"], art["rest"], row["公布日"])
        res["law"] = law_title
        out["results"].append(res)
        out["quotes"].append((law_title, art["quote"]))
        out["urls"].append(url)
    if len(out["quotes"]) == 1:
        out["quotes"] = [out["quotes"][0][1]]
    else:
        out["quotes"] = [f"【{t}】{q}" for t, q in out["quotes"]]
    if not out["results"]:
        out["reason"] = "；".join(notes_status) if notes_status else "現行法令の附則に当該改正法の施行期日が残っていない"
    elif notes_status:
        out["extra"] = notes_status
    return out


def merge_row(row: dict, got: dict) -> dict:
    """既存行に取得結果を重ねる。確定済みの施行日は呼び出し側で除いてある。"""
    results = got["results"]
    old_cands = [c for c in row[CAND_COL].split(";") if c]
    if not results:
        if got["reason"] not in row["備考"]:
            row["備考"] = "；".join(x for x in [row["備考"], got["reason"]] if x)
        return row
    mains = sorted({r["date"] for r in results if r["date"]})
    cands = set(old_cands)
    notes: list[str] = []
    for r in results:
        cands.update(r["others"])
        notes.extend(n for n in r["notes"] if n not in notes)
    method = "施行期日条文（現行法令XMLの附則）"
    kinds = {r["kind"] for r in results}
    if len(mains) == 1 and all(r["date"] == mains[0] for r in results):
        row["施行日"] = mains[0]
        cands.discard(mains[0])
        if kinds == {"computed"}:
            method = "計算（施行期日条文：公布日＋期間）"
        if old_cands and mains[0] not in old_cands:
            notes.append("e-Gov 改正履歴の候補と本文の日が一致しない")
    elif len(mains) > 1:
        cands.update(mains)
        notes.append("改正対象ごとに本文の日が異なるため主な施行日は空欄")
    elif "decree" in kinds and len(kinds) == 1:
        method = "施行期日条文（政令で定める日）"
    if row["施行日"]:
        cands.discard(row["施行日"])
    row["取得方法"] = method
    row[CAND_COL] = ";".join(sorted(cands))
    prior = row["備考"] if old_cands else ""
    row["備考"] = "；".join(x for x in [*notes, *got.get("extra", []), "" if not prior else f"前段の記録: {prior}"] if x)
    row[NEW_COL] = " / ".join(got["quotes"])
    row["出典URL"] = ";".join(x for x in [row["出典URL"], *got["urls"]] if x)
    return row


# ---------- 実行・レポート ----------

def categorize(row: dict) -> str:
    if row["施行日"]:
        return "confirmed"
    if row["取得方法"].endswith("（政令で定める日）"):
        return "decree"
    return "cands" if row[CAND_COL] else "none"


def run(limit: int | None) -> int:
    with ENFORCEMENT.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames or [])
        rows = list(reader)
    if NEW_COL not in cols:
        cols.append(NEW_COL)
    for r in rows:
        r.setdefault(NEW_COL, "")
    fetcher = Fetcher()
    todo = [r for r in rows if not r["施行日"] and not r[NEW_COL]]
    if limit:
        todo = todo[:limit]
    for i, r in enumerate(todo, 1):
        got = resolve_row(fetcher, r)
        merge_row(r, got)
        print(f"[{i}/{len(todo)}] {r['id']} {r['題名'][:24]} -> {r['施行日'] or '-'} {r['取得方法']}", flush=True)
    with ENFORCEMENT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    write_report(rows)
    print(Counter(categorize(r) for r in rows))
    return 0


def write_report(rows: list[dict]) -> None:
    total = len(rows)
    cat = Counter(categorize(r) for r in rows)
    confirmed = [r for r in rows if r["施行日"]]
    by_method = Counter(r["取得方法"] for r in confirmed)
    gaps = [r for r in rows if not r["施行日"]]
    reasons: Counter = Counter()
    for r in gaps:
        if categorize(r) == "decree":
            continue
        tail = r["備考"].split("；")[-1] or "不明"
        key = re.sub(r"^[0-9A-Z]{15}: ", "", tail)
        key = re.sub(r"^[^：:]+: ", "（法律名）: ", re.sub(r"「[^」]*」", "「…」", key))
        reasons[key] += 1
    decree_rows = [r for r in rows if categorize(r) == "decree"]
    decree_cands = sum(1 for r in decree_rows if r[CAND_COL])
    mismatch = sum(1 for r in rows if "改正履歴の候補と本文の日が一致しない" in r["備考"])
    n_amend = sum(1 for r in rows if is_amending(r["題名"]))
    lines = [
        "# 成立法（評価対象）の施行日 取得結果",
        "",
        f"評価対象 {total} 本の施行日を取った結果。2段階で取っている。",
        "",
        "1. `scripts/fetch_enforcement_dates.py`: e-Gov 法令 API v2 の `law_revisions`（改正履歴）から取る。",
        "2. `scripts/fetch_enforcement_fusoku.py`: 1で空欄だった法律について、現行法令の本文 XML（`law_file/xml`）の附則から、当該改正法の施行期日の条を読んで補う。",
        "",
        "結果は `data/acquired/enforcement-dates/enforcement.csv`（列「施行期日の原文」に附則の施行期日の条をそのまま残す）、",
        "取得記録は同 `manifest.csv`（sha256 付き）。原本は `.local/enforcement-dates/raw/`（JSON）と `.local/enforcement-fusoku/raw/`（XML）に置き、git 管理外。",
        "",
        "## 件数",
        "",
        f"- 対象: {total} 本（題名が「〜の一部を改正する法律」の形のもの {n_amend} 本、それ以外 {total - n_amend} 本）",
        f"- 施行日を確定できた: {len(confirmed)} 本",
    ]
    for method, n in by_method.most_common():
        lines.append(f"  - {method}: {n} 本")
    lines += [
        f"- 政令で定める日（未確定）: {cat['decree']} 本（施行日は空欄。附則が「政令で定める日」としており、この表からは日が決まらない。うち {decree_cands} 本は前段の e-Gov 改正履歴に実際の施行日が候補として残っている）",
        f"- 候補はあるが主な施行日を決められず空欄: {cat['cands']} 本（各号の区分施行など、本文に単独の日がない）",
        f"- 取れなかった: {cat['none']} 本",
        "",
        "## 取れなかった理由",
        "",
    ]
    for key, n in reasons.most_common():
        lines.append(f"- {key}: {n} 本")
    lines += [
        "",
        "## 取り方と限界",
        "",
        "- 改正法は、題名の改正対象（現行法令）の本文 XML で、`SupplProvision` の `AmendLawNum` が当該改正法の法令番号に一致する附則を探し、施行期日の条（第一条または見出し「施行期日」の条）を読む。",
        "- 新規の法律は、その法律自身の最初の附則（`AmendLawNum` なし）を読む。",
        "- 本文に和暦の日があればその日、「公布の日」なら公布日、「公布の日から起算して〇を経過した日」なら公布日に期間を足した日（取得方法に「計算」と書く）。",
        "- 「政令で定める日」は空欄にし、備考に「政令で定める日（未確定）」と書く。実際の施行日は施行令などを別に引く必要がある。",
        "- ただし書や各号に別の日があるときは、本文の日を主な施行日とし、他は「施行日の候補」に入れる。本文に単独の日がない（各号による区分施行）ときは空欄。",
        "- 文言を解釈できないものは空欄のまま原文だけ残した。推測では埋めていない。",
        "- 現行の本文は抽出附則（`Extract=\"true\"`）を含み、廃止・全面改正された法令は引けない。そのため古い改正法ほど取れない。",
        "- 前段で確定した施行日は変えていない。前段の候補と本文の日が食い違うもの（段階施行で、本文の日が改正履歴の候補に含まれないもの）は備考に書いた。",
        f"  - 該当: {mismatch} 本",
        "- 題名から現行法令を引けない改称・統合された法令の一部は、現行法令の法令IDを `RENAMED` 表に手で入れて引いた。採るのは附則の `AmendLawNum` が当該改正法の番号に一致した場合だけなので、ID が違っても誤った日は入らない。",
        "- 「本文 XML を取得できない（HTTP 404）」は、改正対象または当該法律が廃止済みで現行法令として引けないもの。",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    return run(args.limit)


if __name__ == "__main__":
    sys.exit(main())
