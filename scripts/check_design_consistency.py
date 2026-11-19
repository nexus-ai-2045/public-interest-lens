"""設計の整合の検査（点数設計 v2.1、設計決定0027）。定数・文書・仕様・コードが同じことを言っているかを機械で確かめる。

検査は4つ。何も書き換えない（読むだけ）。
  ① 固定定数   正本 app/src/scoring-constants.ts の値と、文書（計算式・評価方法設計書・ロードマップ・影響度ランキング・
               設計決定0027）、app/src/method-spec.ts、scripts/backtest*.py に書いてある数字が一致する
  ② 置き換え予定 【置き換え予定…】の印が残る節の一覧と件数（旧方式の節。コードの移行が終われば0になる）
  ③ 撤回した方式 Shapley 値による配分・群の額の本数割り・確かさ「低」の配分に触れる節が、v2.1 への置き換えを指している
               （＝「採用」のまま残っていない）。コードに残る実装は移行待ちとして数える
  ④ 完了の条件  docs/進め方.md 5章の4つ（評価台帳の全件、ロジック検査の違反0、抜き取り検証、公開前検査）の今の状態

終了コード：①か③に不一致があれば 1。--strict は、②の印と③のコードに残る実装が1件でもあれば 1（移行が終わったかの検査）。
④は状態を出すだけで、終了コードには入れない（完了の判定は人が表を見てする）。

使い方：python3 scripts/check_design_consistency.py            表（Markdown）を標準出力へ
        python3 scripts/check_design_consistency.py --strict   移行の残りがあれば失敗
        python3 scripts/check_design_consistency.py --json     機械向け
        python3 scripts/check_design_consistency.py --out PATH 表をファイルにも書く
        python3 scripts/check_design_consistency.py --root DIR 別の作業ツリー（PR のブランチなど）を調べる
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CONSTANTS_FILE = "app/src/scoring-constants.ts"
SPEC_FILE = "app/src/method-spec.ts"
FORMULA_DOC = "docs/計算式.md"
ADR_GLOB = "docs/adr/0027-*.md"

KEYS = ("hitRateFloor", "minContributingLaws", "topThreeShareCap", "certaintyFloor")
LABEL = {
    "hitRateFloor": "的中率の合格線",
    "minContributingLaws": "寄与法律数の下限",
    "topThreeShareCap": "上位3本の占有率の上限",
    "certaintyFloor": "確かさの下限",
}
CONSTANT_RE = {
    "hitRateFloor": r"^\s*hitRateFloor:\s*([0-9.]+)\s*,",
    "minContributingLaws": r"^\s*minContributingLaws:\s*([0-9]+)\s*,",
    "topThreeShareCap": r"^\s*topThreeShareCap:\s*([0-9.]+)\s*,",
    "certaintyFloor": r"^\s*certaintyFloor:\s*'([^']+)'\s*,",
}

# 見出し語と数字のあいだに入ってよい文字（表の区切り・助詞・かっこ・強調）
_SEP = r"(?:[\s|:：（(「*]|は|を|が)*"
_NUM = r"(\d+(?:\.\d+)?)"
_PCT = r"\s*[%％](?!\s*から)"  # 「95% から 80% に」のような変更の経緯は、今の値の主張として読まない

# (定数, 正規表現, 読み取った値の単位)。単位 pct は百分率、raw はそのまま、mark は確かさの印。
CLAIMS: list[tuple[str, re.Pattern[str], str]] = [
    ("hitRateFloor", re.compile(rf"的中率\s*{_NUM}{_PCT}"), "pct"),
    ("hitRateFloor", re.compile(rf"(?:合格線|合格の線){_SEP}(?:的中率|一致率)?\s*{_NUM}{_PCT}"), "pct"),
    ("hitRateFloor", re.compile(rf"{_NUM}\s*[%％]\s*以上\**\s*を合格"), "pct"),
    ("hitRateFloor", re.compile(rf"精度は?\s*{_NUM}\s*[%％]\s*以上"), "pct"),
    ("minContributingLaws", re.compile(rf"寄与法律数の?下限{_SEP}(\d+)"), "raw"),
    ("minContributingLaws", re.compile(r"\|\\+mathcal L_p\|\s*\\+ge\s*(\d+)"), "raw"),
    ("topThreeShareCap", re.compile(rf"上位3本の占有率の上限{_SEP}{_NUM}\s*[%％]"), "pct"),
    ("topThreeShareCap", re.compile(rf"上位3本.*\\+le\s*{_NUM}"), "raw"),
    ("certaintyFloor", re.compile(rf"確かさの下限{_SEP}(高|中|低|参考)"), "mark"),
    ("certaintyFloor", re.compile(r"確かさが(高|中|低|参考)以上"), "mark"),
]

ALL_KEYS = frozenset(KEYS)
HIT_ONLY = frozenset({"hitRateFloor"})
# 文書ごとに、書いてあるはずの定数（無ければ「記載なし」で不一致にする）
DOC_TARGETS: list[tuple[str, frozenset[str]]] = [
    (SPEC_FILE, ALL_KEYS),
    (FORMULA_DOC, ALL_KEYS),
    (ADR_GLOB, ALL_KEYS),
    ("docs/評価方法設計書.md", HIT_ONLY),
    ("docs/ロードマップ.md", HIT_ONLY),
    ("docs/影響度ランキング.md", HIT_ONLY),
]

REPLACE_MARK = "【置き換え予定"
# 撤回した方式に触れる節が持つべき、v2.1 への指し示し
V21_POINTER = re.compile(r"【置き換え予定|置き換え済み|設計決定\s*0027|0027-score-design|点数設計 v2\.1|score-design-v2\.1")
WITHDRAWN: list[tuple[str, re.Pattern[str]]] = [
    ("Shapley 値による配分", re.compile(r"shapley|シャープレイ", re.IGNORECASE)),
    ("群の額の本数割り", re.compile(r"本数で割(?!らない)|本数割り|observation-split")),
    ("確かさ「低」の配分", re.compile(r"「低」[^。\n]{0,12}配[るりっ]|「低」も印つき")),
]
# ③で見ない文書と、その理由（理由なしに足さない）
EXEMPT = {
    "docs/adr/0008-publish-everything-with-certainty-marks.md": "実名公開の線引き。設計決定0027 が「0008 は書き換えない」と決めている",
}
# コードに残る実装（移行待ち）を数える語。文書・テスト・仕様の清書は数えない。
CODE_RESIDUE: list[tuple[str, re.Pattern[str]]] = [
    ("Shapley 値による配分", re.compile(r"shapley", re.IGNORECASE)),
    ("群の額の本数割り", re.compile(r"splitRange|observationKey|observation-split")),
]
CODE_GLOBS = ("app/src/*.ts", "app/src/*.tsx", "scripts/*.py", "scripts/*.mjs")
CODE_SKIP = re.compile(r"\.test\.tsx?$|/method-spec\.ts$|/check_design_consistency\.py$|/scoring-")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def resolve(root: Path, rel: str) -> list[Path]:
    """相対パス（glob 可）を実在のファイルに直す。無ければ空。"""
    if any(c in rel for c in "*?["):
        return sorted(root.glob(rel))
    p = root / rel
    return [p] if p.is_file() else []


def rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


# ---------- ① 固定定数 ----------

def load_constants(root: Path) -> dict[str, float | str]:
    """正本から4つの定数を読む。1つでも読めなければ止める（正本が読めないまま「一致」と言わない）。"""
    path = root / CONSTANTS_FILE
    if not path.is_file():
        raise SystemExit(f"正本が無い：{CONSTANTS_FILE}")
    src = read_text(path)
    out: dict[str, float | str] = {}
    for key in KEYS:
        found = re.findall(CONSTANT_RE[key], src, flags=re.MULTILINE)
        if len(found) != 1:
            raise SystemExit(f"正本 {CONSTANTS_FILE} の {key} の定義が {len(found)} 個（1個のはず）")
        out[key] = found[0] if key == "certaintyFloor" else float(found[0])
    return out


def show(key: str, value: float | str) -> str:
    if key == "certaintyFloor":
        return f"「{value}」以上"
    if key == "minContributingLaws":
        return f"{value:g}"
    return f"{float(value) * 100:g}%"


def find_claims(text: str) -> list[dict]:
    """文書の中の「定数の値の主張」を拾う。同じ行の同じ数字を2つの型で拾っても1件。"""
    seen: set[tuple[str, int, int]] = set()
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        for key, pat, unit in CLAIMS:
            for m in pat.finditer(line):
                at = (key, no, m.start(1))
                if at in seen:
                    continue
                seen.add(at)
                raw = m.group(1)
                value: float | str = raw if unit == "mark" else (float(raw) / 100 if unit == "pct" else float(raw))
                out.append({"key": key, "line": no, "value": value, "text": m.group(0)})
    return out


def same(a: float | str, b: float | str) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return a == b
    return abs(a - b) < 1e-9


def check_constants(root: Path, constants: dict[str, float | str]) -> list[dict]:
    """文書と仕様とバックテストを、正本の値と1件ずつ照らす。status は 一致・不一致・記載なし・ファイルなし。"""
    rows: list[dict] = []
    for target, required in DOC_TARGETS:
        paths = resolve(root, target)
        if not paths:
            rows.append({"file": target, "key": "", "line": 0, "status": "ファイルなし", "found": "", "expected": ""})
            continue
        for path in paths:
            claims = find_claims(read_text(path))
            name = rel(root, path)
            for key in KEYS:
                mine = [c for c in claims if c["key"] == key]
                if not mine:
                    if key in required:
                        rows.append({"file": name, "key": key, "line": 0, "status": "記載なし", "found": "", "expected": show(key, constants[key])})
                    continue
                for c in mine:
                    rows.append({
                        "file": name, "key": key, "line": c["line"],
                        "status": "一致" if same(c["value"], constants[key]) else "不一致",
                        "found": show(key, c["value"]), "expected": show(key, constants[key]),
                    })
    rows += check_backtest_targets(root, float(constants["hitRateFloor"]))
    return rows


def check_backtest_targets(root: Path, expected: float) -> list[dict]:
    """scripts/backtest*.py の合格線。数字で書くか、別のバックテストの TARGET を借りるか。数字の置き場所は1つだけ。"""
    rows = []
    literals = 0
    paths = resolve(root, "scripts/backtest*.py")
    for path in paths:
        name = rel(root, path)
        for no, line in enumerate(read_text(path).splitlines(), 1):
            m = re.match(r"TARGET\s*=\s*([^#\n]+)", line)
            if not m:
                continue
            rhs = m.group(1).strip()
            row = {"file": name, "key": "hitRateFloor", "line": no, "expected": show("hitRateFloor", expected)}
            if re.fullmatch(r"[0-9.]+", rhs):
                literals += 1
                rows.append(row | {"status": "一致" if same(float(rhs), expected) else "不一致", "found": show("hitRateFloor", float(rhs))})
            elif re.fullmatch(r"\w+\.TARGET", rhs):
                rows.append(row | {"status": "一致", "found": f"{rhs}（借用）"})
            else:
                rows.append(row | {"status": "不一致", "found": f"読めない式：{rhs}"})
    if not paths:
        rows.append({"file": "scripts/backtest*.py", "key": "hitRateFloor", "line": 0, "status": "ファイルなし", "found": "", "expected": ""})
    elif literals != 1:
        rows.append({"file": "scripts/backtest*.py", "key": "hitRateFloor", "line": 0, "status": "不一致",
                     "found": f"数字の定義が {literals} 個", "expected": "1個（Python 側の置き場所は1つ）"})
    return rows


# ---------- 節の切り方（②③で共用） ----------

def markdown_units(text: str) -> list[dict]:
    """Markdown を「## 見出し」ごとの節に切る。最初の見出しより前は（冒頭）。"""
    units = [{"title": "（冒頭）", "line": 1, "lines": []}]
    for no, line in enumerate(text.splitlines(), 1):
        if line.startswith("## "):
            units.append({"title": line[3:].strip(), "line": no, "lines": []})
        units[-1]["lines"].append(line)
    return _join(units)


