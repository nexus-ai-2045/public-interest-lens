#!/usr/bin/env python3
"""証券取引等監視委員会「活動状況」（年次報告）の附属資料から、勧告件数と告発件数を取る（便益ルール D7）。

出力: data/acquired/benefit-data/sesc_actions.csv（系列,区分,年,値,単位,出典URL,備考）
      data/acquired/benefit-data/sesc_status.csv（版ごとの取得状況と理由）
原本: .local/benefit-data/raw/sesc/（git 管理外）

取るもの（年は年度。版＝各年の活動状況に付く附属資料）:
  - 「勧告実施件数一覧表」: 勧告件数、行政処分に関する勧告、課徴金納付命令に関する勧告の、その版の年度の件数。
    表は「平成4〜令和元年度の合計＋以降の各年度＋全体の合計」の形で、列の和が合計に一致するときだけ採る。
    その版の年度は表の見出しの最後の年から決める。
  - 「告発件数等一覧表」: 見出しの年の数と値の数が一致するときの告発件数・告発人数。
取れないもの: 平成4〜令和元年度の年ごとの件数は最新版の表では合計1つにまとまっており、各年の版から現年度の値だけを集める。
版が見つからない年度・表の形が違う版は取得できずとする。
"""
from __future__ import annotations

import html
import re
import sys
import unicodedata
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import benefit_fetch as bf  # noqa: E402

SITE = "https://www.fsa.go.jp"
OUT = bf.OUT_DIR / "sesc_actions.csv"
STATUS = bf.OUT_DIR / "sesc_status.csv"
ERA_BASE = {"平成": 1988, "令和": 2018}
TARGET_ROWS = ("勧告件数", "行政処分に関する勧告", "課徴金納付命令に関する勧告")


# ---------- 純粋関数 ----------

def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def report_pages(page_html: str) -> list[tuple[str, str]]:
    """年次公表等のページから、活動状況のページの(URL, リンク文字)を返す。"""
    out = []
    for h, x in re.findall(r'href="([^"]*/sesc/reports/[^"]+\.html)"[^>]*>\s*([^<]{0,120})', page_html):
        if "活動状況" in x and h not in [o[0] for o in out]:
            out.append((h, html.unescape(x.strip())))
    return out


def pdf_links(page_html: str) -> list[tuple[str, str]]:
    out = []
    for h, x in re.findall(r'href="([^"]+\.pdf)"[^>]*>\s*([^<]{0,60})', page_html):
        out.append((h, x.strip()))
    return out


def era_years(tokens: list[str]) -> list[int | None]:
    """「令和元」「令和2」「3」のような並びを、前の元号を引き継いで西暦にする。"""
    out: list[int | None] = []
    era = None
    for t in tokens:
        m = re.fullmatch(r"(平成|令和)?(元|\d+)", nfkc(t).replace("～", ""))
        if not m:
            out.append(None)
            continue
        era = m.group(1) or era
        if era is None:
            out.append(None)
            continue
        n = 1 if m.group(2) == "元" else int(m.group(2))
        out.append(ERA_BASE[era] + n)
    return out


def parse_kankoku(text: str) -> tuple[int | None, dict[str, tuple[int, int]], str]:
    """勧告実施件数一覧表。(その版の年度, {行: (現年度の値, 合計)}, 取れない理由)。"""
    lines = [nfkc(ln).strip() for ln in text.splitlines()]
    start = next((i for i, ln in enumerate(lines) if "勧告実施件数一覧表" in ln and "···" not in ln and "・・" not in ln), None)
    if start is None:
        return None, {}, "勧告実施件数一覧表が無い"
    rows: dict[str, tuple[int, int]] = {}
    header: list[str] = []
    for ln in lines[start + 1:start + 60]:
        m = re.match(r"^(" + "|".join(TARGET_ROWS) + r")((?:\s+\d{1,3}(?:,\d{3})*)+)$", ln)
        if m:
            vals = [int(v.replace(",", "")) for v in m.group(2).split()]
            if len(vals) >= 3 and sum(vals[:-1]) == vals[-1]:
                rows[m.group(1)] = (vals[-2], vals[-1])
            continue
        if not rows and not ln.startswith("(単位") and not ln.startswith("（単位"):
            header.append(ln)
    # 最後の年（見出しの最後の数字）とその元号
    era = None
    last = None
    for t in " ".join(header).replace("～", " ").split():
        if t in ("平成", "令和"):
            era = t
        m = re.fullmatch(r"(平成|令和)?(元|\d+)", t)
        if m:
            era = m.group(1) or era
            last = (era, 1 if m.group(2) == "元" else int(m.group(2)))
    fy = ERA_BASE[last[0]] + last[1] if last and last[0] else None
    if not rows:
        return fy, {}, "対象の行が無い、または列の和が合計と一致しない"
    if fy is None:
        return None, rows, "表の見出しから年度を決められない"
    return fy, rows, ""


