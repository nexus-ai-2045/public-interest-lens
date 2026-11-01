"""評価の規則のうち、作る側（全法律の結果・全体指標・公開ランキング）と検査側（check_evaluation_logic）が同じ判定を使うもの。

作る側と検査側で語や符号の規則が二重にならないよう、ここを正本にする（設計決定0024）。
  L1 因果の鎖  額には、出典 URL つきの議員の関与が1件以上ある
  L2 範囲      狭い題名（特例・特定など）に、経済全体の額を当てない
  L3 向き      向き（貢献・上昇／悪影響・低下）と、額の符号（中央値）が食い違わない
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

NARROW_WORDS = ("特例", "特定", "臨時", "暫定", "特別措置")
WHOLE_ECONOMY_INDUSTRY = "_T"
WHOLE_ECONOMY_FIELD = "経済全体"
GOOD_DIRECTIONS = ("貢献", "上昇")
BAD_DIRECTIONS = ("悪影響", "低下")
SIDE_MEDIAN = re.compile(r"(便益|損失)：中央値=(-?\d+)")

# 作る側が額を付けなかった行の経路。公開ランキングも同じ行を額なしにする（outcomes.csv が唯一の判断元）
ROUTE_SIGN_CONFLICT = "市場（向きと額の符号が逆）"
ROUTE_NO_CHAIN = "市場（議員の関与の出典なし）"
DEMOTED_ROUTES = frozenset({ROUTE_SIGN_CONFLICT, ROUTE_NO_CHAIN})


def narrow_whole_economy(title: str, industry: str, field: str) -> bool:
    """L2：狭い題名の法律に、経済全体の額を当てていないか。"""
    return (industry == WHOLE_ECONOMY_INDUSTRY or field == WHOLE_ECONOMY_FIELD) and any(w in title for w in NARROW_WORDS)


def sign_conflict(direction: str, amount_text: str) -> str | None:
    """L3：向きと中央値の符号が逆なら「便益」か「損失」を返す。逆でなければ None。"""
    m = SIDE_MEDIAN.search(amount_text)
    if not m:
        return None
    side, value = m.group(1), int(m.group(2))
    good, bad = direction in GOOD_DIRECTIONS, direction in BAD_DIRECTIONS
    if (side == "便益" and good and value < 0) or (side == "損失" and bad and value < 0) \
            or (side == "便益" and bad and value > 0) or (side == "損失" and good and value > 0):
        return side
    return None


def involved_law_ids(path: Path) -> set[str] | None:
    """L1：出典 URL つきの関与がある法律 ID。一覧が無い環境では None（鎖を判定しない）。"""
    if not path.exists():
        return None
    with path.open(encoding="utf-8", newline="") as f:
        return {r["法律ID"] for r in csv.DictReader(f) if r["証拠URL"].startswith("http")}


# 降格（参考に下げる）の規則。作る側の台帳（build_evaluation_ledger）と公開ランキング（build_public_ranking）が同じ関数を使う。
# 方針：不合格の法律は「額を消す」のではなく「参考値に下げる」。確かさを参考にし、順位・議員配分に使わず、理由と根拠を添えて額を出し続ける。
VERDICT_FAIL = "不合格"
STATE_FAILED = "抜き取り検証で不合格"
STATE_DEMOTED = "参考に下げた"
# 台帳の到達点が、額を順位・議員配分に使わない（参考額）か、そもそも評価対象外（額が出ていれば順位に混ざる）のもの
DEMOTE_REACH_PREFIXES = ("参考額", "評価対象外", "額（個別")


def is_demoted(verdict: str, reach: str = "", certainty: str = "", in_ranking: bool = False) -> bool:
    """不合格（sample-verdicts の判定）で、額を参考値として残す扱いにする法律か。

    台帳側は 到達点（reach）・確かさ（certainty）で呼ぶ。額の無い到達点（保留・測定できない・効果なし）や
    国の収支の別欄は降格の対象にしない（参考にする額が無い／分類を決め直す必要がある）。
    公開ランキング側は、額が画面に出ている法律について in_ranking=True で呼ぶ。確かさ（高・中・低・参考）や
    コロナ費用便益の群を問わず、不合格なら降格する。
    """
    if verdict != VERDICT_FAIL:
        return False
    return in_ranking or certainty == "参考" or reach.startswith(DEMOTE_REACH_PREFIXES)