def spec_units(text: str) -> list[dict]:
    """method-spec.ts を節（id: '…' から次の id まで）に切る。節の配列の外は1行ずつ。"""
    units: list[dict] = []
    current: dict | None = None
    for no, line in enumerate(text.splitlines(), 1):
        m = re.match(r"\s+id: '([^']+)'", line)
        if m:
            current = {"title": m.group(1), "line": no, "lines": [line], "status": ""}
            units.append(current)
            continue
        if current is not None and line.strip() == "];":
            current = None
            continue
        if current is None:
            units.append({"title": f"{no} 行目", "line": no, "lines": [line]})
            continue
        current["lines"].append(line)
        t = re.match(r"\s+title: '([^']+)'", line)
        if t:
            current["title"] = f"{current['title']}（{t.group(1)}）"
        s = re.match(r"\s+status: '([^']+)'", line)
        if s:
            current["status"] = s.group(1)
    return _join(units)


def whole_file_unit(text: str) -> list[dict]:
    return [{"title": "（ファイル全体）", "line": 1, "text": text}]


def _join(units: list[dict]) -> list[dict]:
    for u in units:
        u["text"] = "\n".join(u.pop("lines"))
    return units


def units_of(root: Path, path: Path) -> list[dict]:
    name = rel(root, path)
    text = read_text(path)
    if name == SPEC_FILE:
        return spec_units(text)
    if name == FORMULA_DOC:
        return markdown_units(text)
    return whole_file_unit(text)  # 設計決定などは、冒頭の注記がファイル全体にかかる


