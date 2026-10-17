#!/usr/bin/env python3
"""施行日が空欄の評価対象法について、施行期日を定めた政令（または政令の附則）から施行日を補う。

入力:  data/acquired/enforcement-dates/enforcement.csv（fetch_enforcement_dates.py と fetch_enforcement_fusoku.py の出力）
出力:  同 enforcement.csv（施行日が空欄の行だけ埋める。確定済みの施行日は変えない）
       同 manifest.csv（取得した JSON / XML の sha256 を追記）
       docs/reports/enforcement-dates.md
原本: .local/enforcement-decrees/raw/*（git 管理外）

方針:
- 「〇〇法（平成X年法律第Y号）の施行期日を定める政令」は e-Gov の法令データには無い（効力を終えた政令は引けない）。
  代わりに e-Gov 法令 API v2 の全文検索（keyword）で、閣令（CabinetOrder）の中から、当該法律の法令番号と施行の日を
  同じ文に書いた附則を探す。施行令・整備政令の附則には、効力を終えた改正政令の附則が `Extract` として残っている。
- 採るのは次の文だけ。法令番号が一致し、日付が文中に明示されているもの。
    「この政令は、〇〇法（法令番号）の施行の日（平成…年…月…日）から施行する。」
  「…附則第一条第二号に掲げる規定の施行の日（日付）」は一部の規定の日なので施行日に採らず、候補に回す。
- 同じ法令番号について政令が互いに違う日を書いているとき、公布日より前の日、附則の「公布の日から起算して〇を
  超えない範囲内」を外れる日は採らず、空欄のまま理由を備考に書く。
- 政令で見つからないとき、当該改正法の改正履歴（law_revisions）で amendment_law_num が一致する版の日のうち、
  附則のただし書・各号に書かれた日を除いて一つに絞れ、附則の期間内にあるものだけを採る。絞れなければ空欄。
- 推測では埋めない。確かめられないものは空欄のまま、理由を備考に書く。
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fetch_enforcement_dates import to_kanji  # noqa: E402
from scripts.fetch_enforcement_fusoku import (  # noqa: E402
    API, CAND_COL, DATE_RE, DECREE_NOTE, ENFORCEMENT, INTERVAL, MANIFEST, NEW_COL, NUM, PERIOD_UNIT, REPORT,
    add_period, categorize, era_to_iso, find_dates, is_amending, kanji_num, own_key, parse_koryoku, text_of,
    write_report as write_fusoku_report,
)

USER_AGENT = "public-interest-lens/1.0 (enforcement-decrees; research use)"
RAW_DIR = ROOT / ".local/enforcement-decrees/raw"
RAW_REL = "../enforcement-decrees/raw/"
METHOD_DECREE = "施行期日政令"
METHOD_REV = "改正履歴（law_revisions）の amendment_law_num 一致"
MARK = "施行期日政令の照合"
REV_GUESS = "推定（改正履歴の期間内で一つだけ残る日。原文で未確認）"
ERA_RE = r"(?:明治|大正|昭和|平成|令和)"
DATE_PAT = rf"{ERA_RE}{NUM}年{NUM}月{NUM}日"
LAW_NUM_RE = re.compile(rf"{ERA_RE}{NUM}年法律第{NUM}号")
MAX_PAGES = 3
EVIDENCE_MAX = 3
CHECK_MAX = 8

# 理由（件数集計のため固定の語にする）
R_NO_DECREE = "施行期日政令は e-Gov に無く、施行令・整備政令の附則にも法令番号と日を明示した記載が見つからない"
R_PART_ONLY = "政令の附則が書いているのは一部の規定の施行日だけで、主な施行日を示す記載が無い"
R_CONFLICT = "政令の附則に互いに違う日が書かれており、一つに決められない"
R_OUT_OF_WINDOW = "政令の附則の日が公布日または附則の期間と合わない"
R_REPEALED = "改正対象または当該法律が廃止・改称されており、e-Gov の現行法令データから引けない"
R_ITEMS = "附則が各号で区分して施行日を定めており、主な施行日の記載が政令に見つからない"


# ---------- 純粋関数 ----------

def short_law_num(attr: str | None) -> str:
    """AmendLawNum「平成十年十月三十日政令第三百三十七号」や LawNum を「平成十年政令第三百三十七号」にする。"""
    m = re.match(rf"({ERA_RE})({NUM})年.*?(政令|法律|省令)第({NUM})号", attr or "")
    if not m:
        return (attr or "").strip()
    year, no = kanji_num(m.group(2)), kanji_num(m.group(4))
    return f"{m.group(1)}{'元' if year == 1 else to_kanji(year)}年{m.group(3)}第{to_kanji(no)}号"


def decree_statements(text: str, num: str) -> list[dict]:
    """政令の附則の文から、法令番号 num の法律の施行日を日付つきで書いた文を拾う。

    kind: main（法律全体の施行の日）/ part（附則の一部の号に掲げる規定の施行の日）/ combined（法律と一部の規定をまとめて書く）。
    「この政令は、…」の文で、num の直後に「の施行の日（日付）から施行する」が続くものだけ。
    法令番号が複数並ぶ文（他の法律も含む）は採らない。
    """
    out: list[dict] = []
    n = re.escape(num)
    pat = re.compile(
        rf"この政令は、(?P<pre>[^。]*?){n}(?:。[^）]*)?）(?P<mid>[^（）。]*?)の施行の日（(?P<d>{DATE_PAT})(?:。[^）]*)?）から施行する"
    )
    for m in pat.finditer(text or ""):
        pre, mid = m.group("pre"), m.group("mid")
        if "法律第" in pre or "政令第" in pre:
            continue
        dates = find_dates(m.group("d"))
        if not dates:
            continue
        if mid == "":
            kind = "main"
        elif mid.startswith("及び") and "附則" in mid:
            kind = "combined"
        elif mid.startswith("附則") and mid.endswith("に掲げる規定"):
            kind = "part"
        else:
            continue
        out.append({"kind": kind, "date": dates[0], "text": m.group(0)})
    return out


def enact_subject(enact: str, num: str) -> str | None:
    """制定文「内閣は、〇〇法（num）の施行に伴い、…」から法律名を取る。「の一部の施行」は None。"""
    m = re.search(rf"([^、。（）]+?)（{re.escape(num)}(?:。[^）]*)?）の施行に伴い", enact or "")
    return m.group(1) if m else None


def enact_decree_dates(enact: str, suppl_text: str, num: str) -> list[dict]:
    """整備政令のように制定文が法律（num）の施行に伴うと書き、附則が「〇〇法の施行の日（日付）から施行する」と書くもの。"""
    title = enact_subject(enact, num)
    if not title:
        return []
    out = []
    pat = re.compile(rf"この政令は、{re.escape(title)}の施行の日（(?P<d>{DATE_PAT})(?:。[^）]*)?）から施行する")
    for m in pat.finditer(suppl_text or ""):
        dates = find_dates(m.group("d"))
        if dates:
            out.append({"kind": "main", "date": dates[0], "text": m.group(0)})
    return out


def window_end(body: str, promulgation: str) -> str | None:
    """附則の「公布の日から起算して〇を超えない範囲内」「〇年〇月〇日までの間」の末日。読めなければ None。"""
    m = re.search(rf"公布の日から起算して{PERIOD_UNIT}を超えない範囲内", body or "")
    if m and any(m.groups()) and promulgation:
        y, mo, d = (kanji_num(g) if g else 0 for g in m.groups())
        return add_period(promulgation, y, mo, d)
    m = re.search(rf"({DATE_PAT})までの間", body or "")
    if m:
        found = find_dates(m.group(1))
        return found[0] if found else None
    return None


def referenced_law_num(body: str) -> str | None:
    """「この法律は、〇〇法（法令番号）の施行の日から施行する」の法令番号。"""
    m = re.search(rf"この法律は、[^、。]*?（({LAW_NUM_RE.pattern})(?:。[^）]*)?）の施行の日から施行する", body or "")
    return m.group(1) if m else None


def pick_decree_main(stmts: list[dict], promulgation: str, end: str | None) -> tuple[str, str, list[str]]:
    """政令の文（kind=main）から主な施行日を決める。返り値は (日, 空欄の理由, 備考)。"""
    mains = sorted({s["date"] for s in stmts if s["kind"] == "main"})
    notes: list[str] = []
    if not mains:
        return "", "", notes
    if len(mains) > 1:
        return "", R_CONFLICT, [f"政令が書く日: {'、'.join(mains)}"]
    d = mains[0]
    if promulgation and d < promulgation:
        return "", R_OUT_OF_WINDOW, [f"政令の日 {d} が公布日 {promulgation} より前"]
    if end and d > end:
        return "", R_OUT_OF_WINDOW, [f"政令の日 {d} が附則の期間の末日 {end} を超える"]
    return d, "", notes


def revision_dates(revs: dict, own: tuple[str, int, int]) -> list[str]:
    """law_revisions のうち amendment_law_num が当該改正法に一致する版の施行日（重複なし、昇順）。"""
    out = set()
    for r in revs.get("revisions", []) or []:
        num = r.get("amendment_law_num")
        if num and own_key(num) == own and r.get("amendment_enforcement_date"):
            out.add(r["amendment_enforcement_date"])
    return sorted(out)


def revision_main_date(dates: list[str], quote: str, promulgation: str) -> tuple[str, str]:
    """改正履歴の日から主な施行日を絞る。返り値は (日, 備考)。絞れなければ日は空で、備考に理由。

    附則が「公布の日から起算して〇を超えない範囲内において政令で定める日」を本文とし、
    ただし書・各号には明示の日（または公布の日）だけが書かれているとき、それらを除いて期間内に残る日が一つなら採る。
    """
    if not dates:
        return "", "改正履歴に当該改正法の版が無い"
    first = quote.split("　", 1)[-1] if quote.startswith("第") else quote
    m = re.search(r"ただし", first)
    body, rest = (first[: m.start()], first[m.start():]) if m else (first, "")
    if "次の各号に掲げる" in body:
        return "", "附則が各号の区分で施行日を定めている"
    res = parse_koryoku(body, rest, promulgation)
    if res["kind"] != "decree":
        return "", "附則本文が「政令で定める日」の形ではない"
    end = window_end(body, promulgation)
    if not end:
        return "", "附則の期間の末日を読めない"
    if re.search(r"政令で定める|法律で定める|経過した日|起算して|施行の日|施行の時|いずれか|別に", rest):
        return "", "ただし書・各号に政令などで定める別の日があり、改正履歴の日を本文の日と区別できない"
    explained = set(res["others"])
    remain = [d for d in dates if d not in explained and promulgation <= d <= end]
    if len(remain) != 1:
        return "", f"ただし書・各号の日を除いて期間内に残る日が{len(remain)}個で一つに絞れない（版の日: {'、'.join(dates)}）"
    note = f"改正履歴の版の日 {'、'.join(dates)} のうち、ただし書・各号に明示された日を除き附則の期間内に残る一つ"
    return remain[0], note


def merge_notes(old: str, drop_prefixes: tuple[str, ...], add: list[str]) -> str:
    parts = [p for p in old.split("；") if p and not p.startswith(drop_prefixes)]
    return "；".join(parts + [x for x in add if x])


# ---------- XML ----------

def scan_decree_xml(root: ET.Element, num: str) -> list[dict]:
    """政令の XML の附則（改正政令の抽出附則を含む）から decree_statements に当たる文を拾う。ref は政令の法令番号。"""
    own_ref = short_law_num(root.findtext("LawNum"))
    title = root.findtext("LawBody/LawTitle") or ""
    found = []
    for sp in root.iter("SupplProvision"):
        ref = short_law_num(sp.get("AmendLawNum")) if sp.get("AmendLawNum") else own_ref
        for st in decree_statements(text_of(sp), num):
            found.append({**st, "ref": ref, "title": title, "extract": bool(sp.get("AmendLawNum"))})
    return found


def scan_enact_xml(root: ET.Element, num: str) -> list[dict]:
    enact = text_of(root.find("LawBody/EnactStatement")) if root.find("LawBody/EnactStatement") is not None else ""
    title = root.findtext("LawBody/LawTitle") or ""
    ref = short_law_num(root.findtext("LawNum"))
    out = []
    for sp in root.iter("SupplProvision"):
        if sp.get("AmendLawNum"):
            continue
        for st in enact_decree_dates(enact, text_of(sp), num):
            out.append({**st, "ref": ref, "title": title, "extract": False})
    return out


# ---------- 取得 ----------

class Fetcher:
    def __init__(self) -> None:
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        self.last = 0.0
        self.known: dict[str, tuple[str, int]] = {}
        with MANIFEST.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh):
                rel = row["local_path"]
                if rel.startswith(RAW_REL) and (RAW_DIR / rel[len(RAW_REL):]).exists():
                    self.known[row["url"]] = (rel, int(row["http_status"]))
                elif row["http_status"] == "404":
                    self.known[row["url"]] = ("", 404)

    def get(self, path: str, params: dict | None, name: str, accept: str = "application/json") -> tuple[str, int, bytes]:
        url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
        if url in self.known:
            rel, status = self.known[url]
            return url, status, (RAW_DIR / rel[len(RAW_REL):]).read_bytes() if rel else b""
        body, status = b"", 0
        for attempt in range(4):
            wait = self.last + INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
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
        rel = RAW_REL + name if status == 200 else ""
        if status == 200:
            (RAW_DIR / name).write_bytes(body)
        row = [url, rel, hashlib.sha256(body).hexdigest(), status, len(body), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")]
        with MANIFEST.open("a", encoding="utf-8", newline="") as fh:
            csv.writer(fh, lineterminator="\n").writerow(row)
        self.known[url] = (rel, status)
        return url, status, body

    def json(self, path: str, params: dict | None, name: str) -> tuple[str, int, dict]:
        url, status, body = self.get(path, params, name)
        try:
            return url, status, json.loads(body.decode("utf-8")) if body else {}
        except ValueError:
            return url, status, {}

    def xml(self, law_id: str) -> tuple[str, int, ET.Element | None]:
        url, status, body = self.get(f"law_file/xml/{law_id}", None, f"{law_id}.xml", "application/xml")
        return url, status, ET.fromstring(body) if status == 200 and body else None

    def revisions(self, law_id: str) -> tuple[str, int, dict]:
        return self.json(f"law_revisions/{law_id}", None, f"revisions_{law_id}.json")

    def keyword(self, kw: str, page: int) -> tuple[str, int, dict]:
        key = hashlib.sha1(f"{kw}|{page}".encode("utf-8")).hexdigest()[:12]
        params = {"keyword": kw, "law_type": "CabinetOrder", "limit": 100, "offset": page * 100, "sentences_limit": 50}
        return self.json("keyword", params, f"keyword_{key}.json")

    def laws(self, params: dict) -> tuple[str, int, dict]:
        key = hashlib.sha1(json.dumps(params, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]
        return self.json("laws", params, f"laws_{key}.json")


def strip_tags(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def decree_evidence(fetcher: Fetcher, num: str) -> dict:
    """法令番号 num の施行日を書いた政令の附則を探す。返り値: stmts（検証済みの文）, urls, note。"""
    out: dict = {"stmts": [], "urls": [], "note": "", "total": 0}
    items: list[dict] = []
    for page in range(MAX_PAGES):
        url, status, data = fetcher.keyword(num, page)
        out["urls"].append(url)
        if status != 200:
            break
        items += data.get("items", [])
        out["total"] = data.get("total_count", 0)
        if (page + 1) * 100 >= out["total"]:
            break
    if out["total"] > MAX_PAGES * 100:
        out["note"] = f"政令の検索結果が{out['total']}件で先頭{MAX_PAGES * 100}件だけ確認"
    own_ids: list[str] = []
    extract_ids: list[str] = []
    for it in items:
        lid = it["law_info"]["law_id"]
        for s in it.get("sentences", []):
            t = strip_tags(s.get("text", ""))
            pos = s.get("position")
            if pos == "supplprovision" and decree_statements(t, num) or pos == "enactstatement" and enact_subject(t, num):
                if lid not in own_ids:
                    own_ids.append(lid)
            elif pos == "amendsupplprovision" and decree_statements(t, num):
                if lid not in extract_ids:
                    extract_ids.append(lid)
    cand_ids = (own_ids + [x for x in extract_ids if x not in own_ids])[:CHECK_MAX]
    seen = set()
    for lid in cand_ids:
        url, status, root = fetcher.xml(lid)
        out["urls"].append(url)
        if root is None:
            continue
        for st in scan_decree_xml(root, num) + scan_enact_xml(root, num):
            key = (st["ref"], st["kind"], st["date"])
            if key not in seen:
                seen.add(key)
                out["stmts"].append({**st, "law_id": lid})
    return out


# ---------- 行の処理 ----------

def law_ids_of(row: dict) -> list[str]:
    ids: list[str] = []
    for lid in re.findall(r"law_(?:revisions|file/xml)/(\w+)", row["出典URL"]):
        if lid not in ids:
            ids.append(lid)
    return ids


def split_quote(row: dict) -> str:
    return row[NEW_COL].split(" / 【政令")[0]


def resolve_row(fetcher: Fetcher, row: dict, cache: dict) -> dict:
    """1行分。返り値: date, method, cands, notes, quote, urls, reason。"""
    num = row["法令番号"]
    own = own_key(num)
    got: dict = {"date": "", "method": "", "cands": [], "notes": [], "quote": "", "urls": [], "reason": ""}
    if own is None:
        got["reason"] = R_NO_DECREE
        return got
    if num not in cache:
        cache[num] = decree_evidence(fetcher, num)
    ev = cache[num]
    got["urls"] += ev["urls"]
    if ev["note"]:
        got["notes"].append(ev["note"])
    quote = split_quote(row)
    body = quote.split("　", 1)[-1] if quote.startswith("第") else quote
    end = window_end(re.split(r"ただし", body)[0], row["公布日"])
    stmts = ev["stmts"]
    date, why, notes = pick_decree_main(stmts, row["公布日"], end)
    got["notes"] += notes
    if date:
        used = [s for s in stmts if s["kind"] == "main" and s["date"] == date]
        used.sort(key=lambda s: (s["extract"], s["ref"]))
        shown = used[:EVIDENCE_MAX]
        got.update(date=date, method=METHOD_DECREE)
        got["quote"] = " / ".join(f"【政令 {s['ref']}（{s['title']}）附則】{s['text']}" for s in shown)
        got["notes"].append("施行期日を定めた政令は e-Gov に無く、" + f"{len(used)}件の政令の附則（{'、'.join(s['ref'] for s in shown)}）が法令番号と日を明示")
    elif why:
        got["reason"] = why
    # 一部の規定の日は候補へ
    for s in stmts:
        if s["kind"] in ("part", "combined") and s["date"] != date and s["date"] not in got["cands"]:
            got["cands"].append(s["date"])
            what = "法律と一部の規定をまとめた施行日" if s["kind"] == "combined" else "一部の規定の施行日"
            got["notes"].append(f"政令の附則（{s['ref']}）に「{s['text'][:90]}」とあり、{s['date']}は{what}として候補")
    if not date and stmts and not why and all(s["kind"] != "main" for s in stmts):
        got["reason"] = R_PART_ONLY
    # 他の法律の施行の日に係る定め（この法律は、〇〇法の施行の日から施行する）
    if not date and not why:
        ref = referenced_law_num(body)
        if ref and ref != num:
            key = ref
            if key not in cache:
                cache[key] = decree_evidence(fetcher, ref)
            sub = cache[key]
            got["urls"] += sub["urls"]
            d2, why2, n2 = pick_decree_main(sub["stmts"], row["公布日"], None)
            if d2:
                used = sorted([s for s in sub["stmts"] if s["kind"] == "main" and s["date"] == d2], key=lambda s: (s["extract"], s["ref"]))[:EVIDENCE_MAX]
                got.update(date=d2, method=METHOD_DECREE)
                got["quote"] = " / ".join(f"【政令 {s['ref']}（{s['title']}）附則】{s['text']}" for s in used)
                got["notes"].append(f"附則が{ref}の施行の日から施行すると定めており、その法律の施行の日を政令の附則が明示")
    # 改正履歴
    if not got["date"]:
        revs_dates: dict[str, list[str]] = {}
        for lid in law_ids_of(row):
            url, status, revs = fetcher.revisions(lid)
            got["urls"].append(url)
            if status == 200:
                revs_dates[lid] = revision_dates(revs, own)
        alld = sorted({d for v in revs_dates.values() for d in v})
        if alld:
            picks = {revision_main_date(v, quote, row["公布日"]) for v in revs_dates.values() if v}
            ok = {p[0] for p in picks if p[0]}
            if len(ok) == 1 and all(p[0] for p in picks):
                # 期間内で一つだけ残る日は推定なので、施行日にせず候補に回す（原文で確認した日だけ使う）
                d, note = next(iter(picks))
                got["notes"].append(f"{REV_GUESS}。{note}")
                if d not in got["cands"]:
                    got["cands"].append(d)
                got["reason"] = REV_GUESS
            else:
                reasons = sorted({p[1] for p in picks if not p[0]})
                got["notes"].append("改正履歴で一つに絞れない: " + "／".join(reasons))
            for d in alld:
                if d != got["date"] and d not in got["cands"]:
                    got["cands"].append(d)
    if not got["date"] and not got["reason"]:
        got["reason"] = R_NO_DECREE
    return got


def apply_row(row: dict, got: dict) -> None:
    drop = (MARK, DECREE_NOTE) if got["date"] else (MARK,)
    old_cands = [c for c in row[CAND_COL].split(";") if c]
    cands = sorted(set(old_cands) | set(got["cands"]))
    if got["date"]:
        row["施行日"] = got["date"]
        row["取得方法"] = got["method"]
        cands = [c for c in cands if c != got["date"]]
        add = [f"{MARK}: 施行日を確定（{got['method']}）"] + got["notes"]
        if got["quote"]:
            row[NEW_COL] = f"{split_quote(row)} / {got['quote']}"
    else:
        add = got["notes"] + [f"{MARK}: 確定できず。{got['reason']}"]
    row[CAND_COL] = ";".join(cands)
    row["備考"] = merge_notes(row["備考"], drop, add)
    new_urls = [u for u in got["urls"] if u not in row["出典URL"].split(";")]
    row["出典URL"] = ";".join(x for x in [row["出典URL"], *dict.fromkeys(new_urls)] if x)


# ---------- 取得不可の再試行 ----------

def alt_law_ids(fetcher: Fetcher, row: dict) -> tuple[list[str], list[str]]:
    """取得不可の行について、別の題名・法令番号で現行法令を探す。返り値: (改正履歴に当該改正法の版を持つ法令ID, URL)。"""
    own = own_key(row["法令番号"])
    urls: list[str] = []
    found: list[str] = []
    if own is None:
        return found, urls
    title = row["題名"].removesuffix("案")
    stem = re.sub(r"の一部を改正する(?:等の)?法律$", "", title) if is_amending(row["題名"]) else title
    queries = []
    for q in dict.fromkeys([title, stem, stem.removesuffix("等"), stem[:10], stem[:6]]):
        if len(q) >= 5:
            queries.append({"law_title": q, "limit": 100})
    queries.append({"law_num": row["法令番号"], "limit": 5})
    checked: set[str] = set()
    for params in queries:
        url, status, data = fetcher.laws(params)
        urls.append(url)
        if status != 200:
            continue
        for item in data.get("laws", [])[:100]:
            lid = item["law_info"]["law_id"]
            if lid in checked or len(checked) >= 12:
                continue
            t = item.get("revision_info", {}).get("law_title", "")
            if params.get("law_title") and not (t.startswith(params["law_title"][:6]) or params["law_title"][:6] in t):
                continue
            checked.add(lid)
            rurl, rstatus, revs = fetcher.revisions(lid)
            urls.append(rurl)
            if rstatus == 200 and revision_dates(revs, own):
                found.append(lid)
    return found, urls


def retry_unavailable(fetcher: Fetcher, row: dict, cache: dict) -> dict:
    got = resolve_row(fetcher, row, cache)
    if got["date"]:
        return got
    ids, urls = alt_law_ids(fetcher, row)
    got["urls"] += urls
    if ids:
        own = own_key(row["法令番号"])
        dates = sorted({d for lid in ids for d in revision_dates(fetcher.revisions(lid)[2], own)})
        got["notes"].append(f"題名・法令番号を変えた検索で改正履歴に版を持つ法令を発見（{'、'.join(ids)}）。版の日: {'、'.join(dates)}")
        for d in dates:
            if d not in got["cands"]:
                got["cands"].append(d)
        got["reason"] = R_NO_DECREE
    else:
        got["notes"].append("別の題名（現行題名・「案」を除いた題名・題名の先頭）と法令番号でも e-Gov の現行法令または改正履歴に当該法律・改正法が見つからない")
        if got["reason"] == R_NO_DECREE:
            got["reason"] = R_REPEALED
    return got


# ---------- 実行・レポート ----------

SECTION_START = "<!-- decree-dates:start -->"
SECTION_END = "<!-- decree-dates:end -->"


def reason_of(row: dict) -> str:
    for part in row["備考"].split("；"):
        if part.startswith(MARK + ": 確定できず。"):
            return part[len(MARK + ": 確定できず。"):]
    return "照合未実施"


def write_report(rows: list[dict], before: dict) -> None:
    write_fusoku_report(rows)
    text = REPORT.read_text(encoding="utf-8")
    after_conf = [r for r in rows if r["施行日"]]
    filled_dec = [r for r in rows if r["取得方法"] == METHOD_DECREE]
    filled_rev = [r for r in rows if r["取得方法"] == METHOD_REV and MARK in r["備考"]]
    empty = [r for r in rows if not r["施行日"]]
    reasons = Counter(reason_of(r) for r in empty)
    n = len(rows)
    lines = [
        SECTION_START,
        "## 施行期日政令による補完（3段階目）",
        "",
        "`scripts/fetch_enforcement_decrees.py` で、施行日が空欄のまま残った行に、施行期日を定めた政令を当たった。",
        "",
        "| | 段階2の終わり | 段階3の後 |",
        "|---|---|---|",
        f"| 施行日あり | {before['confirmed']} 本 | {len(after_conf)} 本 |",
        f"| 施行日が空欄 | {before['empty']} 本 | {len(empty)} 本 |",
        f"| うち 附則が「政令で定める日」とする行 | {before['decree']} 本 | {sum(1 for r in empty if r['取得方法'].endswith('（政令で定める日）'))} 本 |",
        f"| うち 取得不可 | {before['none']} 本 | {sum(1 for r in empty if r['取得方法'] == '取得不可')} 本 |",
        "",
        f"- 政令の附則から補えた: {len(filled_dec)} 本（取得方法「{METHOD_DECREE}」）",
        f"- 改正履歴（law_revisions）から補えた: {len(filled_rev)} 本（取得方法「{METHOD_REV}」。備考に絞り込みの根拠を書いた）",
        f"- 空欄のまま: {len(empty)} 本（全 {n} 本中）",
        "",
        "### 取り方",
        "",
        "- 「〇〇法の施行期日を定める政令」そのものは e-Gov の法令データに無い（効力を終えた政令は引けない。`laws?law_title=施行期日を定める政令` は 0 件）。",
        "- そこで法令 API v2 の全文検索 `keyword` で、閣令（`law_type=CabinetOrder`）から、当該法律の法令番号を含む文を探した。施行令・整備政令の XML には、効力を終えた改正政令の附則が `Extract` として残っている。",
        "- 施行日に採るのは、法令番号が一致し日付が文中に書かれた次の形の文だけ（XML 本文で再確認し、原本を `.local/enforcement-decrees/raw/` に置いて sha256 を manifest.csv に追記）。",
        "  - 「この政令は、〇〇法（法令番号）の施行の日（平成…年…月…日）から施行する。」",
        "  - 制定文が「〇〇法（法令番号）の施行に伴い」とある整備政令で、附則が「〇〇法の施行の日（日付）から施行する」とあるもの。",
        "- 「附則第一条第二号に掲げる規定の施行の日（日付）」は一部の規定の日なので、施行日に採らず候補に入れた。",
        "- 政令どうしで日が食い違うもの、公布日より前の日、附則の「公布の日から起算して〇を超えない範囲内」を外れる日は採らない。",
        "- 政令に記載が無いときは、改正履歴のうち amendment_law_num が一致する版の日から、ただし書・各号に書かれた日を除いて附則の期間内に一つだけ残る場合に限り採った。",
        "- 附則が「この法律は、〇〇法（法令番号）の施行の日から施行する」とするものは、〇〇法の施行の日を同じ方法で確認して採った。",
        "- 取得不可の行は、現行題名・「案」を除いた題名・題名の先頭・法令番号で検索し直し、改正履歴に当該改正法の版を持つ法令を探した。",
        "- 備考の「施行期日政令の照合」に、確定した根拠、または確定できない理由を書いた。「施行期日の原文」には、採った政令の附則の文を `【政令 …】` で追記した。",
        "",
        "### 空欄のまま残った理由",
        "",
    ]
    for key, c in reasons.most_common():
        lines.append(f"- {key}: {c} 本")
    lines += [
        "",
        "限界: e-Gov の保持する政令は現行のものに限られ、効力を終えた施行期日政令や古い施行令の附則は引けない。",
        "官報などの別の原本は取っていない。確かめられない行は推測で埋めず空欄にした。",
        SECTION_END,
        "",
    ]
    block = "\n".join(lines)
    gaps = Counter(reason_of(r) for r in empty if categorize(r) in ("none", "cands"))
    head, sep, tail = text.partition("## 取れなかった理由\n\n")
    if sep:
        body, sep2, rest = tail.partition("\n## 取り方と限界")
        text = head + sep + "\n".join(f"- {k}: {c} 本" for k, c in gaps.most_common()) + "\n" + sep2 + rest
    text = text.replace("2段階で取っている。", "3段階で取っている。", 1)
    step3 = "\n3. `scripts/fetch_enforcement_decrees.py`: 2でも空欄だった行（附則が政令で定める日とするもの、取得不可）について、施行期日を定めた政令の附則と改正履歴から補う。"
    if step3.strip() not in text:
        text = text.replace("\n\n結果は `data/acquired/enforcement-dates/enforcement.csv`", step3 + "\n\n結果は `data/acquired/enforcement-dates/enforcement.csv`", 1)
    text = text.replace("`.local/enforcement-fusoku/raw/`（XML）に置き、git 管理外。", "`.local/enforcement-fusoku/raw/`・`.local/enforcement-decrees/raw/`（XML・JSON）に置き、git 管理外。", 1)
    text = text.replace("\n## 件数\n", "\n" + block + "\n## 件数\n", 1)
    REPORT.write_text(text, encoding="utf-8")


def run(limit: int | None, dry: bool) -> int:
    with ENFORCEMENT.open(encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        cols = list(reader.fieldnames or [])
        rows = list(reader)
    empty0 = [r for r in rows if not r["施行日"]]
    before = {
        "confirmed": len(rows) - len(empty0),
        "empty": len(empty0),
        "decree": sum(1 for r in empty0 if categorize(r) == "decree"),
        "none": sum(1 for r in empty0 if r["取得方法"] == "取得不可"),
    }
    fetcher = Fetcher()
    cache: dict = {}
    todo = empty0[:limit] if limit else empty0
    for i, r in enumerate(todo, 1):
        was_na = r["取得方法"] == "取得不可"
        got = retry_unavailable(fetcher, r, cache) if was_na else resolve_row(fetcher, r, cache)
        apply_row(r, got)
        print(f"[{i}/{len(todo)}] {r['id']} {r['題名'][:20]} -> {r['施行日'] or '-'} {r['取得方法'] if r['施行日'] else got['reason'][:30]}", flush=True)
    if dry:
        return 0
    with ENFORCEMENT.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    write_report(rows, before)
    print(Counter("filled" if r["施行日"] else "empty" for r in rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    return run(args.limit, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
