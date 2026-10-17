#!/usr/bin/env python3
"""預金保険機構「資金援助等の実施及び回収状況等」から、資金援助等実施額（累計）を取る（便益ルール D8）。

出力: data/acquired/benefit-data/dic_assistance.csv（系列,区分,年,値,単位,出典URL,備考）
      data/acquired/benefit-data/dic_status.csv
原本: .local/benefit-data/raw/dic/（git 管理外）

取るもの: 令和8年3月末現在の累計の、資金援助等実施額（表の(a)の列）。表は行ごとに列の一部が空なので、
各行の最初の数が(a)であることを、合計の行と内訳の和の一致で確かめる（③資本増強＝3つの内訳の和）。
取れないもの: 破綻した金融機関の年ごとの件数。預金保険機構のページには、金融整理管財人に選任された
13先（平成11〜22年）の一覧と、この累計の表しか無く、年ごとの破綻件数の表が無い。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import benefit_fetch as bf  # noqa: E402

PDF_URL = "https://www.dic.go.jp/katsudo/content/shikinenjo_no_jissi_oyobi_kaisyujoukyoutou_202603.pdf"
OUT = bf.OUT_DIR / "dic_assistance.csv"
STATUS = bf.OUT_DIR / "dic_status.csv"


def parse_table(text: str) -> list[tuple[str, int]]:
    """各行の(区分, 資金援助等実施額（億円）)。ラベルのある行で、ラベルの後ろに最初に出る数を(a)とする。"""
    text = re.sub(r"\(cid:\d+\)", " ", text).replace("▲", " ▲")
    out: list[tuple[str, int]] = []
    for line in text.splitlines():
        if line.startswith("※"):
            break
        m = re.match(r"^(\S.*?)\s+(\d{1,3}(?:,\d{3})*)(?:\s|$)", line.strip())
        if not m:
            continue
        label = re.sub(r"[（(]注\d+[）)]", "", m.group(1)).strip()
        label = re.sub(r"\s+", "", label)
        if not label or re.fullmatch(r"[\d,]+", label) or label.startswith("（") or label.startswith("(") or "資金援助等項目" in label or "令和" in label:
            continue
        out.append((label, int(m.group(2).replace(",", ""))))
    return out


def check(rows: list[tuple[str, int]]) -> str:
    d = dict(rows)
    keys = ["旧安定化法に基づく資本増強", "早期健全化法に基づく資本増強", "預金保険法に基づく資本増強"]
    if all(k in d for k in keys) and "③資本増強" in d:
        if sum(d[k] for k in keys) != d["③資本増強"]:
            return "③資本増強の内訳の和が合わない"
        return ""
    return "③資本増強の検算に必要な行が無い"


def main() -> int:
    dest, st = bf.fetch("dic", PDF_URL, "shikinenjo_202603.pdf")
    status: list[list] = []
    rows: list[list] = []
    if st != 200:
        status.append(["資金援助等の実施及び回収状況等（令和8年3月末）", "取得できず", f"HTTP {st}", PDF_URL])
    else:
        import pdfplumber
        with pdfplumber.open(dest) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        parsed = parse_table(text)
        why = check(parsed)
        if why:
            status.append(["資金援助等の実施及び回収状況等（令和8年3月末）", "取得できず", why, PDF_URL])
        else:
            for label, v in parsed:
                rows.append(["預金保険機構 資金援助等実施額（累計）", label, 2026, v, "億円", PDF_URL,
                             "令和8年3月末現在の累計。表の(a)の列。億円未満四捨五入のため合計が一致しない所がある"])
            status.append(["資金援助等の実施及び回収状況等（令和8年3月末）", "取得", f"{len(rows)}行", PDF_URL])
    status.append(["破綻した金融機関の年ごとの件数（1991年〜）", "取得できず",
                   "預金保険機構のページ（活動・実績）には年ごとの破綻件数の表が無い。載っているのは資金援助等の累計額のPDFと、"
                   "金融整理管財人に選任された被管理金融機関13先の一覧（平成11〜22年）のみ",
                   "https://www.dic.go.jp/katsudo/page_001084.html"])
    bf.write_csv(OUT, ["系列", "区分", "年", "値", "単位", "出典URL", "備考"], rows)
    bf.write_csv(STATUS, ["対象", "状況", "内容", "出典URL"], status)
    print(len(rows), "rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
