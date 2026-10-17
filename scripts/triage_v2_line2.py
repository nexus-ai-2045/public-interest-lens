"""bill-triage-v2 の系統2：系統2の AI が付けた種類・分野（bill-triage-v1-line2/labels.csv）に、指標の選び方 indicator-pick-v1 を当てる。

docs/提案/指標の選び方-v1.md の 3（指標の表）と 4-4（D1〜D5）を、app/src/indicator-pick.ts とは別に、この文書から書き起こした実装。
系統1（app/scripts/run-triage-v2-line1.mjs が indicator-pick.ts を使う）と別のコード経路にして、実装の写し間違いを一致の確認で拾えるようにする。
ただし規則の中身（語の表・D1〜D5）は同じ文書なので、指標の選び方そのものの一致は自明に近い。独立に確かめられるのは、
系統ごとの AI の判断（種類・分野）が一致するかどうか。
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
    if kind not in KINDS or (field != NO_FIELD and field not in _PICK):
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
    if field != NO_FIELD and not any(w in text for ws in _FIELD_WORDS.values() for w in _words(ws)):
        field = NO_FIELD
        rules.append("D1")
        notes.append("D1：題名に8分野の語が無い")
    indicator = ""
    if field != NO_FIELD:
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
