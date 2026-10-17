"""分野の拡張の見積り（docs/提案/分野の拡張-v1.md の題名の語を、対応表なしの実質法に当てて本数を数える）。

既存の出力は一切変えない。読むのは次の3つだけで、書くのは estimate.csv だけ。
  - data/derived/bill-triage-v1/triage.csv（種類・分野。種類が新規／実質改正で分野が対応表なしの法律が対象）
  - data/acquired/bill-census-full/enacted.csv（題名）
  - data/derived/bill-triage-v2/labels-line2.csv（既存の分野が変わらないかの確認だけに使う）

規則は bill-triage-v2 の D1・D2 と同じ。
  D1：まず既存8分野の語（scripts/triage_v2_line2.py の FIELD_WORDS）で現行どおり決める。既存の規則で対応表なしになる題名にだけ、
      新分野の語を当て、題名で最も前に出る語の分野に決める。語が無ければ対応表なし。
      最初の位置に別々の分野の語が重なれば保留（D5。優先順位は決めない）。
  D2：「及び〜設置法」「及び〜整備法」を除いた題名の最初の法律で決める。
既存8分野の語が当たる法律は、現行の規則どおり既存分野として数え、新分野の語は当てない（既存の結果を変えないため）。

これは語の表を作ったあとの当てはめ（学習内）で、新しいデータでの検証ではない。語の表は題名を見て調整してある。

使い方（リポジトリのルートで）：python3 scripts/estimate_field_expansion.py
"""
from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.triage_v2_line2 import _FIELD_WORDS, NO_FIELD, first_law  # noqa: E402

TRIAGE = ROOT / "data/derived/bill-triage-v1/triage.csv"
ENACTED = ROOT / "data/acquired/bill-census-full/enacted.csv"
LABELS_LINE2 = ROOT / "data/derived/bill-triage-v2/labels-line2.csv"
OUT = ROOT / "data/derived/field-expansion-estimate/estimate.csv"

HOLD = "保留"
SUBSTANTIVE = ("新規", "実質改正")