def design_docs(root: Path) -> list[Path]:
    """設計を述べる文書：docs 直下、設計決定、仕様。報告・学習記録・提案は過去の記録なので見ない。"""
    return sorted(root.glob("docs/*.md")) + sorted(root.glob("docs/adr/*.md")) + resolve(root, SPEC_FILE)


# ---------- ② 置き換え予定の印 ----------

def check_replace_marks(root: Path) -> list[dict]:
    out = []
    for path in design_docs(root):
        name = rel(root, path)
        units = spec_units(read_text(path)) if name == SPEC_FILE else markdown_units(read_text(path))
        for u in units:
            for offset, line in enumerate(u["text"].splitlines()):
                if REPLACE_MARK in line:
                    out.append({"file": name, "line": u["line"] + offset, "section": u["title"]})
    return out


# ---------- ③ 撤回した方式 ----------

def check_withdrawn(root: Path) -> dict:
    """文書：撤回した方式に触れる節が v2.1 を指しているか。コード：実装がまだ残るファイルを数える。"""
    stale, pointed, exempt = [], 0, []
    for path in design_docs(root):
        name = rel(root, path)
        if name in EXEMPT:
            exempt.append({"file": name, "reason": EXEMPT[name]})
            continue
        for u in units_of(root, path):
            hits = [label for label, pat in WITHDRAWN if pat.search(u["text"])]
            if not hits:
                continue
            if V21_POINTER.search(u["text"]):
                pointed += 1
                continue
            stale.append({"file": name, "line": u["line"], "section": u["title"], "methods": hits,
                          "status": u.get("status", "")})
    residue = []
    for pattern in CODE_GLOBS:
        for path in sorted(root.glob(pattern)):
            name = rel(root, path)
            if CODE_SKIP.search("/" + name):
                continue
            text = read_text(path)
            hits = [label for label, pat in CODE_RESIDUE if pat.search(text)]
            if hits:
                residue.append({"file": name, "methods": hits})
    return {"stale": stale, "pointed": pointed, "exempt": exempt, "residue": residue}


