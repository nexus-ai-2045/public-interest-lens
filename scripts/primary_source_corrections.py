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
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "data" / "derived" / "primary-source-corrections-v1" / "corrections.csv"
ITEMS = ("類型", "経済に効くか")
ECON = "経済に効く"
INSTITUTIONAL = "制度"
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
            if r["項目"] == "経済に効くか" and r["直した値"] not in (ECON, INSTITUTIONAL):
                raise ValueError(f"{path.name}: 経済に効くかの値「{r['直した値']}」が定義に無い（{r['id']}）")
            out.setdefault(r["id"], {})[r["項目"]] = r
    return out


def value(corr: dict, id_: str, item: str) -> str | None:
    row = corr.get(id_, {}).get(item)
    return row["直した値"] if row else None