# 新分野：(指標, [(語, 対応), ...])。語は「題名にそのまま含まれるか」だけで当てる。対応は 直接 か 代理。
NEW_FIELDS: dict[str, tuple[str, list[tuple[str, str]]]] = {
    "農林水産": ("農林水産業の付加価値", [
        *[(w, "直接") for w in ("農業", "農地", "農林", "林業", "森林", "水産", "漁業", "漁船", "漁港", "漁場", "畜産", "家畜", "酪農",
                                "農産物", "農薬", "肥料", "種苗", "農協", "農業協同組合", "森林組合", "漁業協同組合", "植物防疫", "米穀", "木材", "農村", "牧野", "農作物", "原料乳", "お茶", "花き", "真珠", "棚田", "土地改良", "養殖", "養ほう", "野菜", "生産調整", "国有林野", "農山漁村", "農住")],
        *[(w, "代理") for w in ("食料", "食糧", "飼料")],
    ]),
    "建設": ("建設業の付加価値", [
        *[(w, "直接") for w in ("建設", "建築", "公共工事", "工事", "測量")],
        *[(w, "代理") for w in ("都市計画", "都市再生", "都市再開発", "市街地", "区画整理", "宅地造成", "耐震", "国土強靱化", "国土形成", "公共施設", "無電柱化", "基盤整備", "河川", "海岸", "砂防", "景観", "歴史的風致", "首都圏整備", "津波防災地域")],
    ]),
    "住宅・不動産": ("不動産業の付加価値", [
        *[(w, "代理") for w in ("住宅", "不動産", "賃貸", "借地", "借家", "宅地建物", "マンション", "区分所有", "土地基本", "土地収用", "建物", "居住", "地価", "空家", "住生活")],
    ]),
    "教育": ("教育の付加価値", [
        *[(w, "代理") for w in ("教育", "学校", "大学", "義務教育", "奨学", "学習", "教職員", "幼稚園", "就学", "学級", "教科用", "留学", "育英")],
    ]),
    "医療・福祉": ("保健衛生・社会事業の付加価値", [
        *[(w, "代理") for w in ("医療", "医師", "歯科", "薬事", "医薬", "薬剤師", "薬局", "看護", "介護", "福祉", "保健", "健康増進", "感染症の予防", "予防接種",
                                "精神保健", "老人", "母子", "難病", "臓器", "献血", "血液", "保育", "子育て", "児童福祉", "障害福祉", "障害者総合支援",
                                "障害児", "児童虐待", "医薬品", "診療", "病院", "原子爆弾被爆者", "結核", "検疫",                                 "狂犬病", "社会福祉", "栄養", "生活衛生", "母体", "あん摩", "柔道整復", "臨床", "移植", "造血幹細胞", "死因究明", "アレルギー", "インフルエンザ", "自殺対策", "障害者自立支援", "障害者の日常生活", "がん対策", "がん登録", "肝炎", "循環器病", "公認心理師", "高齢者虐待", "次世代育成", "子どもの貧困", "生活困窮者")],
    ]),
    "製造業": ("製造業の付加価値", [
        *[(w, "直接") for w in ("製造", "工業", "鉱工業", "工場", "繊維", "化学物質", "計量", "産業標準", "火薬", "高圧ガス", "家庭用機器")],
        *[(w, "代理") for w in ("容器包装", "再商品化", "食品", "たばこ", "電気用品", "消費生活用", "企業立地", "産業集積", "伝統的工芸品", "アルコール", "酒類")],
    ]),
    "商業": ("卸売・小売業の付加価値", [
        *[(w, "直接") for w in ("小売", "卸売", "商店街", "商業", "流通", "古物", "質屋")],
        *[(w, "代理") for w in ("訪問販売", "特定商取引", "販売", "中心市街地", "景品", "表示")],
    ]),
    "専門サービス・研究開発": ("専門・科学技術、業務支援サービス業の付加価値", [
        *[(w, "直接") for w in ("弁護士", "司法書士", "行政書士", "税理士", "公認会計士", "弁理士", "社会保険労務士", "土地家屋調査士", "建築士", "技術士",
                                "不動産鑑定", "警備業", "探偵", "研究開発", "試験研究", "科学技術", "研究所", "研究施設", "産業技術")],
        *[(w, "代理") for w in ("特許", "実用新案", "意匠", "商標", "知的財産", "著作権")],
    ]),
    "文化・娯楽・生活サービス": ("その他のサービス業の付加価値", [
        *[(w, "代理") for w in ("文化", "芸術", "文化財", "スポーツ", "体育", "競馬", "自転車競技", "小型自動車競走", "モーターボート競走", "興行",
                                "遊技", "風俗", "公衆浴場", "宗教", "映画", "博物館", "図書館", "劇場", "オリンピック", "万国博覧会", "博覧会", "墓地", "理容", "美容", "クリーニング", "美術", "競技大会", "温泉")],
    ]),
    "水道・廃棄物": ("電気・ガス・水道・廃棄物処理業の付加価値", [
        *[(w, "代理") for w in ("水道", "下水道", "廃棄物", "再資源化", "リサイクル", "循環型社会", "雨水", "プラスチック", "浄化槽", "汚泥", "資源の有効")],
    ]),
}

