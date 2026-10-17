#!/usr/bin/env python3
"""国民生活センター 消費生活年報／全国の消費生活相談の状況（PIO-NET）から便益ルール D3 の数を取る。

出力: data/acquired/benefit-data/kokusen_pionet.csv（系列,区分,年,値,単位,出典URL,備考）
      data/acquired/benefit-data/kokusen_status.csv（取れた範囲と取れなかった理由）
原本: .local/benefit-data/raw/kokusen/（git 管理外）

取るもの（年は年度。PIO-NET の年度は4月〜翌年3月）:
  1. 表1 消費生活相談の年度別総件数（各版の掲載値を版ごとに残す。後の版で値が改訂されることがある）
  2. 契約購入金額・既支払金額の合計と平均（相談全体）。年報2016〜2022は図、2023〜2026年公表分は本文の文
  3. 上位25位の商品・役務等別の件数と平均既支払金額（年報2016〜2022の「相談の特徴」の表。名前と数が
     行として確実に対応した行だけ）
取れないもの: 2015年度より前の年報（公開されている最古は消費生活年報2016）、2022年度以降の商品・役務等別の
平均既支払金額（表の行が複数行に割れて対応を確定できない）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import benefit_fetch as bf  # noqa: E402

BASE = "https://www.kokusen.go.jp/"
OUT = bf.OUT_DIR / "kokusen_pionet.csv"
STATUS = bf.OUT_DIR / "kokusen_status.csv"
COLS = ["系列", "区分", "年", "値", "単位", "出典URL", "備考"]
ANNUAL = {y: f"pdf_dl/nenpou/{y}_nenpou.pdf" for y in range(2016, 2023)}
SUMMARY = {  # 公表年: (PDF, 本文のページ)
    2023: ("pdf/n-20230809_1.pdf", "news/data/n-20230809_1.html"),
    2024: ("pdf/n-20240807_3.pdf", "news/data/n-20240807_3.html"),
    2025: ("pdf/n-20250806_3.pdf", "news/data/n-20250806_3.html"),
    2026: ("pdf/n-20260805_1.pdf", "news/data/n-20260805_1.html"),
}
NUM = r"\d{1,3}(?:,\d{3})+|\d+"


# ---------- 純粋関数 ----------

def to_int(text: str) -> int:
    return int(text.replace(",", ""))


def parse_table1(text: str) -> dict[int, int]:
    """「表１ 消費生活相談の年度別総件数」の表。年度→件数。"""
    lines = text.splitlines()
    out: dict[int, int] = {}
    start = None
    for i, line in enumerate(lines):
        if line.startswith("表１ 消費生活相談の年度別総件数"):
            start = i
            break
    if start is None:
        return out
    for line in lines[start + 2:]:
        pairs = re.findall(r"(?<!\d)((?:19|20)\d\d) (\d{1,3}(?:,\d{3})+)(?!\d)", line)
        if not pairs:
            if out:
                break
            continue
        for y, n in pairs:
            out[int(y)] = to_int(n)
    return out


def parse_fig_amounts(text: str) -> dict[int, dict[str, int]]:
    """図「年度別にみた契約購入金額および既支払金額の推移」。各年は「平均 合計」「年」「平均 合計」の3行。"""
    lines = [ln.strip() for ln in text.splitlines()]
    start = next((i for i, ln in enumerate(lines) if "年度別にみた契約購入金額および既支払金額の推移" in ln
                  and ln.startswith("図")), None)
    out: dict[int, dict[str, int]] = {}
    if start is None:
        return out
    pair = re.compile(r"^(\d{1,4}) (\d{1,3}(?:,\d{3})*)$")
    i = start + 1
    while i + 2 < len(lines):
        a, y, b = pair.match(lines[i]), re.fullmatch(r"(?:19|20)\d\d", lines[i + 1]), pair.match(lines[i + 2])
        if a and y and b:
            ca, ct, pa, pt = to_int(a.group(1)), to_int(a.group(2)), to_int(b.group(1)), to_int(b.group(2))
            if pa <= ca and pt <= ct:
                out[int(lines[i + 1])] = {"契約購入金額の平均": ca, "契約購入金額の合計": ct,
                                          "既支払金額の平均": pa, "既支払金額の合計": pt}
            i += 3
        else:
            i += 1
        if lines[i - 1].startswith("（注）") or lines[i - 1].startswith("【"):
            break
    return out


TITLE_RE = re.compile(r"^表\d+[−-]\d+ (\d{4})年度の上位商品・役務(?:等)?別")
RANK_RE = re.compile(r"^(\d{1,2}) ?([^\d\s（(].*?)\s+(\d{1,3}(?:,\d{3})*)(?:\s+\d+\.\d)?$")
FEMALE_RE = re.compile(r"^女性\s+(\d{1,3}(?:,\d{3})*)(?:\s+\d+\.\d)?\s+(.+?)\s+(\d{1,3}(?:,\d{3})*)\s+\S+\s+（[\d.]+）$")
MALE_RE = re.compile(r"^男性\s+(\d{1,3}(?:,\d{3})*)\b")


def parse_features(text: str) -> tuple[dict[int, list[dict]], dict[int, list[int]]]:
    """上位商品・役務等別の「相談の特徴」の表。年度→行、年度→行にできなかった順位。
    男性行・順位行・女性行が続けて並んだ行だけ採り、男性＋女性の件数が件数を超えない検算をする。"""
    rows: dict[int, list[dict]] = {}
    skipped: dict[int, list[int]] = {}
    fy = None
    lines = [ln.strip() for ln in text.splitlines()]
    seen_ranks: dict[int, set[int]] = {}
    for i, ln in enumerate(lines):
        m = TITLE_RE.match(ln)
        if m:
            fy = int(m.group(1))
            rows.setdefault(fy, [])
            continue
        if fy is None:
            continue
        if ln.startswith("（注"):
            fy = None
            continue
        rk = RANK_RE.match(ln)
        if rk and 1 <= int(rk.group(1)) <= 25 and i + 1 < len(lines) and i > 0:
            rank, total = int(rk.group(1)), to_int(rk.group(3))
            name, mark = rk.group(2).replace("※", "").strip(), "※" in rk.group(2)
            seen_ranks.setdefault(fy, set()).add(rank)
            male, female = MALE_RE.match(lines[i - 1]), FEMALE_RE.match(lines[i + 1])
            if male and female:
                mc, fc, paid = to_int(male.group(1)), to_int(female.group(1)), to_int(female.group(3))
                if mc + fc <= total:
                    rows[fy].append({"順位": rank, "商品・役務等": name, "件数": total, "平均既支払金額（円）": paid, "分類変更": mark})
    for y, got in rows.items():
        have = {r["順位"] for r in got}
        skipped[y] = sorted(set(range(1, 26)) - have)
    return rows, skipped


NARR_RE = re.compile(r"契約購入金額は、合計金額が(" + NUM + r")億円、平均金額が(" + NUM + r")万円、"
                     r"既支払金額は、?合計金額が(" + NUM + r")億円、平均金額が(" + NUM + r")万円")


def parse_narrative(html_text: str) -> dict[str, int] | None:
    flat = re.sub(r"<[^>]+>", "", html_text)
    flat = re.sub(r"\s+", "", flat)
    m = NARR_RE.search(flat)
    if not m:
        return None
    ct, ca, pt, pa = (to_int(g) for g in m.groups())
    return {"契約購入金額の合計": ct, "契約購入金額の平均": ca, "既支払金額の合計": pt, "既支払金額の平均": pa}


# ---------- 実行 ----------

def pdf_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def main() -> int:
    rows: list[list] = []
    status: list[list] = []
    for y, rel in ANNUAL.items():
        url = BASE + rel
        dest, st = bf.fetch("kokusen", url, f"{y}_nenpou.pdf")
        ed = f"消費生活年報{y}"
        if st != 200:
            status.append([ed, "取得できず", f"HTTP {st}", url])
            continue
        text = pdf_text(dest)
        t1 = parse_table1(text)
        for fy, n in sorted(t1.items()):
            rows.append(["PIO-NET相談総件数", f"全体（{ed}掲載の表1）", fy, n, "件", url, "年度。版により改訂される"])
        amounts = parse_fig_amounts(text)
        for fy, d in sorted(amounts.items()):
            for k, v in d.items():
                rows.append([f"PIO-NET {k}", f"相談全体（{ed}掲載の図）", fy, v,
                             "万円" if "平均" in k else "億円", url, "四捨五入後の値（図中の表記）"])
        feats, skipped = parse_features(text)
        for fy, lst in sorted(feats.items()):
            for r in lst:
                rows.append(["PIO-NET相談件数（商品・役務等別・上位25位）", r["商品・役務等"], fy, r["件数"], "件", url,
                             f"{ed}。順位{r['順位']}" + ("。※付き（2021年度の分類変更で時系列比較不可）" if r["分類変更"] else "")])
                rows.append(["PIO-NET平均既支払金額（商品・役務等別・上位25位）", r["商品・役務等"], fy,
                             r["平均既支払金額（円）"], "円", url, f"{ed}。順位{r['順位']}"])
            status.append([ed, "取得", f"{fy}年度 上位25位のうち{len(lst)}行を採用。採用できなかった順位:"
                           f"{skipped[fy] or 'なし'}（名前の折り返し等で行の対応を確定できないもの）", url])
        status.append([ed, "取得", f"表1 {len(t1)}年度、図 {len(amounts)}年度", url])
    for y, (pdf_rel, page_rel) in SUMMARY.items():
        url = BASE + pdf_rel
        ed = f"{y}年公表『全国の消費生活相談の状況』"
        dest, st = bf.fetch("kokusen", url, Path(pdf_rel).name)
        if st == 200:
            t1 = parse_table1(pdf_text(dest))
            for fy, n in sorted(t1.items()):
                rows.append(["PIO-NET相談総件数", f"全体（{ed}の表1）", fy, n, "件", url, "年度。版により改訂される"])
            if t1:
                status.append([ed, "取得", f"表1 {len(t1)}年度", url])
            else:
                status.append([ed, "取得できず", "表1の文字が崩れて読めない（表が縦書き・回転で文字列にならない）", url])
        else:
            status.append([ed, "取得できず", f"HTTP {st}", url])
        purl = BASE + page_rel
        pdest, pst = bf.fetch("kokusen", purl, Path(page_rel).name)
        if pst == 200:
            nar = parse_narrative(pdest.read_text(encoding="utf-8", errors="ignore"))
            if nar:
                for k, v in nar.items():
                    rows.append([f"PIO-NET {k}", f"相談全体（{ed}の本文）", y - 1, v,
                                 "万円" if "平均" in k else "億円", purl, "本文の文から。年度は公表年の前年度"])
                status.append([ed, "取得", "契約購入金額・既支払金額の本文の文", purl])
            else:
                status.append([ed, "取得できず", "本文に契約購入金額・既支払金額の文が見つからない", purl])
        else:
            status.append([ed, "取得できず", f"本文ページ HTTP {pst}", purl])
    status.append(["2015年度以前の年報（消費生活年報2015以前）", "取得できず",
                   "国民生活センターの公開ページが年報2016以降のPDFだけを掲載し、2015以前のPDFのURLは404（pdf_dl/nenpou/2015_nenpou.pdf など）。"
                   "年度別総件数（表1）だけは年報2016掲載の1984〜2015年度が取れる", BASE + "soudan_topics/data/annualreport.html"])
    bf.write_csv(OUT, COLS, rows)
    bf.write_csv(STATUS, ["対象", "状況", "内容", "出典URL"], status)
    print(len(rows), "rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
