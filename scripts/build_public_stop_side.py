"""技術を止めた側の記録（1,227件）と規制をめぐる判決（40件・保留8件）を公開用の1ファイルにまとめる（/stop-side ページ用）。

入力：data/acquired/blocking-actors/（12本のCSV と verify/status.csv の照合結果）
      data/acquired/court-rulings/（rulings.csv・disputed.csv）
出力：app/public/distribution/stop-side.json
載せる単位：団体・省庁・審議会・自治体など公の主体の記録。個人の氏名は載せない。
  - 審議会の発言者は所属が団体のときだけ団体名を出し（役職・括弧書きは落とす）、学者・弁護士などの個人は区分だけにする。
  - 規制改革会議の省庁ヒアリングは「発言者の官職」の列ごと落とし、省庁名だけにする。
  - 再就職の公表は「離職時の官職」の列ごと落とす（府省と再就職先の組織名だけ）。
  - 審議会の「引用」列（発言そのまま）と判決の「備考」列は載せない。
確かさ：verify/status.csv の照合（確認済み・保留・未照合）をそのまま印にする。保留は誤りの型を理由として付ける。
使い方：python3 scripts/build_public_stop_side.py
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ACTORS = ROOT / "data/acquired/blocking-actors"
COURTS = ROOT / "data/acquired/court-rulings"
OUT = ROOT / "app/public/distribution/stop-side.json"

# 系統（画面の見出し）。キーは配布ファイルの g と画面で共有する。
GROUPS = [
    ("hotline", "規制改革ホットラインの省庁回答", "事業者や団体が出した規制緩和の提案に、所管省庁が「対応不可」「現行制度下で対応可能」などと答えた記録。"),
    ("followup", "規制改革の実施計画フォローアップ", "規制改革推進会議が、実施計画の項目ごとに省庁の対応（反対・慎重・未措置）をまとめた資料。"),
    ("wg", "規制改革会議ワーキンググループの省庁ヒアリング", "ワーキンググループで省庁が反対・慎重と述べた要旨。発言者の官職は載せず、省庁名だけにしています。"),
    ("council", "審議会・検討会で反対・慎重を述べた側", "審議会や検討会で反対・慎重を述べた団体など。個人（学者・弁護士など）は区分だけで、氏名・所属は載せません。"),
    ("amakudari", "府省から所管業界への再就職の公表", "内閣人事局が公表した再就職状況。府省と再就職先の組織名だけを載せ、官職・氏名は載せません。"),
    ("review", "行政事業レビューで廃止・抜本的改善とされた事業", "公開プロセスや秋のレビューで、廃止または抜本的な改善と判断された事業。"),
    ("ordinance", "自治体の上乗せ条例", "民泊などに、法律より厳しい制限を条例で足した自治体。"),
]
FILE_GROUP = {
    "1_regulatory-requests/hotline.csv": "hotline", "1_regulatory-requests/hotline-h26-h27.csv": "hotline", "1_regulatory-requests/hotline-h29-later.csv": "hotline",
    "1_regulatory-requests/council-followup.csv": "followup", "1_regulatory-requests/wg-hearings.csv": "wg",
    "2_shingikai/data-semicon-mobility.csv": "council", "2_shingikai/finance-telecom-ai.csv": "council", "2_shingikai/medical.csv": "council", "2_shingikai/transport-tourism.csv": "council",
    "4_amakudari/reemployment.csv": "amakudari", "5_budget-review/review-findings.csv": "review", "6_local-ordinances/ordinances.csv": "ordinance",
}
STATUS_CODE = {"確認済み": "c", "保留": "h", "未照合": "u"}
# 全文PDFを取得していない判決（docs/reports/court-rulings.md）。系統一致の行のまま残し、本文確認へは上げない。
RULING_NO_FULLTEXT = {"tech-01", "tech-02", "med-06"}
ORG_KINDS = ("業界団体", "労組")
ORG_KINDS_OTHER = ("その他（事業者）", "その他（企業）", "その他（民間シンクタンク）", "その他（消費者団体）", "その他（自治体）")
NO_ORG = re.compile(r"^(議事録|所属|（|\(|委員|構成員|企業|会議資料)")


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def strip_parens(text: str) -> str:
    """括弧書き（入れ子を含む）を落とす。"""
    prev = None
    while prev != text:
        prev = text
        text = re.sub(r"[（(][^（()）]*[）)]", "", text)
    return text


def org_name(text: str, kind: str) -> str:
    """審議会の発言者の所属から、団体名だけを取る。個人の区分や、団体名を取れないときは空にする。"""
    if not (kind.startswith(ORG_KINDS) or kind in ORG_KINDS_OTHER):
        return ""
    name = strip_parens(text).strip()
    if NO_ORG.match(text.strip()) or NO_ORG.match(name):
        return ""
    name = re.split(r"\s", name)[0]
    name = re.sub(r"(代表取締役|取締役.*|常務理事|専務理事|理事長|事務局長|事務局次長|会長代行|会長|代表理事|課長|部長|公共政策チーム)$", "", name)
    name = re.sub(r"(法律事務所)?\s*弁護士$", r"\1", name)
    return name.strip()


def kind_label(kind: str) -> str:
    return kind.replace("その他（", "").rstrip("）") if kind.startswith("その他（") else kind


def actor(rel: str, r: dict[str, str]) -> dict[str, str]:
    """1行ぶんを画面の共通の形（o 主体・d 日付・s 立場・t 件名・x 要旨・k 技術・l 法令・a 相手・u 出典）にする。"""
    g = FILE_GROUP[rel]
    if g == "hotline":
        return {"o": r["所管省庁"], "d": r["受付日"], "s": r["対応分類"], "t": r["提案事項"], "x": r["回答の理由（要旨）"], "k": r["関連技術"], "l": r["該当法令"],
                "a": "個人（氏名は載せない）" if r["提案主体"] == "個人" else r["提案主体"], "u": r["出典URL"], "p": r["ページ"]}
    if g == "followup":
        return {"o": r["所管省庁"], "d": r["年月日"], "s": r["省庁の立場（反対・慎重・未措置）"], "t": r["事項"], "x": r["理由（要旨）"], "k": r["関連技術"], "l": r["該当法令"], "a": r["会議名"], "u": r["出典URL"], "p": r["ページ"]}
    if g == "wg":
        return {"o": r["所管省庁"], "d": r["開催日"], "s": r["立場（反対・慎重）"], "t": " ".join(x for x in (r["会議名"], r["WG名"], r["回"]) if x), "x": r["理由（要旨）"], "k": r["関連技術"], "l": r["該当法令"], "u": r["出典URL"], "p": r["ページ"]}
    if g == "council":
        kind = r["発言者の区分"].strip()
        if kind == "省庁":
            who = r["所管省庁"]
        else:
            who = org_name(r["発言者の所属・肩書"], kind)
            if not who:
                # 団体名を取れない行は、団体か個人か分からないまま区分だけを出す（氏名・所属を推測しない）。
                who = "団体（名称は資料に記載なし）" if kind.startswith(ORG_KINDS) else "個人または所属不明（氏名は載せない）：" + kind_label(kind)
        return {"o": who, "d": r["開催日"], "s": r["立場"], "t": " ".join(x for x in (r["会議名"], r["回"]) if x), "x": r["要旨"], "k": r["関連技術"], "l": r["関連法令"], "a": r["所管省庁"], "u": r["出典URL"], "p": r["ページ"]}
    if g == "amakudari":
        return {"o": r["府省"], "d": r["公表年度"], "s": r["所管関係"], "t": f"再就職先：{r['再就職先']}（{r['再就職先の業種']}）", "x": "", "u": r["出典URL"], "p": r["ページ"]}
    if g == "review":
        budget = "".join(f"　{label} {r[col]}百万円" for label, col in (("予算額", "予算額（百万円）"), ("執行額", "執行額（百万円）")) if r[col])
        return {"o": r["府省"], "d": r["年度"], "s": r["判定（廃止・抜本的改善など）"], "t": r["事業名"] + budget, "x": r["所見の要旨"], "a": r["判定者（外部有識者・公開プロセス・秋のレビュー）"], "u": r["出典URL"], "p": r["ページ"]}
    law_name = r["条例名"]
    return {"o": r["自治体"], "d": r["制定日"] or r["施行日"], "s": "上乗せ条例", "t": law_name, "x": r["制限の内容（区域・期間など）"], "k": r["関連技術"], "u": r["出典URL"]}


def build_actors() -> tuple[list[dict], dict[str, int]]:
    status = {(s["ファイル"], int(s["行"])): s for s in read(ACTORS / "verify/status.csv")}
    rows: list[dict] = []
    for rel in FILE_GROUP:
        for i, r in enumerate(read(ACTORS / rel), 1):
            st = status[(rel, i)]
            a = {k: v.strip() for k, v in actor(rel, r).items() if v and v.strip()}
            a["g"], a["v"] = FILE_GROUP[rel], STATUS_CODE[st["照合"]]
            if st["照合"] == "保留" and st["誤りの型"]:
                a["r"] = st["誤りの型"]
            a["h"] = st["行ハッシュ"]
            if not re.match(r"^https://", a.get("u", "")):
                a.pop("u", None)
            rows.append(a)
    counts = {"actors": len(rows), "confirmed": sum(a["v"] == "c" for a in rows), "held": sum(a["v"] == "h" for a in rows), "unchecked": sum(a["v"] == "u" for a in rows),
              "withLink": sum("u" in a for a in rows)}
    return rows, counts


def build_rulings() -> tuple[list[dict], list[dict]]:
    rulings = []
    for r in read(COURTS / "rulings.csv"):
        link = r["判例URL"] if r["判例URL"].startswith("https://www.courts.go.jp/") else ""
        later = r["その後の変化"].strip()
        rulings.append({k: v for k, v in {
            "id": r["id"], "name": r["通称"], "rule": r["規制"], "agency": r["所管"], "field": r["分野"], "court": r["裁判所"], "date": r["判決日"], "no": r["事件番号"],
            "kind": r["裁判種別"], "result": r["結果"], "judge": r["規制への判断"], "summary": r["判断の要旨"], "after": "" if later in ("", "未確認") else later,
            "u": link, "check": (re.match(r"^2系統一致（[^）]*）", r["確認状況"]) or re.match(r"^[^。]*", r["確認状況"])).group(0), "fulltext": "" if r["id"] not in RULING_NO_FULLTEXT else "no"}.items() if v})
    held = [{"id": r["id"], "name": r["通称"], "reason": r["理由"]} for r in read(COURTS / "disputed.csv")]
    return rulings, held


def build() -> dict:
    actors, counts = build_actors()
    rulings, held = build_rulings()
    counts.update({"rulings": len(rulings), "rulingsHeld": len(held)})
    return {
        "schema": "public-stop-side/v1",
        "notes": [
            "ここにあるのは、新しい技術やサービスを止めた側（所管省庁・審議会で慎重を述べた団体・再就職先・効果の出ない事業・上乗せ条例）の記録です。誰かの責任を決めるものではなく、点数にも入れていません。",
            "印の見方：確認済みは、原本と機械の照合＋AI2系統がすべて一致した行です。保留は照合で食い違い（ページ違い・値の違いなど）が見つかった行で、理由を添えました。未照合はまだ原本と照らしていない行です。保留と未照合の中身は、そのまま正しいとは言えません。",
            "一次資料（官公庁の資料）へのリンクがある行だけリンクを出しています。出典のURLが無い、またはhttpsでない行は「一次資料のリンクなし」と書いています。",
            "個人の氏名は載せていません。審議会の発言者は団体のときだけ団体名を出し、学者・弁護士などの個人は区分だけです。省庁ヒアリングの官職、再就職した人の官職、審議会の発言そのままの引用も載せていません。",
            "判決は、規制が裁判で退けられた例と維持された例です。判決日・事件番号・規制への判断の3つが、独立した2系統で一致したものだけを載せ、食い違うものは保留として理由だけ示します。「2系統一致」は原本の全文確認が済んだという意味ではありません。",
        ],
        "counts": counts,
        "groups": [{"key": k, "label": label, "about": about} for k, label, about in GROUPS],
        "actors": actors,
        "rulings": rulings,
        "rulingsHeld": held,
    }


def main() -> int:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(data["counts"], f"{OUT.stat().st_size // 1024}KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
