#!/usr/bin/env python3
"""金融庁 貸金業関係資料集から便益ルール D5 の数を取る。

出力: data/acquired/benefit-data/fsa_kasikin.csv（系列,区分,年,値,単位,出典URL,備考）
      data/acquired/benefit-data/fsa_kasikin_status.csv（取れた範囲と取れなかった理由）
原本: .local/benefit-data/raw/fsa-kasikin/（git 管理外）

取るもの:
  - 貸金業者数（登録、各年3月末）、貸付残高（消費者向・事業者向、業態別、各年3月末）、
    貸金業者の行政処分件数（年度）、金融庁・財務局・都道府県に寄せられた貸金業者に係る苦情等の件数（年度）
  - 令和7年11月掲載の資料集（Excel）を基本に、古い資料集（Excel・PDF）で期間を延ばす。
    PDF は表の行の数が見出しの列の数と一致し、苦情の内訳は内訳の和が「苦情計」「相談・照会計」に一致するときだけ採る。
年は、3月末の数は3月末の年、年度の数は年度の初めの年。
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import benefit_fetch as bf  # noqa: E402

BASE = "https://www.fsa.go.jp/status/kasikin/"
OUT = bf.OUT_DIR / "fsa_kasikin.csv"
STATUS = bf.OUT_DIR / "fsa_kasikin_status.csv"
ERA_BASE = {"明治": 1867, "大正": 1911, "昭和": 1925, "平成": 1988, "令和": 2018}
SHORT_ERA = {"S": "昭和", "H": "平成", "R": "令和"}


# ---------- 文字列・年 ----------

def clean(value) -> str:
    """全角を半角にそろえ、空白と改行を除く。"""
    if value is None:
        return ""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)))


def era_year(label, era_hint: str | None = None) -> tuple[str, int] | None:
    """「平成16年3月末」「12年3月末」「令和元年度」などの先頭の年を(元号, 西暦)にする。"""
    s = clean(label)
    m = re.match(r"^(明治|大正|昭和|平成|令和)?(元|\d+)年", s)
    if not m:
        return None
    era = m.group(1) or era_hint
    if era is None:
        return None
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return era, ERA_BASE[era] + n


def short_year(label) -> int | None:
    m = re.match(r"^([SHR])(元|\d+)年$", clean(label))
    if not m:
        return None
    n = 1 if m.group(2) == "元" else int(m.group(2))
    return ERA_BASE[SHORT_ERA[m.group(1)]] + n


def num(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    s = clean(value).replace(",", "")
    return int(s) if re.fullmatch(r"\d+", s) else None


# ---------- Excel の表 ----------

def parse_year_blocks(grid: list[list], label_col: int = 1, first_col: int = 2) -> list[tuple[str, int, float]]:
    """「平成16年3月末」を横に5つ並べた段を縦に重ねた表（各年度末の推移）。(区分, 年, 値)。"""
    out: list[tuple[str, int, float]] = []
    cols: dict[int, int] = {}
    for row in grid:
        heads = {}
        for j, c in enumerate(row):
            if j >= first_col and isinstance(c, str) and "月末" in clean(c):
                ey = era_year(c)
                if ey:
                    heads[j] = ey[1]
        if heads:
            cols = heads
            continue
        if cols and len(row) > label_col and isinstance(row[label_col], str):
            label = clean(row[label_col])
            for j, y in cols.items():
                v = num(row[j]) if j < len(row) else None
                if label and v is not None:
                    out.append((label, y, v))
    return out


def parse_gyotai(grid: list[list]) -> list[tuple[str, int, float]]:
    """業態別の貸付残高（行が業態、列が各年3月末。業態の行の次は対前年比の行なので読まない）。"""
    cols: dict[int, int] = {}
    out: list[tuple[str, int, float]] = []
    for row in grid:
        if not cols:
            era = None
            tmp = {}
            for j, c in enumerate(row):
                if isinstance(c, str) and "3月末" in clean(c):
                    ey = era_year(c, era)
                    if ey:
                        era = ey[0] if re.match(r"^(明治|大正|昭和|平成|令和)", clean(c)) else era
                        tmp[j] = ey[1]
            if len(tmp) >= 10:
                cols = tmp
            continue
        if row and isinstance(row[0], str) and clean(row[0]) and not clean(row[0]).startswith("（注"):
            label = clean(row[0])
            for j, y in cols.items():
                v = num(row[j]) if j < len(row) else None
                if v is not None:
                    out.append((label, y, v))
    return out


def parse_long_term(grid: list[list]) -> list[tuple[str, int, float]]:
    """貸金業者数の長期的な推移（S59年〜R7年。列の見出しが「S59年」の形）。"""
    cols: dict[int, int] = {}
    out: list[tuple[str, int, float]] = []
    for row in grid:
        heads = {j: short_year(c) for j, c in enumerate(row) if short_year(c)}
        if len(heads) >= 5:
            cols = heads
            continue
        if cols and len(row) > 1 and isinstance(row[1], str):
            label = clean(row[1])
            for j, y in cols.items():
                v = num(row[j]) if j < len(row) else None
                if label and v is not None:
                    out.append((label, y, v))
    return out


QUARTERS = ("4～6月", "7～9月", "10～12月", "1～3月")


def norm_sub(value) -> str:
    return clean(value).replace("~", "～").replace("〜", "～")


def year_columns(year_row: list, sub_row: list) -> list[tuple[int, int]]:
    """年度の見出しの行と、その下の「計」「4～6月」の行から、年度の合計の列を(列, 年)で返す。"""
    cur = None
    cells = []
    quarters: dict[int, set] = {}
    for j in range(max(len(year_row), len(sub_row))):
        c = year_row[j] if j < len(year_row) else None
        ey = era_year(c) if isinstance(c, str) and "年度" in clean(c) else None
        labelled = bool(ey)
        if ey:
            cur = ey[1]
        sub = norm_sub(sub_row[j]) if j < len(sub_row) else ""
        if cur is None:
            continue
        cells.append((j, cur, sub, labelled))
        if sub in QUARTERS:
            quarters.setdefault(cur, set()).add(sub)
    out = []
    for j, y, sub, labelled in cells:
        complete = len(quarters.get(y, ())) in (0, 4)  # 四半期が4つ揃わない年度の「計」は年度の合計ではない
        if complete and (sub == "計" or (sub == "" and labelled)):
            out.append((j, y))
    return out


def find_header(grid: list[list], minimum: int = 3) -> int | None:
    for i, row in enumerate(grid[:12]):
        n = sum(1 for c in row if isinstance(c, str) and "年度" in clean(c) and era_year(c))
        if n >= minimum:
            return i
    return None


def parse_enforcement(grid: list[list]) -> list[tuple[str, int, float]]:
    """貸金業者の行政処分件数の推移（財務局登録・都道府県登録・計 × 処分事由。年度）。"""
    h = find_header(grid, 5)
    if h is None:
        return []
    cols = year_columns(grid[h], grid[h + 1])
    out = []
    group = ""
    for row in grid[h + 2:]:
        if len(row) > 1 and row[1] is not None and clean(row[1]):
            group = clean(row[1])
        if group.startswith("（注"):
            break
        label = clean(row[3]) if len(row) > 3 and row[3] is not None else ""
        if not label and len(row) > 2 and row[2] is not None:
            label = clean(row[2])
        label = re.split(r"[（(]", label)[0]
        if not label:
            continue
        for j, y in cols:
            v = num(row[j]) if j < len(row) else None
            if v is not None:
                out.append((f"{group}/{label}", y, v))
    return out


def parse_complaints(grid: list[list]) -> list[tuple[str, int, float]]:
    """苦情等の件数（内容別）。「苦情の内容」「相談・照会の内容」を区分の前に付ける。"""
    h = find_header(grid, 3)
    if h is None:
        return []
    cols = year_columns(grid[h], grid[h + 1])
    out = []
    group = ""
    for row in grid[h + 2:]:
        c1 = clean(row[1]) if len(row) > 1 else ""
        c2 = clean(row[2]) if len(row) > 2 else ""
        if c1.startswith("（注") or c1.startswith("令和元年度は"):
            break
        if c1 and c2:
            group, label = c1, c2
        elif c1:
            group, label = "", c1
        else:
            label = c2
        if not label:
            continue
        key = f"{group}/{label}" if group else label
        for j, y in cols:
            v = num(row[j]) if j < len(row) else None
            if v is not None:
                out.append((key, y, v))
    return out


def parse_complaints_by_office(grid: list[list]) -> list[tuple[str, int, float]]:
    """苦情等の件数（受付先別。金融庁・財務局・都道府県・計）。"""
    h = None
    for i, row in enumerate(grid[:6]):
        if sum(1 for c in row if isinstance(c, str) and era_year(c) and "年度" in clean(c)) >= 2:
            h = i
    if h is None:
        return []
    cur = None
    cols = []
    for j in range(len(grid[h])):
        c = grid[h][j]
        ey = era_year(c) if isinstance(c, str) and "年度" in clean(c) else None
        if ey:
            cur = ey[1]
        sub = clean(grid[h + 1][j]) if j < len(grid[h + 1]) else ""
        if cur is not None and sub:
            cols.append((j, cur, sub))
    out = []
    group = ""
    for row in grid[h + 2:]:
        c1 = clean(row[1]) if len(row) > 1 else ""
        c2 = clean(row[2]) if len(row) > 2 else ""
        if c1.startswith("（注"):
            break
        if c1 and c2:
            group, label = c1, c2
        elif c1:
            group, label = "", c1
        else:
            label = c2
        if not label:
            continue
        key = f"{group}/{label}" if group else label
        for j, y, sub in cols:
            v = num(row[j]) if j < len(row) else None
            if v is not None:
                out.append((f"{key}/{sub}", y, v))
    return out


# ---------- PDF の表 ----------

NUMTOK = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+|－|-)$")


def split_label_values(line: str) -> tuple[str, list[str]] | None:
    toks = unicodedata.normalize("NFKC", line).split()
    i = len(toks)
    while i > 0 and NUMTOK.match(toks[i - 1]):
        i -= 1
    if i == len(toks):
        return None
    label_toks = toks[:i]
    if len(label_toks) >= 2 and len(label_toks[0]) == 1:
        label_toks = label_toks[1:]  # 縦書きの見出しの文字が行頭に混じる
    return "".join(label_toks), toks[i:]


def group_columns(years: list[int], subs: list[str]) -> list[tuple[int, str]] | None:
    """年度と「計/4～6月…」の並びから、各列の(年度, 計か四半期か)を決める。決められなければ None。"""
    cols = []
    k = 0
    for y in years:
        if k >= len(subs):
            return None
        if subs[k] == "計":
            cols.append((y, "計"))
            k += 1
            continue
        n = 0
        while k < len(subs) and subs[k] != "計":
            cols.append((y, subs[k]))
            k += 1
            n += 1
        if k >= len(subs):
            return None
        cols.append((y, "計" if n == 4 else "一部期間の計"))  # 四半期が4つ揃わない年度は年度の合計ではない
        k += 1
    return cols if k == len(subs) else None


def parse_complaints_pdf(text: str) -> tuple[list[tuple[str, int, int]], str]:
    """PDF の苦情等の件数（内容別）。(区分, 年度, 値) と、内訳を採れなかったときの説明を返す。"""
    lines = [unicodedata.normalize("NFKC", ln).strip() for ln in text.splitlines()]
    years: list[int] = []
    hi = None
    for i, ln in enumerate(lines):
        ys = [era_year(re.sub(r"\s", "", m.group(0))) for m in re.finditer(r"(?:平成|令和)\s*(?:元|\d+)\s*年度", ln)]
        if len([y for y in ys if y]) >= 2:
            years = [y[1] for y in ys if y]
            hi = i
            break
    if hi is None:
        return [], "年度の見出しが無い"
    subs: list[str] = []
    for ln in lines[hi + 1:hi + 4]:
        toks = [norm_sub(t) for t in ln.split()]
        if toks and all(t == "計" or t in QUARTERS for t in toks):
            subs = toks
            break
    cols = group_columns(years, subs) if subs else None
    if not cols:
        return [], "年度と計・四半期の見出しの並びを決められない"
    rows: list[tuple[str, list[int | None]]] = []
    for ln in lines[hi + 1:]:
        if ln.startswith("（注"):
            break
        sv = split_label_values(ln)
        if not sv or sv[0] == "":
            continue
        label, vals = sv
        if len(vals) != len(cols):
            continue
        rows.append((label, [None if v in ("－", "-") else int(v.replace(",", "")) for v in vals]))
    names = [r[0] for r in rows]
    out: list[tuple[str, int, int]] = []

    def emit(prefix: str, label: str, vals: list[int | None]) -> None:
        for (y, kind), v in zip(cols, vals):
            if kind == "計" and v is not None:
                out.append((f"{prefix}{label}", y, v))

    for label, vals in rows:
        if label in ("苦情等受付件数", "うち無登録業者に係るもの", "苦情計", "相談・照会計"):
            emit("", label, vals)
    note = ""
    if "苦情計" in names and "相談・照会計" in names:
        i1, i2 = names.index("苦情計"), names.index("相談・照会計")
        start = names.index("うち無登録業者に係るもの") + 1 if "うち無登録業者に係るもの" in names else 1
        sections = [("苦情の内容/", rows[start:i1], rows[i1]), ("相談・照会の内容/", rows[i1 + 1:i2], rows[i2])]
        ok = True
        for _, items, total in sections:
            for c in range(len(cols)):
                if sum((r[1][c] or 0) for r in items) != (total[1][c] or 0):
                    ok = False
        if ok:
            for prefix, items, _ in sections:
                for label, vals in items:
                    emit(prefix, label, vals)
        else:
            note = "内訳の和が苦情計・相談・照会計と一致しないため内訳は採らず、合計の行だけ採った"
    else:
        note = "苦情計・相談・照会計の行が無い（内訳の区分を確定できない）ため、合計の行だけ採った"
    return out, note


def parse_long_term_pdf(text: str) -> list[tuple[str, int, int]]:
    """PDF の貸金業者数の長期的な推移（見出しの年の数と各行の数が一致するときだけ）。"""
    lines = [unicodedata.normalize("NFKC", ln).strip() for ln in text.splitlines()]
    heads: list[int | None] = []
    for ln in lines:
        toks = ln.split()
        yrs = [short_year(t) for t in toks]
        if sum(1 for y in yrs if y) >= 10:
            heads = [short_year(t) if short_year(t) else None for t in toks]
            break
    if not heads:
        return []
    out = []
    for ln in lines:
        for label in ("都道府県登録", "財務局登録", "合計"):
            compact = ln.replace(" ", "")
            if compact.startswith(label):
                vals = re.findall(r"\d{1,3}(?:,\d{3})*", ln.split(label[-1], 1)[1] if label != "合計" else ln.split("計", 1)[1])
                if len(vals) == len(heads):
                    for y, v in zip(heads, vals):
                        if y:
                            out.append((label, y, int(v.replace(",", ""))))
    return out


# ---------- 取得と出力 ----------

def load_grid(path: Path) -> list[list]:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[wb.sheetnames[0]]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def pdf_text(path: Path) -> str:
    import pdfplumber
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def main() -> int:
    rows: list[list] = []
    status: list[list] = []

    def add(series, items, unit, url, note):
        for label, y, v in items:
            rows.append([series, label, y, v, unit, url, note])

    def get(collection: str, name: str, kind: str):
        url = f"{BASE}{collection}/{name}.{kind}"
        dest, st = bf.fetch("fsa-kasikin", url, f"{collection}_{name}.{kind}")
        return url, dest, st

    main_c = "20251128"
    for name, label, fn, series, unit, note in [
        ("01", "各年度末の推移", parse_year_blocks, "貸金業者数（登録）", "業者", "各年3月末"),
        ("04", "貸金業者数の長期的な推移", parse_long_term, "貸金業者数（登録、長期推移表）", "業者", "各年3月末（H4〜H17年は表に無い）"),
        ("05", "消費者向・事業者向別の貸付残高", parse_year_blocks, "貸付残高", "億円", "各年3月末"),
        ("06", "業態別の貸付残高", parse_gyotai, "業態別貸付残高", "億円", "各年3月末。対前年比の行は読まない"),
        ("17", "貸金業者の行政処分件数", parse_enforcement, "貸金業者の行政処分件数", "件", "年度"),
        ("18", "苦情等の件数（内容別）", parse_complaints, "貸金業者に係る苦情等の件数", "件", "年度（令和元年度〜）"),
        ("19", "苦情等の件数（受付先別）", parse_complaints_by_office, "貸金業者に係る苦情等の件数（受付先別）", "件", "年度（令和2年度〜）"),
    ]:
        url, dest, st = get(main_c, name, "xlsx")
        if st != 200:
            status.append([f"{main_c}/{name} {label}", "取得できず", f"HTTP {st}", url])
            continue
        got = fn(load_grid(dest))
        add(series, got, unit, url, f"令和7年11月28日掲載の資料集。{note}")
        years = sorted({y for _, y, _ in got})
        status.append([f"{main_c}/{name} {label}", "取得" if got else "取得できず",
                       f"{len(got)}行、{years[0]}〜{years[-1]}年" if got else "表を読めない", url])
    # 古い資料集で延ばす
    url, dest, st = get("20191031", "21", "xlsx")
    if st == 200:
        got = parse_complaints(load_grid(dest))
        add("貸金業者に係る苦情等の件数", got, "件", url, "令和元年10月31日掲載の資料集。年度。令和2年度第1四半期は除く（合計の列だけ）")
        ys = sorted({y for _, y, _ in got})
        status.append(["20191031/21 苦情等の件数（内容別）", "取得", f"{len(got)}行、{ys[0]}〜{ys[-1]}年度", url])
    for coll, name, label in [("20140930", "21", "苦情等の件数（内容別、H22〜H27）"),
                              ("20101102", "23", "苦情等の件数（H19〜H22）"),
                              ("20080307", "20", "苦情等の件数（H14〜H18）")]:
        url, dest, st = get(coll, name, "pdf")
        if st != 200:
            status.append([f"{coll}/{name} {label}", "取得できず", f"HTTP {st}", url])
            continue
        got, note = parse_complaints_pdf(pdf_text(dest))
        add("貸金業者に係る苦情等の件数", got, "件", url, f"{coll}掲載の資料集（PDF）。年度" + (f"。{note}" if note else ""))
        status.append([f"{coll}/{name} {label}", "取得" if got else "取得できず",
                       (f"{len(got)}行。" + note) if got else note or "表を読めない", url])
    url, dest, st = get("20140930", "06", "pdf")
    if st == 200:
        got = parse_long_term_pdf(pdf_text(dest))
        add("貸金業者数（登録、長期推移表）", got, "業者", url, "平成26年9月30日掲載の資料集（PDF）。各年3月末")
        ys = sorted({y for _, y, _ in got})
        status.append(["20140930/06 貸金業者数の長期的な推移", "取得" if got else "取得できず",
                       f"{len(got)}行、{ys[0]}〜{ys[-1]}年" if got else "表を読めない", url])
    status.append(["1995年から1998年の業態別貸付残高・苦情等の件数（H7〜H13年度）", "取得できず",
                   "公開されている資料集は平成17年10月以降の掲載分で、業態別貸付残高は平成11年3月末から、"
                   "苦情等の件数は平成14年度から。それ以前は金融庁の公表資料に無い", BASE + "index_2.html"])
    status.append(["貸金業者数のうち平成20年3月掲載のPDF（長期推移表）", "取得できず",
                   "文字列が無い（画像）。同じ期間は平成26年9月掲載のPDFの表で読めたので不要", BASE + "20080307/06.pdf"])
    bf.write_csv(OUT, ["系列", "区分", "年", "値", "単位", "出典URL", "備考"], rows)
    bf.write_csv(STATUS, ["対象", "状況", "内容", "出典URL"], status)
    print(len(rows), "rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
