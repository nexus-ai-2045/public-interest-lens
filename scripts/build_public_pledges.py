"""第50回衆院選（2024-10-27）の公約と、選挙後に成立した法律の対応を公開用にまとめる（/pledges ページ用）。

入力：data/derived/pledges-v1/judgments.json
      党ごとに {party, governing, sourceUrl, sourceNote, items:[{id,text}], a:[{id,status,lawIds}], b:[…]}（独立した2系統の判定）
      app/public/distribution/votes.json（成立法の題名・衆院の会派別賛否）
出力：app/public/distribution/pledges.json
規則：2系統の判定が一致した項目だけを数える。割れたものは「要確認」。
      enacted は2系統に共通する法律IDだけを残し、共通が無ければ要確認。
      点数・順位には入れない。党の公約は党のもので、議員個人には割り当てない。
使い方：python3 scripts/build_public_pledges.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data/derived/pledges-v1/judgments.json"
VOTES = ROOT / "app/public/distribution/votes.json"
OUT = ROOT / "app/public/distribution/pledges.json"
OBSERVED_AT = "2026-10-29"  # 公約資料を取得した日。党の公式ページは後で更新されうる
ELECTION = {"name": "第50回衆議院議員総選挙", "date": "2024-10-27"}
# 衆院の会派名に含まれる語で、党の賛否を決める（votes.json の会派別記録を使う）
KEY = {"自由民主党": "自由民主", "公明党": "公明", "立憲民主党": "立憲", "日本維新の会": "維新", "国民民主党": "国民民主",
       "日本共産党": "共産", "れいわ新選組": "れいわ", "参政党": "参政", "社民党": "社会民主", "日本保守党": "保守"}
STATUS = {"enacted": "enacted", "no_law_found": "none", "no_law_needed": "no_law"}


def stance(law: dict, key: str) -> str:
    shu = law.get("shu")
    if not shu:
        return "none"
    yes = any(key in g for g in shu["yes"])
    no = any(key in g for g in shu["no"])
    return "split" if yes and no else "yes" if yes else "no" if no else "none"


def reconcile(a: dict | None, b: dict | None) -> tuple[str, list[str]]:
    if not a or not b:
        return "review", []
    if a["status"] == b["status"] == "enacted":
        common = sorted(set(a["lawIds"]) & set(b["lawIds"]))
        return ("enacted", common) if common else ("review", sorted(set(a["lawIds"]) | set(b["lawIds"])))
    if a["status"] == b["status"]:
        return STATUS[a["status"]], []
    laws = sorted(set(a["lawIds"]) | set(b["lawIds"]))
    return "review", laws


def main() -> None:
    laws = {x["id"]: x for x in json.loads(VOTES.read_text(encoding="utf-8"))["laws"]}
    parties = []
    for p in json.loads(SRC.read_text(encoding="utf-8")):
        key = KEY[p["party"]]
        a = {r["id"]: r for r in p["a"]}
        b = {r["id"]: r for r in p["b"]}
        items, counts = [], {"enacted": 0, "review": 0, "none": 0, "no_law": 0}
        for it in p["items"]:
            status, ids = reconcile(a.get(it["id"]), b.get(it["id"]))
            counts[status] += 1
            items.append({"id": it["id"], "text": it["text"], "status": status,
                          "judges": [(a.get(it["id"]) or {}).get("status", "none"), (b.get(it["id"]) or {}).get("status", "none")], "laws": [
                {"id": i, "title": laws[i]["title"], "url": laws[i]["url"], "stance": stance(laws[i], key)} for i in ids if i in laws]})
        n = len(items)
        parties.append({"name": p["party"], "governing": p["governing"], "source": {"url": p["sourceUrl"], "note": p.get("sourceNote", ""), "observedAt": OBSERVED_AT},
                        "total": n, "counts": counts, "items": items})
    out = {"schema": "public-pledges/v1", "election": ELECTION,
           "lawsAsOf": max(x["promulgated"] for x in laws.values() if x.get("promulgated") and x["promulgated"] > ELECTION["date"]),
           "notes": [
               "参考表示です。公約の達成率は当てにならない面があり（粒度・与野党の差・法律の中身）、経済に絞った評価や順位には使いません。",
               "点数・順位には入れない別表示です。公約は党のもので、議員個人には割り当てません。",
               "「成立」は、公約に対応する法律が通ったという意味です。中身が公約どおりに実現したかは測っていません。",
               "公約資料は2026-10-29に各党の公式ページ・PDFから取得しました。公式ページが後で更新されると、選挙時点の版と違う可能性があります（取得元URLを各党の欄に載せています）。",
               "各項目に、独立した2系統の判定結果（成立／法律が見当たらない／法律を要さない）を残しています。判断理由や引用は保存していません。判断の材料は法律の題名と目的だけで、条文までは読んでいません。",
               "対応づけは独立した2系統のAI読み取りが一致した項目だけを数えます。割れた項目は「要確認」です。",
               "法律を要さない項目（予算・運用・外交・党内目標など）はこの方法では測れません。割合は分母を2通りで併記します。",
               "日本保守党は、選挙時点（2024-10-27）の公式公約の版を確認できなかったため載せていません（現在の公式ページは選挙後の改訂が混ざる）。",
               "項目の粒度は党の公表形式に従うため、党の間で項目数が違います（細かく割る党ほど「法律不要」の項目が増えます）。割合の党間比較は参考値です。",
               "与党は法案を通せる側です。野党の成立率が低いのは当然で、比較は与党同士・野党同士で見てください。野党は「対応する成立法に賛成したか」も併記します。"],
           "parties": parties}
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {len(parties)}党 {sum(p['total'] for p in parties)}項目")


if __name__ == "__main__":
    main()
