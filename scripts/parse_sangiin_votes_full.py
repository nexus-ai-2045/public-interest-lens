"""crawl_sangiin_votes_full.py が保存した原本から、議員ごとの賛否 CSV を作る。

出力（--out-dir）:
  votes_<回次>.csv  列: 回次,投票日,議案名,議員名,会派,賛否,出典URL
  summary.csv       議案ページごとの公表票数と、パースして数えた票数の突き合わせ
賛否は 賛成 / 反対 / 投票なし / 不明（賛成・反対・投票なしのどれにも当たらない行）。
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import sys
from pathlib import Path

BASE = "https://www.sangiin.go.jp/japanese/touhyoulist/"
DATE_RE = re.compile(r"第(\d+)回国会\s*(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
TITLE_RE = re.compile(r"案件名：\s*(.*?)\s*投票総数", re.S)
TOTAL_RE = re.compile(r"投票総数\s*(\d+)\s*賛成票\s*(\d+)\s*反対票\s*(\d+)")
TAG = re.compile(r"<[^>]+>")
ITEM_RE = re.compile(
    r'(?P<h4><h4 class="party">(?P<h4t>.*?)</h4>)'
    r'|(?P<cap><caption class="party">(?P<capt>.*?)</caption>)'
    r'|(?P<li><li class="giin">(?P<lit>.*?)</li>)'
    r'|(?P<cell><TD[^>]*class="(?P<ck>pro|con|nam)"[^>]*>(?P<cv>.*?)</TD>)',
    re.S | re.I,
)


def text(s: str) -> str:
    return " ".join(html.unescape(TAG.sub(" ", s)).replace("　", " ").split())


def name_of(s: str) -> str:
    return re.sub(r"\s+", "", html.unescape(TAG.sub("", s)).replace("　", ""))


def party_of(s: str) -> str:
    t = text(s)
    t = re.split(r"賛成票", t)[0].strip()
    return re.sub(r"\s*[(（]\s*\d+\s*名\s*[)）]\s*$", "", t).strip()


def modern_vote(li: str) -> str:
    def span(cls: str) -> str:
        m = re.search(rf'<span class="{cls}">(.*?)</span>(?=<span|$)', li, re.S)
        return text(m.group(1)) if m else ""

    if span("pros"):
        return "賛成"
    if span("cons"):
        return "反対"
    if 'class="novote"' in li:
        return "投票なし"
    return "不明"


def parse_page(raw: str) -> dict:
    flat = text(raw)
    md = DATE_RE.search(flat)
    mt = TITLE_RE.search(flat)
    mtot = TOTAL_RE.search(flat)
    party = ""
    pro = con = ""
    rows = []
    for m in ITEM_RE.finditer(raw):
        if m.group("h4"):
            party = party_of(m.group("h4t"))
        elif m.group("cap"):
            party = party_of(m.group("capt"))
        elif m.group("li"):
            li = m.group("lit")
            nm = re.search(r'<span class="names">(.*?)</span>\s*$', li, re.S)
            rows.append((party, name_of(nm.group(1)) if nm else "", modern_vote(li)))
        elif m.group("cell"):
            ck, cv = m.group("ck"), m.group("cv")
            if ck == "pro":
                pro = cv
            elif ck == "con":
                con = cv
            else:
                if "<img" in pro.lower() and "sansei" in pro.lower():
                    v = "賛成"
                elif "<img" in con.lower() and "hantai" in con.lower():
                    v = "反対"
                elif "投票なし" in cv:
                    v = "投票なし"
                else:
                    v = "不明"
                if name_of(cv):
                    rows.append((party, name_of(cv), v))
                pro = con = ""
    return {
        "date": f"{int(md.group(2)):04d}-{int(md.group(3)):02d}-{int(md.group(4)):02d}" if md else "",
        "kaiji": md.group(1) if md else "",
        "title": mt.group(1).strip() if mt else "",
        "total": tuple(int(x) for x in mtot.groups()) if mtot else None,
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path(".local/sangiin-votes-full"))
    ap.add_argument("--out-dir", type=Path, default=Path("data/acquired/sangiin-votes-full"))
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_root = args.root / "raw"
    summ = (args.out_dir / "summary.csv").open("w", newline="", encoding="utf-8")
    sw = csv.writer(summ)
    sw.writerow(["回次", "投票日", "議案名", "公表_投票総数", "公表_賛成", "公表_反対",
                 "集計_賛成", "集計_反対", "集計_投票なし", "集計_不明", "照合", "出典URL"])
    for kdir in sorted((p for p in raw_root.iterdir() if p.is_dir()), key=lambda p: int(p.name)):
        k = kdir.name
        out = (args.out_dir / f"votes_{k}.csv").open("w", newline="", encoding="utf-8")
        w = csv.writer(out)
        w.writerow(["回次", "投票日", "議案名", "議員名", "会派", "賛否", "出典URL"])
        n = 0
        for f in sorted(kdir.glob(f"{k}-*-v*.htm")):
            url = f"{BASE}{k}/{f.name}"
            pg = parse_page(f.read_text(encoding="utf-8", errors="replace"))
            for party, nm, v in pg["rows"]:
                w.writerow([k, pg["date"], pg["title"], nm, party, v, url])
            n += len(pg["rows"])
            c = {v: sum(1 for r in pg["rows"] if r[2] == v) for v in ("賛成", "反対", "投票なし", "不明")}
            t = pg["total"]
            ok = "OK" if t and (c["賛成"], c["反対"]) == (t[1], t[2]) and c["不明"] == 0 else "要確認"
            sw.writerow([k, pg["date"], pg["title"], t[0] if t else "", t[1] if t else "",
                         t[2] if t else "", c["賛成"], c["反対"], c["投票なし"], c["不明"], ok, url])
        out.close()
        print(k, n, flush=True)
    summ.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