def parse_kokuhatsu(text: str) -> tuple[list[tuple[str, int, int]], str]:
    """告発件数等一覧表。(区分, 年度, 値) と取れない理由。"""
    lines = [nfkc(ln).strip() for ln in text.splitlines()]
    start = next((i for i, ln in enumerate(lines) if "告発件数等一覧表" in ln and "···" not in ln), None)
    if start is None:
        return [], "告発件数等一覧表が無い"
    years: list[int | None] = []
    out: list[tuple[str, int, int]] = []
    for ln in lines[start + 1:start + 14]:
        toks = ln.split()
        if toks and all(re.fullmatch(r"(?:平成|令和)(?:元|\d+)", t) for t in toks):
            years = era_years(toks)
            continue
        m = re.match(r"^(告発件数|告発人数)((?:\s+\d+)+)$", ln)
        if m and years and None not in years:
            vals = [int(v) for v in m.group(2).split()]
            if len(vals) == len(years):
                out += [(m.group(1), y, v) for y, v in zip(years, vals)]
    if not out:
        return [], "年の見出しと値の数が一致する行が無い"
    return out, ""


# ---------- 取得 ----------

def get_text(url: str) -> str:
    import time
    req = urllib.request.Request(url, headers={"User-Agent": bf.USER_AGENT})
    time.sleep(bf.INTERVAL)
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")


def scan_pdf(path: Path) -> tuple[str, str]:
    """2つの表を含むページを探し、そのページの文字列だけを返す。

    大きなPDF（数十MB）を pdfplumber で全頁読むと遅いので、先に pypdfium2 で頁ごとの文字列を
    軽く読み、キーワードを含む頁だけ pdfplumber で取り直す（取り直した文字列だけを表の解析に使う）。
    """
    import pdfplumber
    import pypdfium2
    hits: dict[str, int] = {}
    doc = pypdfium2.PdfDocument(str(path))
    try:
        for i in range(len(doc)):
            page = doc[i]
            tp = page.get_textpage()
            flat = nfkc(tp.get_text_range())
            tp.close()
            page.close()
            for key in ("勧告実施件数一覧表", "告発件数等一覧表"):
                if key not in hits and key in flat and "\u00b7\u00b7\u00b7" not in flat:
                    hits[key] = i
            if len(hits) == 2:
                break
    finally:
        doc.close()
    out = {}
    if hits:
        with pdfplumber.open(path) as pdf:
            for key, i in hits.items():
                out[key] = pdf.pages[i].extract_text() or ""
    return out.get("勧告実施件数一覧表", ""), out.get("告発件数等一覧表", "")


def main() -> int:
    rows: list[list] = []
    status: list[list] = []
    seen_pages: set[str] = set()
    for year in range(2026, 2010, -1):
        page_url = f"{SITE}/sesc/houdou/{year}others.html"
        try:
            page_html = get_text(page_url)
        except Exception as exc:  # noqa: BLE001
            status.append([f"{year}年の年次公表等ページ", "取得できず", str(exc), page_url])
            continue
        for href, label in report_pages(page_html):
            if href in seen_pages:
                continue
            seen_pages.add(href)
            rurl = SITE + href if href.startswith("/") else href
            try:
                rhtml = get_text(rurl)
            except Exception as exc:  # noqa: BLE001
                status.append([label, "取得できず", str(exc), rurl])
                continue
            pdfs = [p for p in pdf_links(rhtml) if "附属" in p[1]] or [p for p in pdf_links(rhtml) if "全体" in p[1] or "全文" in p[1]]
            if not pdfs:
                status.append([label, "取得できず", "附属資料のPDFへのリンクが無い", rurl])
                continue
            purl = SITE + pdfs[0][0] if pdfs[0][0].startswith("/") else pdfs[0][0]
            dest, st = bf.fetch("sesc", purl, Path(purl).name)
            if st != 200:
                status.append([label, "取得できず", f"HTTP {st}", purl])
                continue
            kan, kok = scan_pdf(dest)
            fy, got, why = parse_kankoku(kan) if kan else (None, {}, "勧告実施件数一覧表のページが見つからない")
            if got and fy:
                for name, (cur, total) in got.items():
                    rows.append(["証券取引等監視委員会の勧告件数", name, fy, cur, "件", purl,
                                 f"{label}の附属資料。その版の年度の列。列の和＝合計{total}を確認"])
                status.append([label, "取得", f"勧告 {fy}年度 {len(got)}行", purl])
            else:
                status.append([label, "取得できず", f"勧告: {why}", purl])
            items, why2 = parse_kokuhatsu(kok) if kok else ([], "告発件数等一覧表のページが見つからない")
            for name, y, v in items:
                rows.append(["証券取引等監視委員会の告発", name, y, v, "件" if name == "告発件数" else "人", purl,
                             f"{label}の附属資料。年度。版により重なる年度がある"])
            status.append([label, "取得" if items else "取得できず", f"告発 {len(items)}行" if items else f"告発: {why2}", purl])
    status.append(["平成4年度〜平成22年度ごとの勧告・告発件数", "取得できず",
                   "年次公表等のページは2011年（平成23年）以降の版しか載せていない。最新版の表では平成4〜令和元年度は合計1つにまとまっている",
                   f"{SITE}/sesc/houdou/others.html"])
    bf.write_csv(OUT, ["系列", "区分", "年", "値", "単位", "出典URL", "備考"], rows)
    bf.write_csv(STATUS, ["対象", "状況", "内容", "出典URL"], status)
    print(len(rows), "rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
