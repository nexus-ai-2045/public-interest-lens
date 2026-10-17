"""成立した全法律（bill-census-full/enacted.csv）に施行日の行を作る。衆議院「制定法律」の附則を読んだ結果を使う（暫定値）。

入力: data/acquired/enforcement-dates/shugiin-fusoku-index.txt（1行1法律「コード 種別」）
- コード: 回次3桁＋公布日8桁＋法律番号3桁（衆議院の制定法律ページの名前と同じ）。
- 取得: 衆議院「制定法律」の各法律のページ（第150回以降は housei/{コード}.htm、第142〜147回は housei/h{回次}{番号}.htm）を
  Mac のブラウザで開き、附則の施行期日の文をブラウザ内で種別に直して転記した。原本のバイトは保存していない。
  転記は数百行ずつ、ブラウザ側とこちら側の sha256 が一致することを確かめた（manifest.csv）。
- 種別:
  P = 公布の日から施行 / D{YYYYMMDD} = 日付を明示 / R{年.月.日} = 公布の日から起算して◯を経過した日
  W{年.月.日} = 公布の日から起算して◯を超えない範囲内において政令で定める日 / G = その他の政令で定める日
  I = 各号ごとに施行（本則の施行日が1つに決まらない） / U = 読めない / H{status} = ページが取れない
  末尾の x = ページ冒頭の「法律第◯号（…）」が法律番号・公布日と合わない（施行日に使わない）

採る規則（推測で埋めない）:
1. 既にある行（施行日の有無を問わず）は変えない。台帳に無い法律だけ行を足す。
2. P は公布日、D はその日、R は公布日＋期間（fetch_enforcement_fusoku.add_period）。
3. W は期限を計算し、公布日と期限が同じ暦年・同じ年度のときだけ期限の日を置く（apply_enforcement_year_window と同じ規則）。
4. それ以外（G・I・U・H・x、W で年が決まらない、コードが無い）は施行日を空欄にし、理由を備考に書く。
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from scripts.apply_enforcement_year_window import same_year
from scripts.fetch_enforcement_fusoku import CAND_COL, NEW_COL, add_period

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "data" / "acquired" / "enforcement-dates"
CSV_PATH = DIR / "enforcement.csv"
INDEX = DIR / "shugiin-fusoku-index.txt"
ENACTED = ROOT / "data" / "acquired" / "bill-census-full" / "enacted.csv"

ERAS = {"昭和": 1925, "平成": 1988, "令和": 2018}
KANJI = "〇一二三四五六七八九"
SOURCE = "https://www.shugiin.go.jp/internet/itdb_housei.nsf/html/housei/"
METHOD = "衆議院 制定法律の附則（ブラウザで読んで種別を転記、1回取得の暫定値）"
METHOD_CALC = "計算（衆議院 制定法律の附則：公布日＋期間、1回取得の暫定値）"
METHOD_WINDOW = "年の確定（衆議院 制定法律の附則の期限と公布日が同じ年・同じ年度。日は未確定で期限の日を置く、1回取得の暫定値）"
KIND_TEXT = {
    "G": "政令で定める日（期限の書き方が読めない）",
    "I": "各号ごとに施行（本則の施行日が1つに決まらない）",
    "U": "附則の施行期日の文を読めない",
}


def kanji(n: int) -> str:
    """整数を十・百を使う漢数字にする（法令番号の書き方）。"""
    if n == 0:
        return KANJI[0]
    out = ""
    for unit, ch in ((100, "百"), (10, "十")):
        q, n = divmod(n, unit)
        if q:
            out += ("" if q == 1 else KANJI[q]) + ch
    return out + (KANJI[n] if n else "")


def iso(jp: str) -> str | None:
    m = re.match(r"(昭和|平成|令和)\s*(元|\d+)年\s*(\d+)月\s*(\d+)日", jp.strip())
    if not m:
        return None
    year = ERAS[m[1]] + (1 if m[2] == "元" else int(m[2]))
    return f"{year}-{int(m[3]):02d}-{int(m[4]):02d}"


def era_of(iso_date: str) -> str:
    return "昭和" if iso_date < "1989-01-08" else "平成" if iso_date < "2019-05-01" else "令和"


def law_number(jp_date: str, number: str) -> str:
    m = re.match(r"(昭和|平成|令和)\s*(元|\d+)年", jp_date.strip())
    year = "元" if m[2] in ("元", "1") else kanji(int(m[2]))
    return f"{m[1]}{year}年法律第{kanji(int(number))}号"


def page_url(code: str) -> str:
    session = int(code[:3])
    return f"{SOURCE}{code}.htm" if session >= 150 else f"{SOURCE}h{code[:3]}{code[11:]}.htm"


def period(text: str) -> tuple[int, int, int]:
    y, m, d = (int(x) for x in text.split("."))
    return y, m, d


def judge(kind: str, promulgation: str) -> tuple[str, str, str]:
    """(施行日, 取得方法, 備考)。施行日が決まらなければ施行日は空。"""
    if kind.endswith("x"):
        return "", METHOD, "ページ冒頭の法律番号・公布日が台帳と合わないため使わない"
    if kind.startswith("H"):
        return "", "取得不可", f"衆議院の制定法律ページが取れない（HTTP {kind[1:]}）"
    if kind == "P":
        return promulgation, METHOD, "公布の日から施行"
    if kind.startswith("D"):
        d = kind[1:]
        return f"{d[:4]}-{d[4:6]}-{d[6:]}", METHOD, "附則に日付を明示"
    if kind.startswith("R"):
        y, m, d = period(kind[1:])
        got = add_period(promulgation, y, m, d)
        if not got:
            return "", METHOD_CALC, f"公布の日から{y}年{m}月{d}日を経過した日（同じ日の無い月のため計算しない）"
        return got, METHOD_CALC, f"公布の日から{y}年{m}月{d}日を経過した日"
    if kind.startswith("W"):
        y, m, d = period(kind[1:])
        deadline = add_period(promulgation, y, m, d)
        within = f"公布の日から{y}年{m}月{d}日を超えない範囲内で政令で定める日"
        if deadline and same_year(promulgation, deadline):
            return deadline, METHOD_WINDOW, f"{within}。施行日は {promulgation} から {deadline} の間（同じ年・同じ年度）。年単位の判定のため期限の日を置いた"
        return "", METHOD, f"{within}（期限 {deadline or '計算できない'}。年が決まらない）"
    return "", METHOD, KIND_TEXT.get(kind, f"未知の種別 {kind}")


def read_index() -> dict[tuple[str, int], tuple[str, str]]:
    """(元号, 公布の暦年, 法律番号) → (コード, 種別)。法律番号は暦年ごと・改元ごとに振り直されるので、この組で1本に決まる。
    一覧の公布日が台帳と1日ずれる法律があるため、日までは突き合わせない（ページ冒頭の照合は種別の x で済んでいる）。"""
    out = {}
    for line in INDEX.read_text(encoding="utf-8").splitlines():
        code, kind = line.split(" ", 1)
        key = (era_of(f"{code[3:7]}-{code[7:9]}-{code[9:11]}"), code[3:7], int(code[11:]))
        if key in out:
            raise ValueError(f"同じ年・番号のコードが2つある: {out[key][0]} {code}")
        out[key] = (code, kind)
    return out


def build(existing: list[dict], enacted: list[dict], index: dict) -> tuple[list[dict], dict[str, int]]:
    have = {r["id"] for r in existing}
    added, stats = [], {"追加": 0, "施行日あり": 0, "コードなし": 0}
    for r in enacted:
        law_id = f"{r['種別']}-{r['提出回次']}-{r['番号']}"
        if law_id in have:
            continue
        promulgation = iso(r["公布日"]) if r["公布日"].strip() else None
        row = {"id": law_id, "題名": r["題名"], "法令番号": "", "公布日": promulgation or "", "施行日": "", CAND_COL: "",
               "取得方法": "取得不可", "備考": "", "出典URL": "", NEW_COL: ""}
        if promulgation and r["法律番号"].strip():
            row["法令番号"] = law_number(r["公布日"], r["法律番号"])
            hit = index.get((era_of(promulgation), promulgation[:4], int(r["法律番号"])))
            if hit:
                code, kind = hit
                row["施行日"], row["取得方法"], row["備考"] = judge(kind, promulgation)
                row["出典URL"] = page_url(code)
            else:
                row["備考"] = "衆議院の制定法律ページの一覧に見当たらない"
                stats["コードなし"] += 1
        else:
            row["備考"] = "台帳に公布日・法律番号が無い"
            stats["コードなし"] += 1
        stats["追加"] += 1
        stats["施行日あり"] += bool(row["施行日"])
        added.append(row)
    return existing + added, stats


def main() -> None:
    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    with ENACTED.open(encoding="utf-8", newline="") as f:
        enacted = list(csv.DictReader(f))
    rows, stats = build(rows, enacted, read_index())
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(stats, f"施行日あり {sum(1 for r in rows if r['施行日'])} / {len(rows)} 本")


if __name__ == "__main__":
    main()
