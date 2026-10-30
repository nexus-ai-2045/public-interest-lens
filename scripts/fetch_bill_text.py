"""未成立の提出法案（評価対象）の本文を衆議院の議案本文ページから取る。実在確認（題名・回次・号数の一致）が取れないものは取らない。

URL：.../honbun/houan/g{回次3桁}{05衆|06参|09閣}{番号3桁}.htm（既存の取得物で確かめた規則）
確認：ページの題名＝scale.csv の題名、かつ「第N回」「衆|参|閣第N号」の見出しが一致。一致しない行は本文を保存せず理由を残す。
出力：本文 .local/bill-text/<id>.txt（Git に入れない）、索引 data/derived/unenacted-bills-v1/bill-text-index.csv
使い方：python3 scripts/fetch_bill_text.py [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import html
import re
import time
import urllib.request
from pathlib import Path

SCALE = Path("data/derived/unenacted-bills-v1/scale.csv")
OUT = Path(".local/bill-text")
INDEX = Path("data/derived/unenacted-bills-v1/bill-text-index.csv")
BASE = "https://www.shugiin.go.jp/internet/itdb_gian.nsf/html/gian/honbun/houan/"
CODE = {"衆法": ("05", "衆"), "参法": ("06", "参"), "閣法": ("09", "閣")}
KAN = "〇一二三四五六七八九"


def kan(n: int) -> str:
    """号数・回次の漢数字（ページの見出し形式：第一四七回、衆第三三号）。位取りでなく数字の並び。"""
    return "".join(KAN[int(c)] for c in str(n))


def kan_pos(n: int) -> str:
    """位取りの漢数字（第三十三号）。ページによってどちらの形式もあるため両方を許す。"""
    d = ["", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    h, t, o = n // 100, n // 10 % 10, n % 10
    return (d[h] + "百" if h > 1 else "百" if h == 1 else "") + (d[t] + "十" if t > 1 else "十" if t == 1 else "") + d[o]


def page_lines(raw: bytes) -> list[str]:
    t = raw.decode("cp932", errors="replace")
    t = re.sub(r"(?s)<script.*?</script>|<style.*?</style>|<!--.*?-->", "", t)
    t = html.unescape(re.sub(r"<[^>]+>", "\n", t))
    return [x.strip() for x in t.split("\n") if x.strip()]


def verify(lines: list[str], title: str, kind: str, kai: int, num: int) -> str:
    """一致なら空、不一致なら理由。"""
    page_title = re.sub(r"\s", "", lines[0].lstrip("●")) if lines else ""  # 新しいページは題名の頭に「●」が付く
    if not lines or page_title != re.sub(r"\s", "", title):
        return f"題名不一致（ページ：{lines[0] if lines else '空'}）"
    sh = CODE[kind][1]
    if not any(l in (f"第{kan(kai)}回", f"第{kan_pos(kai)}回") for l in lines[:40]):
        return "回次の見出しが一致しない"
    if not any(l in (f"{sh}第{kan(num)}号", f"{sh}第{kan_pos(num)}号") for l in lines[:40]):
        return "号数の見出しが一致しない"
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(SCALE.open(encoding="utf-8")) if r["判定"] == "評価対象" and r["id"].rsplit("-", 1)[-1]]
    if a.limit:
        rows = rows[: a.limit]
    OUT.mkdir(parents=True, exist_ok=True)
    done = {}
    if INDEX.exists():
        done = {r["id"]: r for r in csv.DictReader(INDEX.open(encoding="utf-8"))}
    for r in rows:
        if r["id"] in done and done[r["id"]]["確認"] == "一致":
            continue
        kind, kai, num = r["種別"], int(r["提出回次"]), int(r["id"].rsplit("-", 1)[-1])
        url = f"{BASE}g{kai:03d}{CODE[kind][0]}{num:03d}.htm"
        try:
            lines = page_lines(urllib.request.urlopen(url, timeout=30).read())
            why = verify(lines, r["題名"], kind, kai, num)
        except Exception as e:  # noqa: BLE001 404 など。理由に型名を残す
            lines, why = [], f"取得できず（{type(e).__name__}）"
        n = 0
        if not why:
            i = next(k for k, l in enumerate(lines) if l.endswith("号") and "第" in l)
            body = [l for l in lines[i + 1:] if not l.startswith(("ホームページについて", "Webアクセシビリティ"))]
            (OUT / f"{r['id']}.txt").write_text("\n".join(body[:-1] if body else body), encoding="utf-8")
            n = sum(len(x) for x in body)
        done[r["id"]] = {"id": r["id"], "題名": r["題名"], "本文URL": url, "確認": "一致" if not why else "不一致", "理由": why, "文字数": n}
        time.sleep(0.5)
    with INDEX.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["id", "題名", "本文URL", "確認", "理由", "文字数"], lineterminator="\n")
        w.writeheader()
        w.writerows(done.values())
    ok = sum(v["確認"] == "一致" for v in done.values())
    print(f"{len(done)} 本中、実在確認できた {ok} 本 → {INDEX}")


if __name__ == "__main__":
    main()
