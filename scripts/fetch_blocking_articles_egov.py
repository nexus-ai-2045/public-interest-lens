#!/usr/bin/env python3
"""「新技術を止めた法律」の表1に挙げた条文を、e-Gov 法令 API v2 から原本で取り、記載と照らす。

e-Gov が返すのは現行の条文（最新の改正を反映したもの）。制定当時の文言ではないので、
「表1の言う内容が現行条文にあるか」を見る。条番号が改正で動いたものは「条番号が動いた」と書く。

照合は2系統。
  系統A: 条文に、表1の要点を表す言葉（KEY）が全部入っているか。
  系統B: 条の見出し（括弧書き）が、表1の要点と同じ向きか（HEADING に挙げた語のどれかを含むか）。
         古い法律で見出しが無い条は、KEY とは別の言葉（HEADING）が条文にあるかで見る。
両方そろえば「一致」、片方だけなら「保留」、条が無ければ「条が見つからない」。

使い方: python3 scripts/fetch_blocking_articles_egov.py [--out data/acquired/blocking-articles]
"""
import argparse, csv, hashlib, json, time, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

API = "https://laws.e-gov.go.jp/api/2"
# (技術, 法令名, 条, 表1の要点, KEY, HEADING)
ITEMS = [
    ("ライドシェア", "道路運送法", "78", "自家用車での有償運送の原則禁止", ["自家用自動車", "有償"], ["有償運送"]),
    ("ライドシェア", "道路運送法", "4", "一般旅客自動車運送事業の許可", ["許可"], ["一般旅客自動車運送事業の許可"]),
    ("民泊", "旅館業法", "3", "旅館業の許可制", ["許可"], ["旅館業を営もうとする者"]),
    ("民泊新法の上限", "住宅宿泊事業法", "2", "年180日の上限（第3項）", ["百八十日"], ["定義"]),
    ("民泊新法の上限", "住宅宿泊事業法", "18", "条例で更に制限できる", ["条例"], ["条例による住宅宿泊事業の実施の制限"]),
    ("オンライン診療", "医師法", "20", "無診察治療の禁止", ["診察しないで"], ["治療をし"]),
    ("給与のデジタル払い", "労働基準法", "24", "賃金の通貨払い", ["通貨で"], ["賃金の支払"]),
    ("電子契約", "宅地建物取引業法", "35", "重要事項の説明（書面）", ["説明"], ["重要事項の説明等"]),
    ("電子契約", "宅地建物取引業法", "37", "契約の書面の交付", ["書面"], ["書面の交付"]),
    ("株式会社の学校", "学校教育法", "2", "設置者を国・自治体・学校法人に限る", ["学校法人"], ["地方公共団体"]),
    ("AI学習", "著作権法", "30_4", "情報解析などの権利制限（2019施行）", ["情報解析"], ["著作物に表現された思想又は感情の享受を目的としない利用"]),
    ("検索エンジン", "著作権法", "47_5", "検索のための複製（旧第47条の6、2018改正で第47条の5へ）", ["検索"], ["電子計算機による情報処理及びその結果の提供に付随する軽微利用等"]),
    ("解雇の金銭解決", "労働契約法", "16", "解雇権の濫用", ["解雇", "濫用"], ["解雇"]),
    ("混合診療", "健康保険法", "86", "保険外併用療養費", ["保険外併用療養費"], ["保険外併用療養費"]),
    ("ドローン", "航空法", "132_85", "無人航空機の飛行禁止空域（旧第132条、2022改正で第132条の85へ）", ["無人航空機"], ["飛行の禁止空域"]),
    ("ドローン", "航空法", "132_86", "無人航空機の飛行の方法（旧第132条の2）", ["無人航空機"], ["飛行の方法"]),
]


def get(path, params):
    url = f"{API}/{path}?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as r:
        b = r.read()
    time.sleep(1.0)
    return url, b


def law_id(title):
    _, b = get("laws", {"law_title": title, "limit": 20})
    for l in json.loads(b)["laws"]:
        if l["revision_info"]["law_title"] == title:
            return l["law_info"]["law_id"], l["law_info"]["law_num"]
    raise KeyError(title)


def text(n):
    if isinstance(n, str):
        return n
    return "".join(text(c) for c in n.get("children", []))


def find_article(n, num):
    if isinstance(n, dict):
        if n.get("tag") == "Article" and n.get("attr", {}).get("Num") == num:
            return n
        for c in n.get("children", []):
            r = find_article(c, num)
            if r:
                return r
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/acquired/blocking-articles")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    cache, rows = {}, []
    for tech, title, num, point, keys, heads in ITEMS:
        if title not in cache:
            lid, lnum = law_id(title)
            url, b = get(f"law_data/{lid}", {"response_format": "json"})
            cache[title] = (lid, lnum, url, hashlib.sha256(b).hexdigest(), json.loads(b))
        lid, lnum, url, sha, d = cache[title]
        art = find_article(d["law_full_text"], num)
        body = text(art) if art else ""
        caption = ""
        if art:
            for c in art.get("children", []):
                if isinstance(c, dict) and c.get("tag") == "ArticleCaption":
                    caption = text(c)
        a_ok = bool(art) and all(k in body for k in keys)
        b_ok = bool(art) and any(h in (caption or body) for h in heads)
        verdict = "条が見つからない" if not art else ("一致" if a_ok and b_ok else "保留")
        reason = "" if verdict == "一致" else (
            "" if not art else ("要点の言葉が条文に無い" if not a_ok else "見出しが要点と違う") + f"（見出し：{caption or 'なし'}）")
        rows.append({"技術": tech, "法令名": title, "法令番号": lnum, "条": "第" + num.replace("_", "条の") + ("条" if "_" not in num else ""),
                     "表1の要点": point, "判定": verdict, "理由": reason, "条の見出し": caption,
                     "条文（先頭200字）": body[:200], "現行の改正施行日": d["revision_info"].get("amendment_enforcement_date") or "",
                     "出典URL": f"https://laws.e-gov.go.jp/law/{lid}", "API": url, "sha256": sha,
                     "取得日時": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    with open(out / "articles.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    for r in rows:
        print(r["判定"], r["法令名"], r["条"], r["理由"])


if __name__ == "__main__":
    main()
