#!/usr/bin/env python3
"""最高裁 司法統計年報（民事・行政編）の「破産新受事件数―受理区分別―全地方裁判所」表を取る（便益ルール D6）。

出力: data/acquired/benefit-data/courts_bankruptcy.csv（系列,区分,年,値,単位,出典URL,備考）
      data/acquired/benefit-data/courts_bankruptcy_status.csv（年ごとの取得状況と理由）
原本: .local/benefit-data/raw/courts/（git 管理外）

表の形（2005年以降の破産法）: 総数, 自然人, 自然人のうち自己破産, 法人・その他,
法人・その他のうち自己破産, 本年中に破産手続開始決定のあったもの の6つの数。
- 2016年以降は表の Excel（セルで取る）。2021年以降は年報1冊の Excel の「105」シート。
- 2000〜2015年は表の PDF の文字列。千位の空白で数の切れ目が曖昧なので、
  「総数＝自然人＋法人・その他、自然人≧自己破産、法人・その他≧自己破産」を満たす分け方が
  ちょうど1通りのときだけ採る。満たさない・複数あるときは取得できずとする。
- 正誤表は使わない（年報本体の更新版が正誤表の訂正後の値になっていることを確かめた）。
"""
from __future__ import annotations

import html
import re
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import benefit_fetch as bf  # noqa: E402

LIST_URL = ("https://www.courts.go.jp/toukei_siryou/shihotokei_search/list/index.html"
            "?filter%5Btype%5D=1&filter%5ByYear%5D={y}&filter%5ByCategory%5D=1&offset={o}")
FILE_BASE = "https://www.courts.go.jp/saikosai/vc-files/saikosai/toukei/"
TITLE = "破産新受事件数―受理区分別―全地方裁判所"
LABELS = ["総数", "自然人", "自然人のうち自己破産", "法人・その他", "法人・その他のうち自己破産",
          "本年中に破産手続開始決定のあったもの"]
SERIES = "破産新受件数（全地方裁判所）"
OUT_DIR = bf.OUT_DIR
OUT = OUT_DIR / "courts_bankruptcy.csv"
STATUS = OUT_DIR / "courts_bankruptcy_status.csv"


# ---------- 純粋関数 ----------

def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def groupings(tokens: list[str], k: int) -> list[list[int]]:
    """千位の空白で区切られた数字列を、ちょうど k 個の数に分ける全ての分け方を返す。"""
    out: list[list[int]] = []

    def rec(i: int, acc: list[int]) -> None:
        if len(acc) > k:
            return
        if i == len(tokens):
            if len(acc) == k:
                out.append(list(acc))
            return
        digits = tokens[i]
        if not digits.isdigit() or len(digits) > 3:
            if digits.isdigit():
                rec(i + 1, acc + [int(digits)])
            return
        rec(i + 1, acc + [int(digits)])
        j, num = i + 1, digits
        while j < len(tokens) and len(tokens[j]) == 3 and tokens[j].isdigit():
            num += tokens[j]
            rec(j + 1, acc + [int(num)])
            j += 1

    rec(0, [])
    return out


def consistent(v: list[int]) -> bool:
    return (len(v) == 6 and v[0] == v[1] + v[3] and v[1] >= v[2] and v[3] >= v[4] and v[5] <= v[0])


def decode_cid(text: str) -> str:
    """文字コードの対応表が無い PDF で (cid:N) と出る文字列を、数字（N=19〜28 が 0〜9）と空白（N=3）だけ復号し、
    他の字は □ にする。"""
    def one(m: re.Match) -> str:
        n = int(m.group(1))
        if 19 <= n <= 28:
            return str(n - 19)
        return " " if n == 3 else "□"
    return re.sub(r"\(cid:(\d+)\)", one, text)


def cell_int(c) -> int | None:
    if isinstance(c, bool):
        return None
    if isinstance(c, (int, float)):
        return int(c)
    if isinstance(c, str) and re.fullmatch(r"\s*\d{1,3}(?:\s\d{3})*\s*|\s*\d+\s*", c):
        return int(re.sub(r"\s", "", c))
    return None


def values_from_tokens(tokens: list[str]) -> list[int] | None:
    ok = [g for g in groupings(tokens, 6) if consistent(g)]
    return ok[0] if len(ok) == 1 else None


def values_from_pdf_text(text: str) -> tuple[list[int] | None, str]:
    """PDF の文字列から表を探す。(6つの数, 取得できない理由) を返す。"""
    garbled = "(cid:" in text
    if garbled:
        text = decode_cid(text)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if garbled:
            if re.match(r"^\W*□\s*105\s*□", line.strip()):
                start = i
                break
        elif TITLE in norm(line):
            start = i
            break
    if start is None:
        return None, "PDF に表の題名が無い"
    block = []
    for line in lines[start + 1:]:
        if re.match(r"^第\s*\d+\s*表", line.strip()) or (garbled and re.match(r"^\W*□\s*\d+\s*□", line.strip())):
            break
        block.append(line)
    numeric = [ln for ln in block if re.fullmatch(r"[\d\s]+", ln.strip()) and ln.strip()]
    tag = "（文字の対応表が無いPDFで数字だけ復号）" if garbled else ""
    if len(numeric) != 1:
        return None, f"数字だけの行が{len(numeric)}行あり、表の数を一意に決められない{tag}"
    vals = values_from_tokens(numeric[0].split())
    if vals is None:
        return None, ("千位の空白の分け方が一意でない、または総数＝自然人＋法人・その他などの検算を満たさない。"
                      "2004年以前の表は旧破産法の区分（自然人・法人の区分と異なる）" + tag)
    return vals, ""