# 新分野を作らず、対応表なしのままにする理由（市場の産業が無い、または移転・規則そのもの）。数えるための分類で、分野の決定には使わない。
# 上から順に、題名に最初に当たった理由を付ける。
REMAIN_REASONS: list[tuple[str, tuple[str, ...]]] = [
    ("選挙・政治（市場の産業が無い）", ("選挙", "政治資金", "政党", "国会", "議院", "議員")),
    ("司法・刑事・民事手続（市場の産業が無い）", ("刑法", "刑事", "民法", "民事", "裁判", "訴訟", "少年", "検察", "犯罪", "更生", "保護司", "受刑", "戸籍", "登記", "仲裁",
                                  "法律扶助", "法律支援", "後見", "破産", "処罰", "ストーカー", "暴力", "会社法", "商法", "国籍", "出入国", "旅券", "犯罪被害")),
    ("防衛・外交・国際（市場の産業が無い）", ("自衛隊", "武力攻撃", "防衛", "安全保障", "条約", "協定", "経済連携", "国際連合", "国際人道", "国際協力", "平和", "北方領土", "拉致",
                                 "在外", "外国", "海外", "日本国")),
    ("公務員・行政組織・地方制度（非市場。付加価値は費用で測る）", ("公務員", "国会職員", "裁判官", "共済", "地方自治", "地方公共団体", "市町村", "地方交付", "地方税", "地方法人", "特別区域", "行政機関",
                                         "独立行政法人", "国有財産", "公文書", "情報公開", "政策の評価", "公益通報", "公益社団", "特定非営利", "特別措置法")),
    ("年金・給付金・手当・税（所得の移転）", ("年金", "給付金", "手当", "弔慰金", "扶助", "特別給付", "一時金", "税", "租税", "寄附", "交付金", "補償", "義援金")),
    ("災害・防災・復興（市場の産業が無い）", ("震災", "津波", "地震", "防災", "火山", "水防", "被災", "復興", "災害")),
    ("環境保全・自然（市場の産業が無い）", ("環境", "自然", "大気", "水質", "鳥獣", "生物", "温室効果", "動物", "オゾン", "悪臭", "海洋", "南極", "気候")),
    ("消費者・競争・企業一般（分野横断）", ("消費者", "消費生活", "不正競争", "私的独占", "中小企業", "小規模企業", "企業", "事業", "協同組合", "特区", "特別区")),
    ("人権・社会一般", ("差別", "障害者", "人権", "男女", "共生", "子ども", "青少年", "ホームレス", "自殺", "犯罪被害者", "孤独")),
]


def remain_reason(title: str) -> str:
    for reason, words in REMAIN_REASONS:
        if any(w in title for w in words):
            return reason
    return "その他（語なし）"


# 手で付けた語の表（上）を引くための索引。(分野, 語, 対応)
NEW_WORDS: list[tuple[str, str, str]] = [(f, w, m) for f, (_, ws) in NEW_FIELDS.items() for w, m in ws]
EXISTING_WORDS: list[tuple[str, str]] = [(f, w) for f, ws in _FIELD_WORDS.items() for w in ws.split("、")]


def _earliest(hits: list[tuple[int, str, str, str]]) -> tuple[str, str, str, str] | None:
    """最も前の位置の語を返す。同じ位置に別の分野の語が重なれば ("保留", 語…, "", "")。同じ分野の語が重なれば長い語。"""
    if not hits:
        return None
    pos = min(h[0] for h in hits)
    first = [h for h in hits if h[0] == pos]
    # 同じ位置の語が別の語の一部（土地／土地改良）なら、短い方は長い方の言い換えとして落とす。
    first = [h for h in first if not any(h[2] != g[2] and h[2] in g[2] for g in first)]
    if len({h[1] for h in first}) > 1:
        return HOLD, "、".join(h[2] for h in first), "", ""
    _, field, word, match = max(first, key=lambda h: len(h[2]))
    return field, word, match, ""


def classify(title: str) -> dict:
    """題名から分野を決める。D2→D1→D5。
    1) 既存8分野の語だけで現行どおり決める（bill-triage-v2 と同じ。既存の結果は変えない）。
    2) 既存の規則で対応表なしになる題名にだけ、新分野の語を当てる。新分野の語どうしが同じ位置で重なれば保留（D5）。
    kind：既存（既存の規則で分野が決まる）／新／保留／対応表なし。
    """
    text = first_law(title)
    out = {"kind": NO_FIELD, "field": NO_FIELD, "word": "", "match": "", "note": "", "d2": text != title}
    old = _earliest([(text.find(w), f, w, "") for f, w in EXISTING_WORDS if w in text])
    if old:
        if old[0] == HOLD:
            out.update(kind=HOLD, field=HOLD, word=old[1], note="D5：既存8分野の語が最初の位置で重なるため保留")
        else:
            out.update(kind="既存", field=old[0], word=old[1])
        return out
    hits = [(text.find(w), f, w, m) for f, w, m in NEW_WORDS if w in text]
    new = _earliest(hits)
    if new:
        if new[0] == HOLD:
            out.update(kind=HOLD, field=HOLD, word=new[1], note="D5：新分野の語が最初の位置で重なるため保留")
        else:
            others = sorted({h[1] for h in hits} - {new[0]})
            out.update(kind="新", field=new[0], word=new[1], match=new[2], note=("他に当たった新分野の語：" + "、".join(others)) if others else "")
    return out


