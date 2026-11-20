"""類型の照合（scripts/type_crosscheck.py）の規則の性質テスト。ネットワークは使わない。"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from type_crosscheck import (
    NEW,
    ORG,
    ROUTINE,
    SUBST,
    egov_law_id,
    honbun_url,
    rule_type,
    status,
)

HEAD = "第二一一回 閣第一一号 ○○法の一部を改正する法律案 "


def amend(body: str) -> str:
    return HEAD + "○○法（昭和二十七年法律第九十三号）の一部を次のように改正する。 " + body + " 附 則 この法律は、公布の日から施行する。 理 由 必要がある。"


def test_新規は本文が一部改正で始まらないとき():
    t = "第二一一回 閣第一号 ○○法案 目次 第一章 総則 第一条 この法律は…しなければならない。 附 則 施行する。"
    assert rule_type(t, True, [])[0] == NEW


def test_改正元が組織の分類だけなら組織手続():
    assert rule_type(amend("第三条中「十人」を「十二人」に改める。"), False, ["行政組織", "国家公務員"])[0] == ORG


def test_分類が混ざれば組織手続にしない():
    assert rule_type(amend("第三条に次の一項を加える。 ２ 許可を受けなければならない。"), False, ["行政組織", "金融・保険"])[0] == SUBST


def test_数と日付の置き換えだけなら定型改正():
    t = amend("第十五条中「四万三千円」を「五万千円」に改める。 附則第二項中「平成三十五年」を「令和十年」に改める。")
    assert rule_type(t, False, ["財務通則"])[0] == ROUTINE


def test_改めの連用形は数えない既知の限界():
    # 測定（標本・全件）に使った規則のまま。「改め、」で続く置き換えは指示の数に入らないので実質改正に倒れる。
    # 直すなら規則の版を上げ、標本で測り直す（README の既知の限界）。
    t = amend("第十五条中「四万三千円」を「五万千円」に改め、附則第二項中「平成三十五年」を「令和十年」に改める。")
    assert rule_type(t, False, ["財務通則"])[0] == SUBST


def test_加えるがあれば実質改正():
    t = amend("第十五条中「四万三千円」を「五万千円」に改める。 第十五条の三に次のただし書を加える。 ただし、この限りでない。")
    assert rule_type(t, False, ["外事"])[0] == SUBST


def test_本則に改正が無く附則だけなら定型改正():
    t = HEAD + "○○法の一部を次のように改正する。 附 則 第二項中「五年」を「十年」に改める。 理 由 延長する。"
    assert rule_type(t, False, ["工業"])[0] == ROUTINE


def test_本文が空なら決めない():
    assert rule_type("", False, []) == ("", {})


def test_law_id_の組み方():
    assert egov_law_id({"公布日": "平成10年 3月25日", "法律番号": "7", "種別": "衆法"}) == "410AC1000000007"
    assert egov_law_id({"公布日": "令和元年 5月1日", "法律番号": "12", "種別": "閣法"}) == "501AC0000000012"
    assert egov_law_id({"公布日": "", "法律番号": "", "種別": "閣法"}) is None


def test_本文URLの組み方():
    assert honbun_url("閣法-211-11").endswith("/g21109011.htm")
    assert honbun_url("参法-164-5").endswith("/g16406005.htm")
    assert honbun_url("閣法-211-") is None


def test_照合の区分():
    assert status(SUBST, SUBST) == "一致"
    assert status(ROUTINE, SUBST) == "食い違い"
    assert status(NEW, NEW).startswith("一致（新規")
    assert status("保留", SUBST).startswith("照合できない")
    assert status(SUBST, "").startswith("照合できない")
