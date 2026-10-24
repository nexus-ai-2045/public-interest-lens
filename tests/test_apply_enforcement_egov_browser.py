from scripts.apply_enforcement_egov_browser import judge, month_end_next

NUM = "平成十年法律第百二十六号"


def row(**kw):
    base = {"id": "衆法-143-1", "法令番号": NUM, "公布日": "1998-10-16", "施行日": "", "取得方法": "",
            "備考": "", "出典URL": "", "施行日の候補（; 区切り）": "",
            "施行期日の原文": "第一条　この法律は、公布の日から起算して六月を超えない範囲内において政令で定める日から施行する。"}
    base.update(kw)
    return base


def test_month_end_next_uses_last_day_of_month():
    text = "この法律は、公布の日から起算して一月を経過した日から施行する。"
    assert month_end_next("2020-01-31", text) == "2020-03-01"
    assert month_end_next("2020-01-15", text) is None  # 応当日がある月は通常の計算に任せる


def test_two_subordinate_orders_agree():
    res = {"id": "衆法-143-1", "A": [], "B": {}, "T": "", "C": [
        ["411CO0000000014", "施行令", "平成十一年政令第十四号", "附則（施行期日）１この政令は、法の施行の日（平成十一年二月一日）から施行する。"],
        ["411M50000010004", "施行規則", "平成十一年法務省令第四号", "附則この省令は、法の施行の日（平成十一年二月一日）から施行する。"],
    ]}
    got = judge(row(), res)
    assert got["date"] == "1999-02-01"
    assert "2系統" in got["method"]


def test_subordinate_order_outside_window_is_not_used():
    res = {"id": "x", "A": [], "B": {}, "T": "", "C": [
        ["a", "施行令", "", "この政令は、法の施行の日（平成十二年二月一日）から施行する。"],
    ]}
    got = judge(row(), res)
    assert got["date"] == ""
    assert "2000-02-01" in got["cands"]


def test_decree_disagreeing_with_revision_is_held():
    a = [["x", "某施行令", "amendsupplprovision",
          f"この政令は、債権管理回収業に関する特別措置法（{NUM}）の施行の日（平成十一年二月一日）から施行する。"]]
    res = {"id": "x", "A": a, "B": {"L": {"own": False, "ex": ["1999-03-01"], "orig": []}}, "T": ""}
    got = judge(row(), res)
    assert got["date"] == ""
    assert "一致しない" in got["reason"]


def test_decree_matching_revision_is_two_systems():
    a = [["x", "某施行令", "amendsupplprovision",
          f"この政令は、債権管理回収業に関する特別措置法（{NUM}）の施行の日（平成十一年二月一日）から施行する。"]]
    res = {"id": "x", "A": a, "B": {"L": {"own": False, "ex": ["1999-02-01"], "orig": []}}, "T": ""}
    got = judge(row(), res)
    assert got["date"] == "1999-02-01"
    assert "2系統" in got["method"]


def test_later_of_fixed_date_and_promulgation():
    r = row(公布日="2018-06-01", 施行期日の原文="（施行期日）第一条この法律は、平成三十年四月一日又はこの法律の公布の日のいずれか遅い日から施行する。")
    got = judge(r, {"id": "x", "A": [], "B": {}, "T": ""})
    assert got["date"] == "2018-06-01"


def test_original_version_outside_deadline_is_not_used():
    # e-Gov が古い版を持たず、初めの版が後年の版になっている例
    r = row(公布日="2012-03-29", 施行期日の原文="第一条この法律は、公布の日から起算して三月を超えない範囲内において政令で定める日から施行する。")
    res = {"id": "x", "A": [], "T": "", "B": {"L": {"own": True, "ex": [], "orig": ["2021-04-01"]}}}
    assert judge(r, res)["date"] == ""


def test_proviso_deadline_is_not_used_for_main_clause():
    r = row(公布日="2004-06-18", 施行期日の原文="第一条この法律は、協定の効力発生の日から施行する。ただし、第十三条の規定は、公布の日から起算して三月を超えない範囲内において政令で定める日から施行する。")
    res = {"id": "x", "A": [], "T": "", "B": {"L": {"own": True, "ex": [], "orig": []}}}
    assert judge(r, res)["date"] == ""