def load_targets() -> list[dict]:
    titles = {}
    with ENACTED.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            titles[f"{r['種別']}-{r['提出回次']}-{r['番号']}"] = r["題名"]
    out = []
    with TRIAGE.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["種類"] in SUBSTANTIVE and r["分野"] == NO_FIELD and r["結果"] == "評価対象外":
                out.append({"id": r["id"], "題名": titles[r["id"]]})
    return out


def estimate(targets: list[dict]) -> list[dict]:
    rows = []
    for t in targets:
        c = classify(t["題名"])
        if c["kind"] == "新":
            field, indicator = c["field"], NEW_FIELDS[c["field"]][0]
        elif c["kind"] == "既存":
            field, indicator = "（既存の規則で）" + c["field"], ""
        elif c["kind"] == HOLD:
            field, indicator = HOLD, ""
        else:
            field, indicator = NO_FIELD, ""
            c["note"] = remain_reason(t["題名"])
        rows.append({"id": t["id"], "題名": t["題名"], "新分野": field, "指標": indicator, "一致した語": c["word"],
                     "対応": c["match"], "備考": c["note"]})
    return rows


def regression(path: Path = LABELS_LINE2) -> tuple[int, int, int]:
    """labels-line2.csv（既存の規則の結果）に新しい語を足したとき。(分野が決まっている本数, 既存分野が変わる本数, 対応表なし→新分野になる本数)"""
    if not path.exists():
        return 0, 0, 0
    n = changed = gained = 0
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            old = r["系統2_分野"]
            # 新分野は bill-triage-v2 に取り込み済み（空欄・保留・新分野の行は「既存分野が変わるか」の確認に使わない）。
            if old in ("", HOLD) or old in NEW_FIELDS:
                continue
            c = classify(r["題名"])
            if old != NO_FIELD:
                n += 1
                if c["kind"] != "既存" or c["field"] != old:
                    changed += 1
            elif c["kind"] == "新":
                gained += 1
    return n, changed, gained


HEADER = ["id", "題名", "新分野", "指標", "一致した語", "対応", "備考"]


def write(rows: list[dict], dst: Path = OUT) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for r in rows:
            w.writerow([r[h] for h in HEADER])


def main() -> None:
    targets = load_targets()
    rows = estimate(targets)
    write(rows)
    cnt = Counter(r["新分野"] for r in rows)
    print(f"対象（種類が新規／実質改正で、振り分け v1 が対応表なし）：{len(rows)} 本")
    print("--- 新分野 ---")
    for f in NEW_FIELDS:
        k = [r for r in rows if r["新分野"] == f]
        d = sum(1 for r in k if r["対応"] == "直接")
        print(f"{f}（{NEW_FIELDS[f][0]}）：{len(k)} 本（直接 {d}／代理 {len(k) - d}）")
    new_total = sum(cnt[f] for f in NEW_FIELDS)
    print(f"新分野の合計：{new_total} 本")
    existing = [r for r in rows if r["新分野"].startswith("（既存の規則で）")]
    print(f"既存の規則の語が先に当たる（既存分野に入る）：{len(existing)} 本")
    for f, n in Counter(r["新分野"] for r in existing).most_common():
        print(f"  {f}：{n}")
    print(f"保留（最初の語の位置で分野が重なる）：{cnt[HOLD]} 本")
    print(f"対応表なしのまま：{cnt[NO_FIELD]} 本")
    for reason, n in Counter(r["備考"] for r in rows if r["新分野"] == NO_FIELD).most_common():
        print(f"  {reason}：{n}")
    n, changed, gained = regression()
    print(f"回帰確認：labels-line2.csv で既存分野が決まっている {n} 本のうち、語を足すと分野が変わる {changed} 本（0が条件）")
    print(f"        同じ表で対応表なしだった行のうち新分野になる {gained} 本")
    print(f"書き出し：{OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
