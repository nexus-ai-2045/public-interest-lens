#!/usr/bin/env python3
"""法律の目的規定（第1条）を e-Gov 法令 API v2 から取る（便益ルール D1）。

入力:  data/derived/loss-v1/loss.csv（損失額の対象。先に処理する）
       data/acquired/enforcement-dates/enforcement.csv（施行日のある法律）
出力:  data/acquired/law-purposes/purposes.csv
       data/acquired/law-purposes/manifest.csv
原本: .local/benefit-data/law-purposes/raw/*.json（git 管理外）

方針:
- 対象法令は enforcement.csv の出典URLにある法令ID。新規法はその法律自身、
  「〜の一部を改正する法律」は改正される法律。
- 版は「現行」（既定の版）と「施行時」（法令の改正履歴で、施行日が一致し、改正法の法令番号が
  当該改正法に一致する、または新規法の初めの版）。e-Gov が保持する版に無いときは取得できずと書く。
- 第1条の原文は条文を平らな文字列にしたもの（改行は段落・号の区切り）。要約や補完はしない。
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.fetch_enforcement_dates import Client, amended_titles, parse_law_num  # noqa: E402

LOSS = ROOT / "data/derived/loss-v1/loss.csv"
ENFORCEMENT = ROOT / "data/acquired/enforcement-dates/enforcement.csv"
OUT_DIR = ROOT / "data/acquired/law-purposes"
RAW_DIR = ROOT / ".local/benefit-data/law-purposes/raw"
OUT_COLS = ["id", "法令番号", "対象法令ID", "版", "第1条の原文", "出典URL",
            "対象法令名", "対象の関係", "版の法令改正履歴ID", "取得状況", "備考"]
ID_RE = re.compile(r"(?:law_revisions|law_file/xml|law_data)/([0-9A-Za-z]+)")
SUB = ("Item", "Subitem1", "Subitem2", "Subitem3")


# ---------- 純粋関数 ----------

def target_ids(source_url: str) -> list[str]:
    """出典URL（; 区切り）から法令IDを重複なく順に取り出す。"""
    out: list[str] = []
    for m in ID_RE.finditer(source_url or ""):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def relation(title: str) -> str:
    return "改正対象の法令" if amended_titles(title) else "新規の法令（自身）"


def _flat(node) -> str:
    if isinstance(node, str):
        return node
    if node.get("tag") == "Rt":
        return ""
    return "".join(_flat(c) for c in node.get("children", []))


def _lines(node, out: list[str]) -> None:
    tag = node.get("tag")
    if tag == "Paragraph" or tag in SUB:
        own = [_flat(c) for c in node.get("children", [])
               if not (isinstance(c, dict) and c.get("tag") in SUB)]
        text = "".join(own).strip()
        if text:
            out.append(text)
        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("tag") in SUB:
                _lines(child, out)
        return
    for child in node.get("children", []):
        if isinstance(child, dict):
            _lines(child, out)


def find_article1(tree):
    """条文の木から第1条（Num が "1"）を探す。無ければ None。"""
    if isinstance(tree, dict):
        if tree.get("tag") == "Article" and tree.get("attr", {}).get("Num") == "1":
            return tree
        for child in tree.get("children", []):
            got = find_article1(child)
            if got is not None:
                return got
    return None


def article_text(article: dict) -> str:
    """第1条の見出し・条番号・各項（号は改行）を平らな文字列にする。"""
    head = title = ""
    for child in article.get("children", []):
        if isinstance(child, dict) and child.get("tag") == "ArticleCaption":
            head = _flat(child)
        if isinstance(child, dict) and child.get("tag") == "ArticleTitle":
            title = _flat(child)
    lines: list[str] = []
    _lines(article, lines)
    if lines and title:
        lines[0] = title + "　" + lines[0]
    return "\n".join(([head] if head else []) + lines)


def pick_revision(revs: dict, own: tuple[str, int, int] | None, date: str):
    """施行日が一致し、改正法の法令番号が一致する（または初めの版で空の）版を返す。一意でなければ None。"""
    hits = []
    for r in revs.get("revisions", []):
        if r.get("amendment_enforcement_date") != date:
            continue
        num = r.get("amendment_law_num")
        if not num or (own is not None and parse_law_num(num) == own):
            hits.append(r)
    ids = {h["law_revision_id"] for h in hits}
    return hits[0] if len(ids) == 1 else None


# ---------- 取得 ----------

def fetch_article(client: Client, ident: str, name: str):
    params = {"law_full_text_format": "json", "elm": "MainProvision-Article[1]"}
    url, status, data = client.get(f"law_data/{ident}", params, name)
    if status != 200:
        return url, status, None, None, data.get("message", "")
    art = find_article1(data.get("law_full_text"))
    return url, status, art, data.get("revision_info", {}).get("law_title", ""), ""


def _row(base: dict, lid: str, ver: str, url: str, status: int, art, title: str, rid: str, msg: str) -> dict:
    row = {**base, "対象法令ID": lid, "版": ver, "出典URL": urllib.parse.unquote(url),
           "対象法令名": title or "", "版の法令改正履歴ID": rid}
    if art is None:
        row.update({"第1条の原文": "", "取得状況": "取得できず",
                    "備考": f"HTTP {status} {msg}".strip() if status != 200 else "第1条が条文に無い（削除・廃止の可能性）"})
    else:
        row.update({"第1条の原文": article_text(art), "取得状況": "取得", "備考": ""})
    return row


def _fail(base: dict, lid: str, ver: str, url: str, title: str, note: str) -> dict:
    return {**base, "対象法令ID": lid, "版": ver, "第1条の原文": "", "出典URL": urllib.parse.unquote(url),
            "対象法令名": title, "版の法令改正履歴ID": "", "取得状況": "取得できず", "備考": note}


def build_rows(client: Client, bills: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for bill in bills:
        own = parse_law_num(bill["法令番号"])
        ids = target_ids(bill["出典URL"])
        date = bill["施行日"]
        base = {"id": bill["id"], "法令番号": bill["法令番号"], "対象の関係": relation(bill["題名"])}
        if not ids:
            rows.append(_fail(base, "", "現行", bill["出典URL"], "", "対象法令IDを enforcement.csv の出典URLから特定できない"))
            continue
        for lid in ids:
            rurl, rstatus, revs = client.revisions(lid)
            url, status, art, title, msg = fetch_article(client, lid, f"cur_{lid}")
            title = title or ""
            rows.append(_row(base, lid, "現行", url, status, art, title, "", msg))
            if not date:
                rows.append(_fail(base, lid, "施行時", rurl, title, "施行日が不明"))
                continue
            rev = pick_revision(revs, own, date) if rstatus == 200 else None
            if rev is None:
                rows.append(_fail(base, lid, "施行時", rurl, title,
                                  f"e-Gov の改正履歴に施行日 {date} と改正法の法令番号が一致する版が一意に無い"
                                  "（e-Gov は概ね2016年以降の版だけ保持）"))
                continue
            rid = rev["law_revision_id"]
            url, status, art, t2, msg = fetch_article(client, rid, f"rev_{rid}")
            rows.append(_row(base, lid, "施行時", url, status, art, t2 or title, rid, msg))
    return rows


def load_bills(limit: int | None) -> list[dict]:
    with ENFORCEMENT.open(encoding="utf-8", newline="") as fh:
        enf = {r["id"]: r for r in csv.DictReader(fh)}
    with LOSS.open(encoding="utf-8", newline="") as fh:
        loss_ids = [r["id"] for r in csv.DictReader(fh)]
    order = [i for i in loss_ids if i in enf and enf[i]["施行日"]]
    order += [i for i, r in enf.items() if r["施行日"] and i not in order]
    bills = [enf[i] for i in order]
    return bills[:limit] if limit else bills


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = Client(RAW_DIR, OUT_DIR / "manifest.csv")
    bills = load_bills(args.limit)
    rows = build_rows(client, bills)
    with (OUT_DIR / "purposes.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    got = sum(1 for r in rows if r["取得状況"] == "取得")
    print(f"bills={len(bills)} rows={len(rows)} 取得={got} 取得できず={len(rows) - got}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