def values_from_rows(rows: list[list]) -> tuple[list[int] | None, str]:
    """Excel の行（先頭から数行）から表を探す。見出しに自然人・法人・その他と自己破産があり、検算を満たすとき採る。"""
    flat = norm("".join(str(c) for r in rows[:8] for c in r if c is not None))
    if TITLE not in flat or "自然人" not in flat or "法人・その他" not in flat:
        return None, "Excel に表の題名または見出しが無い"
    for r in rows[:20]:
        nums = [cell_int(c) for c in r if cell_int(c) is not None]
        if len(nums) == 6:
            vals = nums
            if consistent(vals):
                return vals, ""
            return None, "6つの数が検算（総数＝自然人＋法人・その他など）を満たさない"
    return None, "6つの数の行が無い"


def candidate_links(page_html: str, after: str | None = None) -> list[str]:
    seg = page_html
    if after:
        i = page_html.find(after)
        if i < 0:
            return []
        seg = page_html[i:i + 3000]
    out: list[str] = []
    for h in re.findall(r'href="([^"]+toukei-[^"]+)"', seg):
        name = html.unescape(h).rsplit("/", 1)[-1]
        if name not in out:
            out.append(name)
    return out


def to_rows(year: int, vals: list[int], url: str, note: str) -> list[list]:
    return [[SERIES, lab, year, v, "件", url, note] for lab, v in zip(LABELS, vals)]


# ---------- 取得 ----------

def get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": bf.USER_AGENT})
    time.sleep(bf.INTERVAL)
    return urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "ignore")


def find_candidates(year: int) -> list[str]:
    if year >= 2021:
        return [n for n in candidate_links(get_text(LIST_URL.format(y=year, o=0))) if n.endswith(".xlsx")]
    for offset in (100, 90, 110, 80, 70):
        links = candidate_links(get_text(LIST_URL.format(y=year, o=offset)), after="破産新受事件数")
        if links:
            return links
    return []


def pdf_text(path: Path) -> str:
    import pdfplumber  # 仮想環境（リポジトリ外）に入れる
    with pdfplumber.open(path) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages)


def xlsx_rows(path: Path) -> tuple[list[list] | None, int]:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    n = len(wb.sheetnames)
    for ws in wb:
        rows = [list(r) for r in ws.iter_rows(min_row=1, max_row=24, values_only=True)]
        if TITLE in norm("".join(str(c) for r in rows[:4] for c in r if c is not None)):
            return rows, n
    return None, n


def run_year(year: int) -> tuple[list[list], list[str]]:
    cands = find_candidates(year)
    if not cands:
        return [], [str(year), "取得できず", "司法統計検索システムの一覧に当年の表が見つからない", ""]
    reasons = []
    for name in cands[:4]:
        url = FILE_BASE + name
        dest, status = bf.fetch("courts", url, f"{year}_{name}")
        if status != 200:
            reasons.append(f"{name}: HTTP {status}")
            continue
        if name.endswith(".xlsx"):
            rows, nsheets = xlsx_rows(dest)
            if rows is None:
                reasons.append(f"{name}: 表なし")
                continue
            if year >= 2021 and nsheets < 100:
                reasons.append(f"{name}: 年報本体ではない（シート{nsheets}）")
                continue
            vals, why = values_from_rows(rows)
        elif name.endswith(".pdf") and year <= 2015:
            vals, why = values_from_pdf_text(pdf_text(dest))
            if why == "PDF に表の題名が無い":
                reasons.append(f"{name}: 表なし")
                continue
        else:
            continue
        if vals is None:
            return [], [str(year), "取得できず", f"{name}: {why}", url]
        return to_rows(year, vals, url, "司法統計年報 民事・行政編 第105表（番号は年により変わりうる）"), [str(year), "取得", "", url]
    return [], [str(year), "取得できず", "; ".join(reasons) or "候補の表が見つからない", ""]


def main() -> int:
    rows: list[list] = []
    status: list[list] = []
    for year in range(2000, 2026):
        got, st = run_year(year)
        rows += got
        status.append(st)
        print(st, flush=True)
    for year in range(1990, 2000):
        status.append([str(year), "取得できず", "司法統計検索システムに1999年以前の年報の表が無い（一覧が0件）", ""])
    bf.write_csv(OUT, ["系列", "区分", "年", "値", "単位", "出典URL", "備考"], rows)
    bf.write_csv(STATUS, ["年", "状況", "理由", "出典URL"], sorted(status, key=lambda s: s[0]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
