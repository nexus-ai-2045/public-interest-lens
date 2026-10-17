"""bill-triage-v2 の系統2：系統2の AI が付けた種類・分野（bill-triage-v1-line2/labels.csv）に、指標の選び方 indicator-pick-v1 を当てる。

docs/提案/指標の選び方-v1.md の 3（指標の表）と 4-4（D1〜D5）を、app/src/indicator-pick.ts とは別に、この文書から書き起こした実装。
系統1（app/scripts/run-triage-v2-line1.mjs が indicator-pick.ts を使う）と別のコード経路にして、実装の写し間違いを一致の確認で拾えるようにする。
ただし規則の中身（語の表・D1〜D5）は同じ文書なので、指標の選び方そのものの一致は自明に近い。規則適用後の分野・指標の一致は独立の判断を示さない。
入力のAI判断と決定的な規則適用後の結果は区別する。
tests/test_triage_v2.py が、全題名で2つの実装の出力が同じことを確かめる。

入力：data/derived/bill-triage-v1-line2/labels.csv（題名・系統2_種類・系統2_分野）。系統1の列は読まない。
出力：data/derived/bill-triage-v2/labels-line2.csv
使い方（リポジトリのルートで）：python3 scripts/triage_v2_line2.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

NO_FIELD = "対応表なし"
KINDS = ("新規", "実質改正", "定型改正", "組織手続")

# 3 の表。(分野, [(行の符号, 語, 指標), ...], 既定)。語は「、」区切りの1本の文字列から割る。
_PICK = {
    "金融": ([("F1", "預金保険、貯金保険、破綻、不良債権、早期健全化、金融機能、債権債務の処理、債権管理回収、債権の管理", "不良債権比率"),
             ("F2", "倒産、再生、更生手続、信用保険、信用保証", "企業倒産件数")], "貸出残高"),
    "交通・移動": ([("T1", "運転者、乗務員、船員、従事者、労働時間", "就業者数"),
               ("T2", "運送事業、運送法、事業法、事業の適正化、鉄道株式会社", "旅客輸送の付加価値"),
               ("T3", "空港、港湾、道路、新幹線、鉄道、整備、施設", "利用件数")], "利用件数"),
    "宿泊・観光": ([("H1", "旅館、ホテル、宿泊施設", "客室数"), ("H2", "宿泊業", "宿泊業の付加価値")], "宿泊者数"),
    "通信・ネット": ([("C1", "ブロードバンド、光ファイバ、高度情報通信、ネットワーク、基盤の整備", "ブロードバンド普及率"),
                ("C2", "電子商取引、電子消費者契約、電子承諾、インターネット上、プラットフォーム", "ネット企業の時価総額")], "通信業の付加価値"),
    "半導体・電子": ([("S1", "輸出、国際競争力", "世界輸出シェア")], "生産額"),
    "エネルギー": ([("G1", "省エネルギー、エネルギーの使用の合理化、消費性能", "エネルギー効率"),
               ("G2", "再生可能、原子力、原子炉、核燃料、電源、水素、アンモニア、発電", "発電構成")], "電力価格"),
    "労働市場": ([("L1", "賃金、給与、報酬、待遇、労働基準、労働時間", "賃金"),
              ("L2", "職業能力開発、労働安全、衛生、作業環境、過労、災害", "労働生産性"),
              ("L3", "職業訓練、就職、求職、職業安定、派遣", "雇用の流動性")], "雇用の流動性"),
    "行政のデジタル化": ([("E1", "電子、オンライン、デジタル、情報システム、情報通信技術", "電子申請率"),
                   ("E2", "簡素、迅速、負担軽減、手続の時間", "行政手続きの時間")], "電子申請率"),
}

# D1：分野を決める語（criteria.md の2の表の語＋上の指標の表の語＋170本を見て足した語）。
_FIELD_WORDS = {
    "金融": "銀行、金庫、金融、保険、証券、預金、貯金、貸金、融資、信用保証、資産の流動化、公庫、政策投資、破綻、不良債権、早期健全化、債権債務の処理、債権管理回収、債権の管理、倒産、再生、更生手続、信用組合、協同組織、貸付、社債、振替、割賦、信託",
    "交通・移動": "鉄道、道路、自動車、航空、空港、港湾、船舶、海上運送、運送、運転者、乗務員、船員、従事者、新幹線、旅客、交通、移動",
    "宿泊・観光": "観光、旅行業、通訳案内、宿泊、旅館、ホテル、ツーリズム",
    "通信・ネット": "電気通信、電波、放送、郵便、通信、インターネット、サイバーセキュリティ、電話、ブロードバンド、光ファイバ、ネットワーク、電子商取引、電子消費者契約、電子承諾、プラットフォーム",
    "半導体・電子": "半導体、電子部品、情報処理",
    "エネルギー": "電気事業、ガス事業、石油、原子力、原子炉、核燃料、再生可能、エネルギー、電源、水素、アンモニア、発電",
    "労働市場": "労働、雇用、賃金、給与、報酬、待遇、職業、就職、求職、派遣、過労、災害、作業環境、衛生",
    "行政のデジタル化": "電子、オンライン、デジタル、情報システム、情報通信技術、行政手続、手続、データ活用",
}


# field-expansion-v1（docs/提案/分野の拡張-v1.md の3）の新分野。(分野: (指標名, 直接の語, 代理の語))。水道・廃棄物は承認項目 B3 の推奨に従い作らない。
# 既存8分野の語が題名に1つも無いときだけ当てる（既存優先）。代理の語に当たった法律の指標には「（代理）」を付け、直接の語と別の指標にする
# （代理は参考扱い：合計に入れず、公開せず、議員への配分に使わない）。語の全文は scripts/estimate_field_expansion.py の NEW_FIELDS（水道・廃棄物を除く）と同じ。
_NEW_FIELDS = {
    "農林水産": ("農林水産業の付加価値", "農業、農地、農林、林業、森林、水産、漁業、漁船、漁港、漁場、畜産、家畜、酪農、農産物、農薬、肥料、種苗、農協、農業協同組合、森林組合、漁業協同組合、植物防疫、米穀、木材、農村、牧野、農作物、原料乳、お茶、花き、真珠、棚田、土地改良、養殖、養ほう、野菜、生産調整、国有林野、農山漁村、農住", "食料、食糧、飼料"),
    "建設": ("建設業の付加価値", "建設、建築、公共工事、工事、測量", "都市計画、都市再生、都市再開発、市街地、区画整理、宅地造成、耐震、国土強靱化、国土形成、公共施設、無電柱化、基盤整備、河川、海岸、砂防、景観、歴史的風致、首都圏整備、津波防災地域"),
    "住宅・不動産": ("不動産業の付加価値", "", "住宅、不動産、賃貸、借地、借家、宅地建物、マンション、区分所有、土地基本、土地収用、建物、居住、地価、空家、住生活"),
    "教育": ("教育の付加価値", "", "教育、学校、大学、義務教育、奨学、学習、教職員、幼稚園、就学、学級、教科用、留学、育英"),
    "医療・福祉": ("保健衛生・社会事業の付加価値", "", "医療、医師、歯科、薬事、医薬、薬剤師、薬局、看護、介護、福祉、保健、健康増進、感染症の予防、予防接種、精神保健、老人、母子、難病、臓器、献血、血液、保育、子育て、児童福祉、障害福祉、障害者総合支援、障害児、児童虐待、医薬品、診療、病院、原子爆弾被爆者、結核、検疫、狂犬病、社会福祉、栄養、生活衛生、母体、あん摩、柔道整復、臨床、移植、造血幹細胞、死因究明、アレルギー、インフルエンザ、自殺対策、障害者自立支援、障害者の日常生活、がん対策、がん登録、肝炎、循環器病、公認心理師、高齢者虐待、次世代育成、子どもの貧困、生活困窮者"),
    "製造業": ("製造業の付加価値", "製造、工業、鉱工業、工場、繊維、化学物質、計量、産業標準、火薬、高圧ガス、家庭用機器", "容器包装、再商品化、食品、たばこ、電気用品、消費生活用、企業立地、産業集積、伝統的工芸品、アルコール、酒類"),
    "商業": ("卸売・小売業の付加価値", "小売、卸売、商店街、商業、流通、古物、質屋", "訪問販売、特定商取引、販売、中心市街地、景品、表示"),
    "専門サービス・研究開発": ("専門・科学技術、業務支援サービス業の付加価値", "弁護士、司法書士、行政書士、税理士、公認会計士、弁理士、社会保険労務士、土地家屋調査士、建築士、技術士、不動産鑑定、警備業、探偵、研究開発、試験研究、科学技術、研究所、研究施設、産業技術", "特許、実用新案、意匠、商標、知的財産、著作権"),
    "文化・娯楽・生活サービス": ("その他のサービス業の付加価値", "", "文化、芸術、文化財、スポーツ、体育、競馬、自転車競技、小型自動車競走、モーターボート競走、興行、遊技、風俗、公衆浴場、宗教、映画、博物館、図書館、劇場、オリンピック、万国博覧会、博覧会、墓地、理容、美容、クリーニング、美術、競技大会、温泉"),
}
PROXY_SUFFIX = "（代理）"
NEW_FIELD_NAMES = tuple(_NEW_FIELDS)
ALL_FIELDS = tuple(_PICK) + NEW_FIELD_NAMES


def new_indicator(field: str, match: str) -> str:
    """新分野の指標。直接の語は指標名そのまま、代理の語は「（代理）」付き。"""
    name = _NEW_FIELDS[field][0]
    return name if match == "直接" else name + PROXY_SUFFIX


def _new_hits(text: str) -> list[tuple[int, str, str, str]]:
    return [(text.find(w), f, w, m) for f, (_, direct, proxy) in _NEW_FIELDS.items()
            for m, ws in (("直接", direct), ("代理", proxy)) for w in _words(ws) if w and w in text]


def _words(s: str) -> list[str]:
    return s.split("、")


def first_law(title: str) -> str:
    """D2：設置法・整備法の部分を除いて、題名の最初の法律で決める。"""
    out = title
    while True:
        m = re.search(r"及び[^及]*(?:設置法|整備法)", out)
        if not m:
            return out
        out = out[: m.start()] + out[m.end():]


def pick(field: str, text: str) -> tuple[str, str, str]:
    rows, default = _PICK[field]
    for sign, words, indicator in rows:
        for w in _words(words):
            if w in text:
                return indicator, field + sign, w
    return default, field + "既定", ""


def triage(title: str, kind: str, field: str) -> dict:
    if kind not in KINDS or (field != NO_FIELD and field not in ALL_FIELDS):
        return {"kind": kind, "field": field, "indicator": "", "verdict": "保留", "rules": ["D5"],
                "reason": f"D5：種類「{kind}」・分野「{field}」が定義にない値のため保留"}
    rules, notes = [], []
    text = first_law(title)
    if text != title:
        rules.append("D2")
        notes.append("D2：題名の最初の法律で決める")
    if kind == "組織手続" and "設置法" not in title:
        if re.search(r"(機構|公庫|公団|事業団|基金|銀行|金庫)法案$", text):
            kind = "新規"
            rules.append("D3")
            notes.append("D3：新設法人の根拠法は新規")
        elif re.search(r"(機構|公庫|公団|事業団|基金|銀行|金庫)法の一部を改正する法律案$", text):
            kind = "実質改正"
            rules.append("D4")
            notes.append("D4：機構法などの改正は実質改正")
    hits = [(text.find(w), f, w) for f, ws in _FIELD_WORDS.items() for w in _words(ws) if w in text]
    hits.sort(key=lambda hit: hit[0])
    first = hits[0] if hits else None
    if first and any(pos == first[0] and f != first[1] for pos, f, _ in hits):
        return {"kind": kind, "field": "", "indicator": "", "verdict": "保留", "rules": [*rules, "D5"],
                "reason": "D5：最初の語の位置で複数の分野が競合するため保留"}
    new_match = ""
    if first is None:
        # 既存8分野の語が無いときだけ新分野の語を当てる。同じ位置の語が別の語の一部なら長い語を採り、別々の分野の語が重なれば保留（D5）。
        nh = _new_hits(text)
        if nh:
            pos = min(h[0] for h in nh)
            top = [h for h in nh if h[0] == pos]
            top = [h for h in top if not any(h[2] != g[2] and h[2] in g[2] for g in top)]
            if len({h[1] for h in top}) > 1:
                return {"kind": kind, "field": "", "indicator": "", "verdict": "保留", "rules": [*rules, "D5"],
                        "reason": "D5：最初の語の位置で複数の分野が競合するため保留"}
            _, nf, nw, new_match = max(top, key=lambda h: len(h[2]))
            first = (pos, nf, nw)
    field = first[1] if first else NO_FIELD
    rules.append("D1")
    notes.append(f"D1：題名で最初の語「{first[2]}」の分野" if first else "D1：題名に8分野の語が無い")
    indicator = ""
    if new_match:
        indicator, sign, word = new_indicator(field, new_match), field + new_match, first[2]
        rules.append(sign)
        notes.append(f"{sign}（語「{word}」）")
    elif field != NO_FIELD:
        indicator, sign, word = pick(field, text)
        rules.append(sign)
        notes.append(f"{sign}（語「{word}」）" if word else sign)
    verdict = "評価対象外" if field == NO_FIELD or kind in ("定型改正", "組織手続") else "評価対象"
    reason = f"{verdict}（{kind}・{field}{'・' + indicator if indicator else ''}）／{'、'.join(notes)}"
    return {"kind": kind, "field": field, "indicator": indicator, "verdict": verdict, "rules": rules, "reason": reason}


HEADER = ["id", "題名", "付託委員会", "系統2_入力種類", "系統2_入力分野", "系統2_種類", "系統2_分野", "系統2_指標", "系統2_判定", "系統2_規則", "系統2_理由"]


def build(src: Path, dst: Path) -> int:
    with src.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for r in rows:
            t = triage(r["題名"], r["系統2_種類"], r["系統2_分野"])
            w.writerow([r["id"], r["題名"], r["付託委員会"], r["系統2_種類"], r["系統2_分野"], t["kind"], t["field"], t["indicator"], t["verdict"], "／".join(t["rules"]), t["reason"]])
    return len(rows)


if __name__ == "__main__":
    n = build(Path("data/derived/bill-triage-v1-line2/labels.csv"), Path("data/derived/bill-triage-v2/labels-line2.csv"))
    print(f"bill-triage-v2 系統2: {n} 本")