# ---------- ④ 完了の条件（docs/進め方.md 5章） ----------

def _logic_counts_from_repo() -> dict[str, int]:
    sys.path.insert(0, str(ROOT))
    from scripts import check_evaluation_logic as logic

    return {rule: len(found) for rule, found in logic.check().items()}


def completion_status(root: Path, logic_counts=None) -> list[dict]:
    """4つの条件の今の状態。state は 達成・未達・未実行。測れないものを達成にしない。"""
    d = root / "data" / "derived"
    rows = []

    # 1. 評価台帳の全件：全法律が「額あり」か「額なし＋理由」で載っている
    ledger_path, outcomes_path = d / "evaluation-ledger-v1" / "ledger.csv", d / "all-laws-v1" / "outcomes.csv"
    ledger: list[dict[str, str]] = []
    if ledger_path.is_file() and outcomes_path.is_file():
        ledger = read_csv(ledger_path)
        target = {r["id"] for r in read_csv(outcomes_path)}
        listed = {r["id"] for r in ledger}
        with_amount = sum(1 for r in ledger if r["額（円）"] or r["国の収支（億円）"])
        with_reason = sum(1 for r in ledger if not (r["額（円）"] or r["国の収支（億円）"]) and r["到達点"])
        neither = len(ledger) - with_amount - with_reason
        missing = len(target - listed)
        persons = d / "person-ids" / "persons.csv"
        people = f"。人物台帳 {len(read_csv(persons)):,} 人" if persons.is_file() else ""
        rows.append({
            "no": 1, "name": "評価台帳の全件",
            "state": "達成" if not missing and not neither and len(listed) == len(ledger) else "未達",
            "now": f"対象 {len(target):,} 本中、台帳に {len(target & listed):,} 本（額あり {with_amount:,}、額なし＋到達点 {with_reason:,}、どちらでもない {neither:,}、台帳に無い {missing:,}）{people}",
            "how": "data/derived/evaluation-ledger-v1/ledger.csv を all-laws-v1/outcomes.csv と照合",
        })
    else:
        rows.append({"no": 1, "name": "評価台帳の全件", "state": "未実行", "now": "台帳か全法律の一覧が無い",
                     "how": "python3 scripts/build_evaluation_ledger.py build"})

    # 2. ロジック検査の違反0
    try:
        counts = (logic_counts or _logic_counts_from_repo)() if (logic_counts or root == ROOT) else None
    except (OSError, KeyError) as e:  # 派生データが無い環境
        counts, note = None, f"測れない（{type(e).__name__}）"
    else:
        note = "測っていない（リポジトリの外）"
    if counts is None:
        rows.append({"no": 2, "name": "ロジック検査の違反0", "state": "未実行", "now": note,
                     "how": "python3 scripts/check_evaluation_logic.py"})
    else:
        total = sum(counts.values())
        rows.append({"no": 2, "name": "ロジック検査の違反0", "state": "達成" if total == 0 else "未達",
                     "now": "違反 " + "・".join(f"{k} {v}" for k, v in sorted(counts.items())) + f"（計 {total:,} 本）",
                     "how": "scripts/check_evaluation_logic.py の check()（tests/test_evaluation_logic.py と同じ規則）"})

    # 3. 抜き取り検証：不合格0
    sample_path, verdict_path = d / "evaluation-ledger-v1" / "sample.csv", d / "evaluation-ledger-v1" / "sample-verdicts.csv"
    if sample_path.is_file() and verdict_path.is_file() and ledger:
        sample = {r["id"] for r in read_csv(sample_path)}
        verdicts = Counter(r["判定"] for r in read_csv(verdict_path) if r["id"] in sample)
        judged = sum(verdicts.values())
        state = Counter(r["検証状態"] for r in ledger if r["id"] in sample)
        still_failed, demoted = state["抜き取り検証で不合格"], state["参考に下げた"]
        rows.append({
            "no": 3, "name": "抜き取り検証（不合格0が目標）",
            "state": "達成" if judged == len(sample) and still_failed == 0 else "未達",
            "now": f"抜き取り {len(sample):,} 本中、判定済み {judged:,} 本（合格 {verdicts['合格']:,}、不合格 {verdicts['不合格']:,}）。不合格のうち参考に下げた {demoted:,} 本、不合格のまま {still_failed:,} 本",
            "how": "sample.csv・sample-verdicts.csv と台帳の検証状態。やり直しの有無は判定の中身からは分からない",
        })
    else:
        rows.append({"no": 3, "name": "抜き取り検証（不合格0が目標）", "state": "未実行", "now": "抜き取りか判定の記録が無い",
                     "how": "python3 scripts/build_evaluation_ledger.py sample"})

    # 4. 公開前検査：release_check.py が残した最新の記録を読む（ここでは走らせない）
    records = sorted((root / ".local" / "release-check").glob("*.json"))
    if records:
        steps = json.loads(read_text(records[-1]))
        bad = [s["step"] for s in steps if not s["ok"]]
        rows.append({"no": 4, "name": "公開前検査（出典・議員ページ・個人名義）", "state": "未達" if bad else "達成",
                     "now": f"{records[-1].stem} の記録：{len(steps) - len(bad)}/{len(steps)} 合格" + (f"（失敗：{'、'.join(bad)}）" if bad else ""),
                     "how": "python3 scripts/release_check.py の記録（.local/release-check/）。記録より後の変更は見ていない"})
    else:
        rows.append({"no": 4, "name": "公開前検査（出典・議員ページ・個人名義）", "state": "未実行", "now": "記録が無い",
                     "how": "python3 scripts/release_check.py"})
    return rows


