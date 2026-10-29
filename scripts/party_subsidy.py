"""政党交付金の使途等報告書（総務省・索引 SK）を取り込む。

政党本部と政党支部が受けた政党交付金の総額・前年の基金残高・支出・本年末の基金残高と、
交付元（党本部など）を、支部の代表者（議員が多い）に結ぶ。点数には使わない。

段：
  urls     索引 index.csv から対象年の PDF の一覧を作る
  render   PDF の1〜3頁を画像にする（その1＝表紙、その2＝収支の状況、その3＝支出項目別）
  build    独立した2つの AI の読み手（A・B）の結果を突き合わせ、食い違いは3つ目（C）が
           A か B と一致したものだけ採る。さらに収支の算術（①-③+②-⑧=0、③=④+⑤）で検査する
読み手の結果は .local/party-subsidy/line-{a,b,c}/<PDF のファイル名の幹>.json（形は docs/政党交付金の使途等報告書.md）。

個人の扱い：事務所の住所・会計責任者・事務担当者は読まず、出力にも残さない。
代表者の氏名は、人物ID（議員）に結べたときだけ出す。結べなければ「（未照合）」。
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "data/acquired/political-funds/index.csv"
PERSONS = ROOT / "data/derived/person-ids/persons.csv"
WORK = ROOT / ".local/party-subsidy"
OUT = ROOT / "data/derived/party-subsidy"
# 索引ページの名前 SKyyyymmdd（9〜10月公表）→ 何年分か。SK20260925 は令和7年（2025年）分。
YEAR_OF_PAGE = {"SK20260925": 2025, "SK20250926": 2024, "SK20240927": 2023, "SK20230929": 2022, "SK20220930": 2021}
NUMS = ("交付金総額", "前年末基金残高", "交付金による支出総額", "交付金支出充当額", "基金支出充当額", "本年末基金残高")


def norm_name(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or ""))


def stem_of(url: str) -> str:
    return url.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def rows_for(page: str) -> list[dict]:
    with INDEX.open(encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if f"/{page}" in r["索引ページURL"] and "/TK/" in r["PDF_URL"]]


def cmd_urls(args) -> None:
    rows = rows_for(args.page)
    sys.stdout.write("\n".join(r["PDF_URL"] for r in rows) + "\n")


def cmd_render(args) -> None:
    pdf_dir, img_dir = Path(args.pdf_dir), Path(args.img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        if (img_dir / f"{pdf.stem}-1.png").exists():
            continue
        subprocess.run(["pdftoppm", "-r", str(args.dpi), "-f", "1", "-l", "3", "-png", str(pdf), str(img_dir / pdf.stem)], check=True)
        for p in img_dir.glob(f"{pdf.stem}-0?.png"):  # pdftoppm は桁をそろえる
            p.rename(img_dir / f"{pdf.stem}-{int(p.stem.rsplit('-', 1)[1])}.png")


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?[\d,]+", v.strip()):
        return int(v.replace(",", ""))
    return None


def _read(path: Path):
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


EXPENSE_KEYS = ("支部政党交付金", "人件費", "光熱水費", "備品消耗品費", "事務所費", "組織活動費", "選挙関係費", "機関紙誌", "調査研究費", "寄附金", "その他の経費")


def _flows(d: dict) -> list:
    out = []
    for f in d.get("交付元") or []:
        if isinstance(f, dict) and _num(f.get("金額")) is not None:
            out.append((norm_name(str(f.get("交付をした者", ""))), norm_name(str(f.get("年月日", ""))), _num(f["金額"])))
    return sorted(out)


def _canon(d: dict) -> dict:
    """比較用の形。金額は整数に、名前は NFKC・空白なし。交付元の一覧は別に突き合わせる（続きの頁があり不完全なことがある）。"""
    exp = d.get("支出") if isinstance(d.get("支出"), dict) else {}
    return {
        "名称": norm_name(str(d.get("名称", ""))),
        "代表者": norm_name(str(d.get("代表者", ""))),
        "区分": norm_name(str(d.get("区分", ""))),
        **{k: _num(d.get(k)) for k in NUMS},
        "支出": {k: _num(exp.get(k)) for k in (*EXPENSE_KEYS, "合計")},
    }


def _arith(c: dict) -> list[str]:
    """収支の算術の検査。式の項がそろっているものだけ検べ、食い違いを返す（頁が欠けた PDF は欠けた式を飛ばす）。"""
    t, p, e, a, b, z = (c[k] for k in NUMS)
    bad = []
    if None not in (e, a, b) and e != a + b:
        bad.append("③≠④+⑤")
    if None not in (t, p, e, z) and t - e + p - z != 0:
        bad.append("①-③+②-⑧≠0")
    x = c["支出"]
    if all(x[k] is not None for k in EXPENSE_KEYS) and x["合計"] is not None and sum(x[k] for k in EXPENSE_KEYS) != x["合計"]:
        bad.append("支出の費目の和≠合計")
    return bad


def completeness(c: dict) -> str:
    have_p2 = all(c[k] is not None for k in NUMS)
    have_p3 = all(c["支出"][k] is not None for k in (*EXPENSE_KEYS, "合計"))
    return "完全" if have_p2 and have_p3 else "一部の頁のみ"


def adopt(a: dict | None, b: dict | None, c: dict | None):
    ca, cb = (_canon(a) if a else None), (_canon(b) if b else None)
    if ca and cb and ca == cb:
        return ca, "A・B一致", (_flows(a) if _flows(a) == _flows(b) else [])
    if c:
        cc = _canon(c)
        for x, raw, name in ((ca, a, "C・A一致"), (cb, b, "C・B一致")):
            if x and cc == x:
                return x, name, (_flows(raw) if _flows(raw) == _flows(c) else [])
    return None, "読み手が不一致または未回答", []


KANSUJI = {"〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def kansuji(text: str):
    """「十九」→19（百未満）。読めなければ None。"""
    if text.isdigit():
        return int(text)
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = KANSUJI.get(head, 1) if head else 1
        ones = KANSUJI.get(tail, 0) if tail else 0
        return tens * 10 + ones if head in ("", *KANSUJI) and tail in ("", *KANSUJI) else None
    return KANSUJI.get(text) if len(text) == 1 else None


PREFS = ("北海道 青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 東京 神奈川 新潟 富山 石川 福井 山梨 長野 岐阜 静岡 愛知 三重 滋賀 京都 大阪 兵庫 奈良 和歌山 "
         "鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄").split()
DISTRICT = re.compile(r"(" + "|".join(PREFS) + r")[都道府県]?第([〇一二三四五六七八九十\d]+)選挙区支部")


def district_of(branch_name: str):
    """衆院の選挙区支部の名称（○○県第十九選挙区支部）から persons.csv と同じ形（東京19）を作る。参議院選挙区は対象外。"""
    m = DISTRICT.search(norm_name(branch_name))
    n = kansuji(m.group(2)) if m else None
    return f"{m.group(1)}{n}" if n else None


def load_persons() -> dict[str, list[dict]]:
    by: dict[str, list[dict]] = {}
    with PERSONS.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if not r.get("人物ID"):
                continue
            for n in {r["氏名"], *(r.get("別表記") or "").split("|")}:
                if n:
                    by.setdefault(norm_name(n), []).append(r)
    return by


def cmd_build(args) -> None:
    year = YEAR_OF_PAGE[args.page]
    rows = {stem_of(r["PDF_URL"]): r for r in rows_for(args.page)}
    persons = load_persons()
    out, stats = [], {}
    for stem, r in rows.items():
        got = [_read(WORK / line / f"{stem}.json") for line in ("line-a", "line-b", "line-c")]
        c, how, flows = adopt(*got)
        bad = []
        if c:
            bad = _arith(c)
            if bad:
                c, how = None, "算術の検査で不一致（" + "・".join(bad) + "）"
        stats[how.split("（")[0]] = stats.get(how.split("（")[0], 0) + 1
        if not c:
            out.append({"年分": year, "名称": r["団体名"], "採用": how, "PDF_URL": r["PDF_URL"]})
            continue
        # 代表者 → 人物ID（氏名が1人に決まるときだけ）。支部の名称は索引の名前と読み手の名称が一致したときだけ使う
        hit = persons.get(c["代表者"], [])
        pid = hit[0]["人物ID"] if len(hit) == 1 else ""
        dist = district_of(r["団体名"])
        sure = "氏名と選挙区が一致" if pid and dist and hit[0]["選挙区"] == dist else ("氏名のみ一致" if pid else "")
        out.append({
            "年分": year, "名称": r["団体名"], "区分": c["区分"], "代表者": c["代表者"] if pid else "（未照合）", "人物ID": pid, "結びの確度": sure,
            **{k: c[k] for k in NUMS},
            **{"支出_" + k: c["支出"][k] for k in (*EXPENSE_KEYS, "合計")},
            "主な交付元": "；".join(sorted({f[0] for f in flows})) if flows else "",
            "採用": how, "検査": completeness(c), "PDF_URL": r["PDF_URL"],
        })
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["年分", "名称", "区分", "代表者", "人物ID", "結びの確度", *NUMS, *("支出_" + k for k in (*EXPENSE_KEYS, "合計")), "主な交付元", "採用", "検査", "PDF_URL"]
    with (OUT / f"branch-subsidy-{year}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    adopted = [o for o in out if o.get("交付金総額") is not None]
    summary = {
        "年分": year, "対象PDF": len(rows), "採用": len(adopted), "採用経路の内訳": stats,
        "人物IDに結べた支部": sum(1 for o in adopted if o["人物ID"]),
        "うち氏名と選挙区が一致": sum(1 for o in adopted if o.get("結びの確度") == "氏名と選挙区が一致"),
        "交付金総額の合計": sum(o["交付金総額"] for o in adopted),
    }
    (OUT / f"summary-{year}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("urls", cmd_urls), ("build", cmd_build)):
        p = sub.add_parser(name)
        p.add_argument("--page", default="SK20260925")
        p.set_defaults(fn=fn)
    p = sub.add_parser("render")
    p.add_argument("--pdf-dir", required=True)
    p.add_argument("--img-dir", required=True)
    p.add_argument("--dpi", type=int, default=80)
    p.set_defaults(fn=cmd_render)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
