"""bill-triage-v2 の系統2：系統2の AI が付けた種類・分野（bill-triage-v1-line2/labels.csv）に、指標の選び方 indicator-pick-v1 を当てる。

docs/提案/指標の選び方-v1.md の 3（指標の表）と 4-4（D1〜D5）を、app/src/indicator-pick.ts とは別に、この文書から書き起こした実装。
系統1（app/scripts/run-triage-v2-line1.mjs が indicator-pick.ts を使う）と別のコード経路にして、実装の写し間違いを一致の確認で拾えるようにする。
ただし規則の中身（語の表・D1〜D5）は同じ文書なので、指標の選び方そのものの一致は自明に近い。規則適用後の分野・指標の一致は独立の判断を示さない。
入力のAI判断と決定的な規則適用後の結果は区別する。
tests/test_triage_v2.py が、全題名で2つの実装の出力が同じことを確かめる。

入力：data/derived/bill-triage-v1-line2/labels.csv（題名・系統2_種類・系統2_分野）。系統1の列は読まない。
出力：data/derived/bill-triage-v2/labels-line2.csv
labels.csv は施行日台帳の349本でも、全3,415本でもよい（出力は入力と同じ行数）。
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
             ("F2", "倒産、再生、更生手続、信用保険、信用保証", "企業倒産件数"),
             ("F3", "貸付、融資、政策金融、公庫、金庫、政策投資", "貸出残高")], "金融・保険業の付加価値"),
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

# R1（2026-10-18、額の大きい法律の点検）：語の境界。語が、ここに挙げた複合語の一部として題名に現れたところは当たりにしない。
# app/src/indicator-pick.ts の WORD_EXCLUSIONS と同じ表（tests/test_triage_v2.py が確かめる）。
# R4 は上の金融の表（既定を貸出残高から金融・保険業の付加価値へ。貸出残高は F3 の語があるときだけ）。
WORD_EXCLUSIONS = {
    "保険": ["健康保険", "社会保険", "介護保険", "雇用保険", "保険医"],
    "融資": ["財政投融資"],
    "金融": ["資金融通", "国際金融公社"],
    "銀行": ["国際復興開発銀行", "アジア開発銀行", "米州開発銀行", "アフリカ開発銀行", "欧州復興開発銀行", "アジアインフラ投資銀行"],
    "工業": ["加工業"],
    "報酬": ["診療報酬"],
    "災害": ["海上災害"],
}


def find_word(text: str, word: str) -> int:
    """題名で語が最初に現れる位置。除外表の複合語の一部として現れたところは飛ばす。無ければ -1。"""
    compounds = WORD_EXCLUSIONS.get(word, [])
    pos = text.find(word)
    while pos >= 0:
        inside = False
        for c in compounds:
            q = text.find(c)
            while q >= 0 and not inside:
                inside = q <= pos and pos + len(word) <= q + len(c)
                q = text.find(c, q + 1)
        if not inside:
            return pos
        pos = text.find(word, pos + 1)
    return -1


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
    "農林水産": ("農林水産業の付加価値", "農業、農地、農林、林業、森林、水産、漁業、漁船、漁港、漁場、畜産、家畜、酪農、農産物、農薬、肥料、種苗、農協、農業協同組合、森林組合、漁業協同組合、植物防疫、米穀、木材、農村、牧野、農作物、原料乳、お茶、花き、真珠、棚田、土地改良、養殖、養ほう、野菜、生産調整、国有林野、農山漁村、農住、農産加工", "食料、食糧、飼料"),
    "建設": ("建設業の付加価値", "建設、建築、公共工事、工事、測量", "都市計画、都市再生、都市再開発、市街地、区画整理、宅地造成、耐震、国土強靱化、国土形成、公共施設、無電柱化、基盤整備、河川、海岸、砂防、景観、歴史的風致、首都圏整備、津波防災地域"),
    "住宅・不動産": ("不動産業の付加価値", "", "住宅、不動産、賃貸、借地、借家、宅地建物、マンション、区分所有、土地基本、土地収用、建物、居住、地価、空家、住生活"),
    "教育": ("教育の付加価値", "", "教育、学校、大学、義務教育、奨学、学習、教職員、幼稚園、就学、学級、教科用、留学、育英"),
    "医療・福祉": ("保健衛生・社会事業の付加価値", "", "医療、健康保険、医師、歯科、薬事、医薬、薬剤師、薬局、看護、介護、福祉、保健、健康増進、感染症の予防、予防接種、精神保健、老人、母子、難病、臓器、献血、血液、保育、子育て、児童福祉、障害福祉、障害者総合支援、障害児、児童虐待、医薬品、診療、病院、原子爆弾被爆者、結核、検疫、狂犬病、社会福祉、栄養、生活衛生、母体、あん摩、柔道整復、臨床、移植、造血幹細胞、死因究明、アレルギー、インフルエンザ、自殺対策、障害者自立支援、障害者の日常生活、がん対策、がん登録、肝炎、循環器病、公認心理師、高齢者虐待、次世代育成、子どもの貧困、生活困窮者"),
    "製造業": ("製造業の付加価値", "製造、工業、鉱工業、工場、繊維、化学物質、計量、産業標準、火薬、高圧ガス", "容器包装、再商品化、食品、たばこ、電気用品、消費生活用、企業立地、産業集積、伝統的工芸品、アルコール、酒類"),
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
    hits = [(find_word(text, w), f, w, m) for f, (_, direct, proxy) in _NEW_FIELDS.items()
            for m, ws in (("直接", direct), ("代理", proxy)) for w in _words(ws) if w]
    return [h for h in hits if h[0] >= 0]


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
            if find_word(text, w) >= 0:
                return indicator, field + sign, w
    return default, field + "既定", ""


def resolve_tie(at: list):
    """同じ位置に別々の分野の語が重なったときの解消（HR1・v2.1）。(分野, 語, 元の値) の並びを受け、
    他の語の一部でない短い語を除いて残る分野が1つなら元の値を返す。複数なら保留の理由（文字列）を返す。"""
    top = [h for h in at if not any(h[1] != g[1] and h[1] in g[1] for g in at)]
    if len({h[0] for h in top}) > 1:
        lst = "／".join(dict.fromkeys(f"{h[0]}「{h[1]}」" for h in top))
        return f"D5：最初の語の位置で複数の分野が競合し、他の語の一部でない語が複数の分野に残るため保留（{lst}）"
    return max(top, key=lambda h: len(h[1]))[2]


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
        elif re.search(r"(機構|公庫|公団|事業団|基金|銀行|金庫)法等の一部を改正する法律案$", text):
            kind = "実質改正"
            rules.append("HR2")
            notes.append("HR2（v2.1）：機構法等の一部改正はD4と同じく実質改正")
    hits = [h for h in ((find_word(text, w), f, w) for f, ws in _FIELD_WORDS.items() for w in _words(ws)) if h[0] >= 0]
    hits.sort(key=lambda hit: hit[0])
    first = hits[0] if hits else None
    if first:
        at = [h for h in hits if h[0] == first[0]]
        if any(h[1] != first[1] for h in at):
            tie = resolve_tie([(h[1], h[2], h) for h in at])
            if isinstance(tie, str):
                return {"kind": kind, "field": "", "indicator": "", "verdict": "保留", "rules": [*rules, "D5"], "reason": tie}
            first = tie
            rules.append("HR1")
            notes.append(f"HR1（v2.1）：最初の位置で競合した語のうち、他の語の一部でない最長の語「{tie[2]}」の分野")
    new_match = ""
    # 新分野の語。R3（2026-10-18）：既存8分野の語が無いときに加え、新分野の語が既存8分野の語より題名の先にあるときも新分野を当てる（同じ位置なら既存優先）。
    # 同じ位置の語が別の語の一部なら長い語を採り、別々の分野の語が重なれば保留（D5）。
    nh = _new_hits(text)
    if first is not None and nh and min(h[0] for h in nh) < first[0]:
        rules.append("R3")
        notes.append(f"R3：新分野の語が既存8分野の語「{first[2]}」より題名の先にある")
        first = None
    if first is None:
        if nh:
            pos = min(h[0] for h in nh)
            at = [h for h in nh if h[0] == pos]
            tie = resolve_tie([(h[1], h[2], h) for h in at])
            if isinstance(tie, str):
                return {"kind": kind, "field": "", "indicator": "", "verdict": "保留", "rules": [*rules, "D5"], "reason": tie}
            _, nf, nw, new_match = tie
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


def _rank(field: str, indicator: str):
    """分野の表の中での指標の順位（上の行ほど小さい。既定は最後）。表にない指標は None。"""
    rows, default = _PICK[field]
    for i, (_, _, ind) in enumerate(rows):
        if ind == indicator:
            return i
    return len(rows) if indicator == default else None


def resolve_diff(title: str, l1: dict, l2: dict) -> dict:
    """v2.1 の解消規則 HR3・HR4（app/src/line-agreement.ts の resolveTriageDiff と同じ規則。parity は tests/test_triage_v2.py）。
    l1・l2 は {verdict, field, indicator, kind}。解消したら {rule, line, reason}、しなければ {rule: "", reason}。"""
    if any(l["verdict"] not in ("評価対象", "評価対象外") for l in (l1, l2)):
        return {"rule": "", "reason": "片方の系統が保留（入力値が未定義、または同位置の競合）のため解消しない"}
    if l1["field"] == l2["field"] and l1["field"] in _PICK and l1["indicator"] != l2["indicator"]:
        if l1["verdict"] != l2["verdict"]:
            return {"rule": "", "reason": "HR3に当たらない：指標も判定も食い違う"}
        r1, r2 = _rank(l1["field"], l1["indicator"]), _rank(l2["field"], l2["indicator"])
        if r1 is None or r2 is None:
            return {"rule": "", "reason": "HR3に当たらない：指標が分野の表にない"}
        win, lose, wn, ln = (l1, l2, "系統1", "系統2") if r1 <= r2 else (l2, l1, "系統2", "系統1")
        return {"rule": "HR3", "line": dict(win),
                "reason": f"HR3：同じ分野「{win['field']}」で指標が違う（{wn}：{win['indicator']}、{ln}：{lose['indicator']}）ため、分野の表の上の行の{win['indicator']}を固定の優先順で採る"}
    one = [l for l in (l1, l2) if l["field"] == NO_FIELD]
    other = [l for l in (l1, l2) if l["field"] != NO_FIELD]
    if len(one) == 1 and len(other) == 1 and other[0]["field"] in _PICK:
        f = other[0]["field"]
        if not l1.get("kind") or not l2.get("kind") or l1["kind"] != l2["kind"]:
            return {"rule": "", "reason": "HR4に当たらない：2系統の種類が同じと確かめられない"}
        seg = first_law(title)
        word = next((w for w in _words(_FIELD_WORDS[f]) if find_word(seg, w) >= 0), "")
        if not word:
            return {"rule": "", "reason": f"HR4に当たらない：題名に分野「{f}」の直接の語が無い"}
        indicator, sign, _ = pick(f, seg)
        verdict = "評価対象外" if l1["kind"] in ("定型改正", "組織手続") else "評価対象"
        return {"rule": "HR4", "line": {"verdict": verdict, "field": f, "indicator": indicator, "kind": l1["kind"]},
                "reason": f"HR4：片方が対応表なしで、題名に分野「{f}」の直接の語「{word}」があるため分野を採り、指標は{sign}で{indicator}"}
    return {"rule": "", "reason": "v2.1の解消規則（HR3・HR4）に当たらない"}


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