# ---------- まとめ ----------

def run(root: Path = ROOT, logic_counts=None) -> dict:
    constants = load_constants(root)
    return {
        "constants": {k: show(k, v) for k, v in constants.items()},
        "constant_rows": check_constants(root, constants),
        "replace_marks": check_replace_marks(root),
        "withdrawn": check_withdrawn(root),
        "completion": completion_status(root, logic_counts),
    }


def verdict(result: dict, strict: bool) -> tuple[bool, list[str]]:
    """合否と理由。①③は常に、②と③のコードの残りは --strict のときだけ合否に入れる。"""
    reasons = []
    bad = [r for r in result["constant_rows"] if r["status"] != "一致"]
    if bad:
        reasons.append(f"① 固定定数の不一致 {len(bad)} 件")
    if result["withdrawn"]["stale"]:
        reasons.append(f"③ 撤回した方式が v2.1 を指さずに残る節 {len(result['withdrawn']['stale'])} 件")
    if strict:
        if result["replace_marks"]:
            reasons.append(f"② 置き換え予定の印 {len(result['replace_marks'])} 件（--strict）")
        if result["withdrawn"]["residue"]:
            reasons.append(f"③ コードに残る旧方式 {len(result['withdrawn']['residue'])} ファイル（--strict）")
    return (not reasons, reasons)


