"""抜き取り検証の結果（sample-verdicts.csv・verification-raw/）から docs/評価の独立検証.md を作る。手で直さない。"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.build_evaluation_ledger import (
    REDO_DEMOTED_MEMO,
    REDO_PASS_MEMO,
)

ROOT = Path(__file__).resolve().parents[1]
L = ROOT / "data" / "derived" / "evaluation-ledger-v1"
CAUSE = {
    "範囲": "仕組みの欠陥：産業全体の差を、法律の対象の広さに合わせずに当てている",
    "分野": "仕組みの欠陥：題名の語の規則（D1）や AI 分野ラベルが、法律の中身と別の分野を選んでいる",
    "分類": "仕組みの欠陥：制度・名称整備の法律を『評価対象』に振り分けている（2系統が同じ型で誤る）",
    "類型": "仕組みの欠陥：定型改正と実質改正の境目の語の規則",
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - m) / d, (c + m) / d)


def redo_section(v: dict, led: dict) -> list[str]:
    """やり直しの結果。台帳の検証状態（初回の判定＋自動の降格＋読み直しの決着）から数える。決着の表が無ければ出さない。"""
    path = L / "sample-resolutions.csv"
    if not path.exists():
        return []
    used = {i for i in v if led[i]["検証メモ"].startswith((REDO_PASS_MEMO, REDO_DEMOTED_MEMO))}
    res = [r for r in csv.DictReader(path.read_text(encoding="utf-8").splitlines()) if r["id"] in used]
    state = Counter(led[i]["検証状態"] for i in v)
    n = len(v)
    fixed = sum(led[i]["検証メモ"].startswith(REDO_PASS_MEMO) for i in used)
    lowered = sum(led[i]["検証メモ"].startswith(REDO_DEMOTED_MEMO) for i in used)
    auto = state["参考に下げた"] - lowered
    out = ["", "## やり直しの結果（不合格のまま残った法律の読み直し）", "",
           "初回と同じ抜き取り（同じ本数・同じ法律）を、今の台帳に当て直した。新しく抜き取り直してはいない。",
           "",
           f"- 抜き取り {n} 本中、**不合格のまま {state['抜き取り検証で不合格']} 本**、合格 {state['抜き取り検証で合格']} 本、参考に下げた {state['参考に下げた']} 本。",
           "- 定義：「不合格のまま」は、初回に不合格で、額が順位・議員配分に使われない参考値にもなっておらず、読み直しの決着も付いていない法律。",
           f"- 内訳：初回の合格 {len([i for i in v if v[i]['判定'] == '合格'])} 本はそのまま。初回の不合格 {len([i for i in v if v[i]['判定'] == '不合格'])} 本のうち、額を参考値に下げたもの {auto} 本（規則で自動）、読み直しで合格に訂正 {fixed} 本、読み直しで参考に下げた {lowered} 本。",
           "- 読み直しの方法：サイトの値も初回の判定も見せない2系統（Haiku、系統Aは議案本文を先に、系統Bは会議録を先に読む）が一次資料から類型と「経済に効くか」を判定し、初回と結論が変わる項目と照合の読み方は Opus が一次資料で裁定した。決着は `scripts/resolve_sample_failures.py` の規則で機械的に決める。",
           "- 記録：指示文（版 v1）・2系統の判定・裁定・前提は `data/derived/evaluation-ledger-v1/reverification-v1/`、1本ごとの決着は `sample-resolutions.csv`。",
           "- 参考に下げた法律は、サイトの値がまだ直っていない。額が無い（または国の収支の別欄だけ）ので、順位・議員配分には初めから入っていない。サイトの値と読み直しの値を下の表に並べて出し続ける。",
           "- 限界：これは抜き取った法律についての結果。抜き取っていない法律に同じ型の誤りが残っているかは、この表からは分からない。",
           "", "| id | 題名 | 決着 | 原因の区分 | 理由 | 参考値 |", "|---|---|---|---|---|---|"]
    out += [f"| {r['id']} | {led[r['id']]['題名'][:28]} | {r['決着']} | {r['原因の区分']} | {r['理由'].replace('|', '/')} | {r['参考値'].replace('|', '/')} |" for r in res]
    out += ["", "根拠の URL は `sample-resolutions.csv` の「根拠URL」の列にある。"]
    return out


def main() -> int:
    v = {r["id"]: r for r in csv.DictReader(Path(L / "sample-verdicts.csv").read_text(encoding="utf-8").splitlines())}
    led = {r["id"]: r for r in csv.DictReader(Path(L / "ledger.csv").read_text(encoding="utf-8").splitlines())}
    A = {x["id"]: x for x in json.loads(Path(L / "verification-raw" / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads(Path(L / "verification-raw" / "lineB.json").read_text(encoding="utf-8"))}
    n = len(v)
    fail = [i for i in v if v[i]["判定"] == "不合格"]
    ok = [i for i in v if v[i]["判定"] == "合格"]
    lo, hi = wilson(len(fail), n)
    lines = ["# 法律の評価の独立検証（抜き取り）", "",
             "このファイルは `python3 scripts/report_verification.py` が作ります。手で直さないでください。", "",
             "## 方法", "",
             "- 全3,415本から、到達点×分類の方法（参考額は分野の由来も）で層をつくり、無作為（乱数の種 20261030）で抜き取った。",
             "- 抜き取った法律の題名だけを、評価サイトの値を見せない2系統（Sonnet）に渡し、一次資料（国会会議録・議案本文）から類型・分類・分野・範囲を独立に判定させた。系統Aは条文を先に、系統Bは会議録を先に読む。",
             "- 2系統が一致した項目をサイトと突き合わせ、割れた項目は Opus が一次資料で裁定した。",
             "- 範囲の基準：サイトの参考額は産業全体の付加価値の差。法律の対象が産業の一部なら過大で不合格。",
             "- 注意：議案本文が取れず会議録だけで判定した行がある（確信=低）。2系統の判定も誤りうる。確信=低の行を除いた数字も併記する。", "",
             "## 結果", "",
             f"- 抜き取り {n} 本のうち **不合格 {len(fail)} 本（{len(fail)/n:.0%}、95%区間 {lo:.0%}〜{hi:.0%}）**、合格 {len(ok)} 本。"]
    hc = [i for i in v if A[i]["確信"] != "低" and B[i]["確信"] != "低"]
    f_hc = [i for i in hc if v[i]["判定"] == "不合格"]
    lo2, hi2 = wilson(len(f_hc), len(hc))
    lines += [f"- 両系統とも確信が中以上の {len(hc)} 本だけでは、不合格 {len(f_hc)} 本（{len(f_hc)/max(1,len(hc)):.0%}、95%区間 {lo2:.0%}〜{hi2:.0%}）。", ""]
    # 項目別
    kinds = Counter()
    for i in fail:
        seen = set()
        for d in v[i]["食い違い"].split("／"):
            k = d.split("：")[0]
            if k in CAUSE and k not in seen:
                seen.add(k)
                kinds[k] += 1
    lines += ["### 誤りの種類と原因", "", "| 種類 | 不合格のうち含む本数 | 原因 |", "|---|---|---|"]
    lines += [f"| {k} | {c} | {CAUSE[k]} |" for k, c in kinds.most_common()]
    # 層別
    st = defaultdict(lambda: [0, 0])
    for i in v:
        k = led[i]["到達点"]
        st[k][1] += 1
        st[k][0] += v[i]["判定"] == "不合格"
    lines += ["", "### 到達点ごとの不合格率", "", "| 到達点 | 抜き取り | 不合格 | 率 |", "|---|---|---|---|"]
    lines += [f"| {k} | {t} | {f} | {f/t:.0%} |" for k, (f, t) in sorted(st.items())]
    # 2系統一致率
    agree = Counter()
    for i in v:
        for k in ("類型", "経済に効くか", "範囲"):
            agree[(k, A[i][k] == B[i][k])] += 1
    lines += ["", "### 2系統の判定の一致率（判定者どうし）", "", "| 項目 | 一致 | 全体 |", "|---|---|---|"]
    lines += [f"| {k} | {agree[(k, True)]} | {n} |" for k in ("類型", "経済に効くか", "範囲")]
    lines += ["", "## 不合格の全件", "", "| id | 題名 | 到達点 | 食い違い |", "|---|---|---|---|"]
    lines += [f"| {i} | {led[i]['題名'][:28]} | {led[i]['到達点']} | {v[i]['食い違い'].replace('|', '/')} |" for i in sorted(fail)]
    lines += redo_section(v, led)
    (ROOT / "docs" / "評価の独立検証.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"不合格 {len(fail)}/{n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
