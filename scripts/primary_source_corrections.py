"""一次資料で直したサイトの値（primary-source-corrections-v1）を読む。AI は呼ばない。

振り分け（bill-triage-v1・v2）と経済の区分（econ-relevance-v1）は AI の判定の記録なので書き換えない。
抜き取り検証の読み直しで一次資料と合わないと分かった値だけを、この表で上書きする。
表の各行は読み直しの記録（evaluation-ledger-v1/reverification-v1/）の値と同じであることを
tests/test_primary_source_corrections.py が確かめる。

項目
  類型          新規／実質改正／定型改正／組織手続。all-laws-v1 の「種類」と定例の規則（RT8）・種類による対象外に使う。
  経済に効くか  経済に効く／制度。
                制度：税収見込み・コロナ対応・市場の経路より先に評価対象外（経済への直接効果なし）にする。台帳の分類も評価対象外にする。
                経済に効く：題名の型（整備法など）・経済の区分の制度・定例の規則・種類による対象外に当てない
                （続けなければ止まる補助や特例がある期限の延長など）。その先はふつうの順で決める
                （市場の経路、マクロ指標の代理で保留、どれにも当たらなければ測定できない）。
                判定不能：一次資料の読み直し（Haiku 2系統・Sonnet・Opus）でも決められなかった。定例の規則（RT8）だけに当てない
                （期限の延長で、続けなければ止まるお金があるかが分からないまま効果なし（定例）に確定させない）。台帳には判定不能と出る。
  分野          主な産業分野（FIELDS）。マクロの参考額の産業（macro-v1）と曝露ランキングの群、all-laws-v1 の「分野」に使う。
                個別の額（因果の鎖）の法律で分野を直したときは、額が別の産業で計算されているので、直した分野で計算し直すまで額を付けない。
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "derived" / "primary-source-corrections-v1" / "corrections.csv"
# 振り分けの当て直し（primary-triage-v1、議案本文＋会議録を Haiku 2系統・Sonnet 裁定で読んだ結果）。訂正表より下、AI の振り分けより上
LABELS = ROOT / "data" / "derived" / "primary-triage-v1" / "labels.csv"
LAYER = "_層"  # 行がどの表から来たか（訂正表／当て直し）
LAYER_CORRECTIONS = "一次資料の読み直し（訂正表）"
LAYER_LABELS = "一次資料の当て直し（primary-triage-v1）"
ITEMS = ("類型", "経済に効くか", "分野")
# 分野の値：読み直しの指示文（sample-v2/prompt-v2.md）の「主な産業分野」の並び。「経済全体（産業を特定できない）」は全産業で測る
FIELDS = ("農林水産", "労働市場", "金融", "医療・福祉", "交通・移動", "教育", "通信・ネット", "専門サービス・研究開発",
          "文化・娯楽・生活サービス", "エネルギー", "行政のデジタル化", "建設", "製造業", "住宅・不動産", "商業", "宿泊・観光",
          "半導体・電子", "鉱業・採石", "経済全体（産業を特定できない）")
ECON = "経済に効く"
INSTITUTIONAL = "制度"
UNDECIDED = "判定不能"
METHOD = "一次資料の読み直し"


def load(path: Path = PATH) -> dict[str, dict[str, dict[str, str]]]:
    """{id: {項目: 行}}。表が無ければ空。"""
    if not path.exists():
        return {}
    out: dict[str, dict[str, dict[str, str]]] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["項目"] not in ITEMS:
                raise ValueError(f"{path.name}: 項目「{r['項目']}」は {ITEMS} のどれでもない（{r['id']}）")
            if r["項目"] == "経済に効くか" and r["直した値"] not in (ECON, INSTITUTIONAL, UNDECIDED):
                raise ValueError(f"{path.name}: 経済に効くかの値「{r['直した値']}」が定義に無い（{r['id']}）")
            if r["項目"] == "分野" and r["直した値"] not in FIELDS:
                raise ValueError(f"{path.name}: 分野の値「{r['直した値']}」が定義に無い（{r['id']}）")
            if r["項目"] in out.get(r["id"], {}):
                raise ValueError(f"{path.name}: {r['id']} の「{r['項目']}」の行が2つある")
            out.setdefault(r["id"], {})[r["項目"]] = r
    return out


def load_layered(path: Path = PATH, labels: Path = LABELS) -> dict[str, dict[str, dict[str, str]]]:
    """訂正表（抜き取り検証の読み直し）を上、振り分けの当て直し（labels.csv）を下に重ねた {id: {項目: 行}}。
    同じ法律・同じ項目が両方にあれば訂正表を使う。行の「_層」にどちらの表かを入れる。
    抜き取り検証の照合（check_error_types・resolve_sample_failures）は訂正表だけを読む（load）。"""
    out: dict[str, dict[str, dict[str, str]]] = {}
    for layer, src in ((LAYER_LABELS, labels), (LAYER_CORRECTIONS, path)):
        for law_id, items in load(src).items():
            for item, row in items.items():
                out.setdefault(law_id, {})[item] = {**row, LAYER: layer}
    return out


def method(corr: dict, id_: str, item: str) -> str:
    """その値を決めた方法の名前（台帳・理由の文に出す）。訂正表なら「一次資料の読み直し」、当て直しなら「一次資料の当て直し」。"""
    row = corr.get(id_, {}).get(item) or {}
    return "一次資料の当て直し" if row.get(LAYER) == LAYER_LABELS else METHOD


def value(corr: dict, id_: str, item: str) -> str | None:
    row = corr.get(id_, {}).get(item)
    return row["直した値"] if row else None