def render(result: dict, strict: bool) -> str:
    ok, reasons = verdict(result, strict)
    rows = result["constant_rows"]
    bad = [r for r in rows if r["status"] != "一致"]
    w = result["withdrawn"]
    out = ["# 設計の整合の検査（点数設計 v2.1）", "",
           f"判定：{'合格' if ok else '不合格'}{'（--strict）' if strict else ''}" + ("" if ok else "　" + "／".join(reasons)), "",
           "## ① 固定定数", "",
           "正本 `app/src/scoring-constants.ts`：" + "、".join(f"{LABEL[k]} {v}" for k, v in result["constants"].items()), "",
           f"照らした記載 {len(rows)} 件中、一致 {len(rows) - len(bad)} 件、不一致・記載なし {len(bad)} 件。", ""]
    if bad:
        out += ["| ファイル | 行 | 定数 | 状態 | 書いてある値 | 正本の値 |", "|---|---|---|---|---|---|"]
        out += [f"| {r['file']} | {r['line'] or '-'} | {LABEL.get(r['key'], '-')} | {r['status']} | {r['found'] or '-'} | {r['expected'] or '-'} |" for r in bad]
        out.append("")
    marks = result["replace_marks"]
    out += ["## ② 置き換え予定の印が残る節", "",
            f"{len(marks)} 件（コードの移行が終わり、旧い節を消すと 0 になる。--strict では 1 件でも失敗）。", ""]
    if marks:
        out += ["| ファイル | 行 | 節 |", "|---|---|---|"]
        out += [f"| {m['file']} | {m['line']} | {m['section']} |" for m in marks]
        out.append("")
    out += ["## ③ 撤回した方式（Shapley 値による配分・群の額の本数割り・確かさ「低」の配分）", "",
            f"文書：触れている節 {w['pointed'] + len(w['stale'])} 件中、v2.1（設計決定0027）を指している {w['pointed']} 件、指さずに残る {len(w['stale'])} 件。", ""]
    if w["stale"]:
        out += ["| ファイル | 行 | 節 | 状態 | 残っている方式 |", "|---|---|---|---|---|"]
        out += [f"| {s['file']} | {s['line']} | {s['section']} | {s['status'] or '-'} | {'、'.join(s['methods'])} |" for s in w["stale"]]
        out.append("")
    out += [f"見ない文書：{e['file']}（{e['reason']}）" for e in w["exempt"]] + ([""] if w["exempt"] else [])
    out += [f"コード：旧方式の実装が残るファイル {len(w['residue'])} 件（移行待ち。--strict では 1 件でも失敗）。", ""]
    if w["residue"]:
        out += ["| ファイル | 残っている方式 |", "|---|---|"]
        out += [f"| {r['file']} | {'、'.join(r['methods'])} |" for r in w["residue"]]
        out.append("")
    done = sum(1 for c in result["completion"] if c["state"] == "達成")
    out += ["## ④ 完了の条件（docs/進め方.md 5章）", "",
            f"4 条件中、達成 {done} 件（この表は状態を出すだけで、合否には入れない）。", "",
            "| # | 条件 | 状態 | いま | 測り方 |", "|---|---|---|---|---|"]
    out += [f"| {c['no']} | {c['name']} | {c['state']} | {c['now']} | {c['how']} |" for c in result["completion"]]
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--strict", action="store_true", help="置き換え予定の印とコードに残る旧方式が1件でもあれば失敗")
    ap.add_argument("--json", action="store_true", help="結果を JSON で出す")
    ap.add_argument("--out", type=Path, help="表（Markdown）をこのファイルにも書く")
    ap.add_argument("--root", type=Path, default=ROOT, help="別の作業ツリーを調べる（PR のブランチなど）。既定はこのリポジトリ")
    args = ap.parse_args(argv)
    result = run(args.root.resolve())
    ok, reasons = verdict(result, args.strict)
    text = render(result, args.strict)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(json.dumps(result | {"ok": ok, "reasons": reasons}, ensure_ascii=False, indent=1) if args.json else text, end="")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
