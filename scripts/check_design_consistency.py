"""設計の整合の検査（点数設計 v2.1、設計決定0027）。定数・文書・仕様・コードが同じことを言っているかを機械で確かめる。

検査は4つ。何も書き換えない（読むだけ）。
  ① 固定定数   正本 app/src/scoring-constants.ts の値と、文書（計算式・評価方法設計書・ロードマップ・影響度ランキング・
               設計決定0027）、app/src/method-spec.ts、scripts/backtest*.py に書いてある数字が一致する
  ② 置き換え予定 【置き換え予定…】の印が残る節の一覧と件数（旧方式の節。コードの移行が終われば0になる）
  ③ 撤回した方式 Shapley 値による配分・群の額の本数割り・確かさ「低」の配分に触れる節が、v2.1 への置き換えを指している
               （＝「採用」のまま残っていない）。コードに残る実装は移行待ちとして数える
  ④ 完了の条件  docs/進め方.md 5章の4つ（評価台帳の全件、ロジック検査の違反0、抜き取り検証、公開前検査）の今の状態

終了コード：①か③に不一致があれば 1。--strict は、②の印と③のコードに残る実装が1件でもあれば 1（移行が終わったかの検査）。
④は状態を出すだけで、終了コードには入れない（完了の判定は人が表を見てする）。材料が無い条件は「未実行」と出す。

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
_MARK = r"(高|中|低|参考)(?=」|以上|\s*\||[。、）)\s]|$)"  # 「下限を高くする」の「高」は印ではない
_LE = r"(?:\\+leq?|≤)"
_GE = r"(?:\\+geq?|≥)"
# 直前にこの語があれば、過去の値の話（今の値の主張ではない）
_PAST = re.compile(r"(?:以前|当時|従来|旧い?|まで)の?\s*$")

# (定数, 正規表現, 読み取った値の単位)。pct は百分率、raw はそのまま（後ろに % があれば百分率）、mark は確かさの印。
# 「的中率 62%」のような測った結果は合格線の主張ではないので、的中率の型は「以上」「の合格線」が続くときだけ拾う。
CLAIMS: list[tuple[str, re.Pattern[str], str]] = [
    ("hitRateFloor", re.compile(rf"的中率\s*{_NUM}{_PCT}\s*(?:以上|の合格線)"), "pct"),
    ("hitRateFloor", re.compile(rf"(?:合格線|合格の線){_SEP}(?:的中率|一致率)?\s*{_NUM}{_PCT}"), "pct"),
    ("hitRateFloor", re.compile(rf"{_NUM}\s*[%％]\s*以上\**\s*を合格"), "pct"),
    ("hitRateFloor", re.compile(rf"精度は?\s*{_NUM}\s*[%％]\s*以上"), "pct"),
    ("minContributingLaws", re.compile(rf"寄与法律数の?下限{_SEP}(\d+)"), "raw"),
    ("minContributingLaws", re.compile(rf"\|\\+mathcal L_p\|\s*{_GE}\s*(\d+)"), "raw"),
    ("topThreeShareCap", re.compile(rf"上位3本の占有率の上限{_SEP}{_NUM}\s*[%％]"), "pct"),
    ("topThreeShareCap", re.compile(rf"上位3本.*?{_LE}\s*{_NUM}(?P<pct>\s*\\*[%％])?"), "raw"),
    ("certaintyFloor", re.compile(rf"確かさの下限{_SEP}{_MARK}"), "mark"),
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
    ("群の額の本数割り", re.compile(r"本数で割|本数割り|本数で等分|observation-split")),
    ("確かさ「低」の配分", re.compile(r"「低」[^。\n]{0,30}配(?:分|る|り|っ)|配るのは[^。\n]*「低」|「低」も印つき")),
]
# 同じ文の中でこう言っていれば「使っている」ではない（使わない・やめた、の説明）
NEGATION = re.compile(r"ない|ません|せず|らず|やめ|撤回|廃止|不採用")
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
                if at in seen or _PAST.search(line[:m.start()]):
                    continue
                seen.add(at)
                raw = m.group(1)
                percent = unit == "pct" or bool(m.groupdict().get("pct"))
                value: float | str = raw if unit == "mark" else (float(raw) / 100 if percent else float(raw))
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


def _join(units: list[dict]) -> list[dict]:
    for u in units:
        u["text"] = "\n".join(u.pop("lines"))
    return units


def design_docs(root: Path) -> list[Path]:
    """設計を述べる文書：docs 直下、設計決定、仕様。報告・学習記録・提案は過去の記録なので見ない。"""
    return sorted(root.glob("docs/*.md")) + sorted(root.glob("docs/adr/*.md")) + resolve(root, SPEC_FILE)


def units_of(root: Path, path: Path) -> list[dict]:
    text = read_text(path)
    return spec_units(text) if rel(root, path) == SPEC_FILE else markdown_units(text)


# ---------- ② 置き換え予定の印 ----------

def check_replace_marks(root: Path) -> list[dict]:
    out = []
    for path in design_docs(root):
        name = rel(root, path)
        for u in units_of(root, path):
            for offset, line in enumerate(u["text"].splitlines()):
                if REPLACE_MARK in line:
                    out.append({"file": name, "line": u["line"] + offset, "section": u["title"]})
    return out


# ---------- ③ 撤回した方式 ----------

def withdrawn_hits(text: str) -> list[str]:
    """節の中で「使っている」と読める撤回済みの方式。同じ文で否定している（割らない・配りません）ものは数えない。"""
    hits = []
    for label, pat in WITHDRAWN:
        for m in pat.finditer(text):
            end = min((i for i in (text.find("。", m.start()), text.find("\n", m.start())) if i != -1), default=len(text))
            if not NEGATION.search(text[m.start():end]):
                hits.append(label)
                break
    return hits


def file_note_points_to_v21(name: str, units: list[dict]) -> bool:
    """冒頭（最初の見出しより前）の「置き換え」の注記は、その文書全体にかかる。

    計算式と仕様は節ごとに版と状態を持つので、冒頭の注記では済ませない（節ごとに印が要る）。
    """
    if name in (SPEC_FILE, FORMULA_DOC) or not units:
        return False
    head = units[0]["text"]
    return "置き換え" in head and bool(V21_POINTER.search(head))


def check_withdrawn(root: Path) -> dict:
    """文書：撤回した方式に触れる節が v2.1 を指しているか。コード：実装がまだ残るファイルを数える。"""
    stale, pointed, exempt = [], 0, []
    for path in design_docs(root):
        name = rel(root, path)
        if name in EXEMPT:
            exempt.append({"file": name, "reason": EXEMPT[name]})
            continue
        units = units_of(root, path)
        covered = file_note_points_to_v21(name, units)
        for u in units:
            hits = withdrawn_hits(u["text"])
            if not hits:
                continue
            if covered or V21_POINTER.search(u["text"]):
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

class NotMeasured(Exception):
    """測る材料が無い。達成にも未達にもせず「未実行」と出す。"""


def _logic_counts_from_repo() -> dict[str, int]:
    sys.path.insert(0, str(ROOT))
    from scripts import check_evaluation_logic as logic

    return {rule: len(found) for rule, found in logic.check().items()}


def _amount(row: dict[str, str]) -> bool:
    return bool(row["額（円）"] or row["国の収支（億円）"])


EXPOSURE = Path("data/derived/exposure-v1/exposure-ranking.json")


def _members_on_ledger(root: Path, d: Path) -> tuple[bool, str]:
    """議員の側：人物台帳（persons.csv）の全員が、曝露ランキングの公開用出力に「点あり」か「点なし＋理由」で1回ずつ載っている。
    (全員そろったか, 説明) を返す。出力が無ければ測れない（generate_artifacts.py が作る）。"""
    persons, exposure = d / "person-ids" / "persons.csv", root / EXPOSURE
    if not persons.is_file():
        return False, "議員：人物台帳が無く、測れない"
    rows = read_csv(persons)
    blank = sum(1 for r in rows if not (r.get("人物ID") or "").strip())
    ledger = {r["人物ID"] for r in rows if (r.get("人物ID") or "").strip()}
    blank_note = f"。人物IDの空の行 {blank:,}（台帳の誤り）" if blank else ""
    if not exposure.is_file():
        return False, f"議員：曝露ランキングの出力（{EXPOSURE}）が無く、測れない（台帳 {len(ledger):,} 人{blank_note}）"
    data = json.loads(exposure.read_text(encoding="utf-8"))
    seen = Counter(p["actorId"] for p in data["people"] if p["actorId"] in ledger)
    ranked = sum(1 for p in data["people"] if p["actorId"] in ledger and p["tier"] is not None)
    reasoned = sum(1 for p in data["people"] if p["actorId"] in ledger and p["tier"] is None and str(p.get("unrankedReason") or "").strip())
    twice = sum(1 for n in seen.values() if n > 1)
    missing = len(ledger - set(seen))
    cov = data.get("coverage") or {}
    cov_ok = cov.get("ledger") == len(ledger) and cov.get("ranked", -1) + cov.get("unrankedWithAmount", -1) + cov.get("noInvolvement", -1) == len(ledger)
    listed = ranked + reasoned
    ok = not blank and not twice and not missing and listed == len(ledger) and cov_ok
    text = (f"議員：人物台帳 {len(ledger):,} 人中、曝露ランキングに載る {listed:,} 人（点あり {ranked:,}、点なし＋理由 {reasoned:,}、"
            f"載っていない {missing:,}、2回以上 {twice:,}）{blank_note}" + ("" if cov_ok else "。出力の coverage が台帳と合わない"))
    return ok, text


def _ledger_condition(d: Path, root: Path = ROOT) -> dict:
    """1. 全法律が「額あり」か「額なし＋到達点（理由）」で台帳に載っている。議員は人物台帳の全員が曝露ランキングに1回ずつ載っている。"""
    ledger_path, outcomes_path = d / "evaluation-ledger-v1" / "ledger.csv", d / "all-laws-v1" / "outcomes.csv"
    if not (ledger_path.is_file() and outcomes_path.is_file()):
        raise NotMeasured("台帳か全法律の一覧が無い")
    ledger = read_csv(ledger_path)
    target = {r["id"] for r in read_csv(outcomes_path)}
    if not target:
        raise NotMeasured("全法律の一覧が空")
    listed = {r["id"] for r in ledger}
    with_amount = sum(1 for r in ledger if _amount(r))
    with_reason = sum(1 for r in ledger if not _amount(r) and r["到達点"])
    neither = len(ledger) - with_amount - with_reason
    missing = len(target - listed)
    laws_ok = not missing and not neither and len(listed) == len(ledger)
    members_ok, members = _members_on_ledger(root, d)
    return {
        "state": "達成" if laws_ok and members_ok else "一部達成" if laws_ok or members_ok else "未達",
        "now": f"法律：対象 {len(target):,} 本中、台帳に {len(target & listed):,} 本（額あり {with_amount:,}、額なし＋到達点 {with_reason:,}、どちらでもない {neither:,}、台帳に無い {missing:,}）。{members}",
        "how": f"data/derived/evaluation-ledger-v1/ledger.csv を all-laws-v1/outcomes.csv と、data/derived/person-ids/persons.csv を {EXPOSURE} と照合",
    }


def _logic_condition(root: Path, logic_counts) -> dict:
    """2. ロジック検査の違反0。"""
    if logic_counts is None and root != ROOT:
        raise NotMeasured("測っていない（リポジトリの外）")
    counts = (logic_counts or _logic_counts_from_repo)()
    if not counts:
        raise NotMeasured("規則が1つも走っていない")
    total = sum(counts.values())
    return {"state": "達成" if total == 0 else "未達",
            "now": "違反 " + "・".join(f"{k} {v}" for k, v in sorted(counts.items())) + f"（計 {total:,} 本）",
            "how": "scripts/check_evaluation_logic.py の check()（tests/test_evaluation_logic.py と同じ規則）"}


def _sampling_condition(d: Path) -> dict:
    """3. 抜き取り検証で不合格のままの法律が0。標本1（初回）と標本2（sample-v2、新しい標本）のそれぞれで、抜き取った全件に判定があること。"""
    base = d / "evaluation-ledger-v1"
    if not all((base / n).is_file() for n in ("sample.csv", "sample-verdicts.csv", "ledger.csv")):
        raise NotMeasured("抜き取りか判定の記録が無い")
    ledger_state = {r["id"]: (r["検証状態"], r.get("検証メモ", "")) for r in read_csv(base / "ledger.csv")}
    parts, ok = [], True
    for name, sample_csv, verdict_csv in (("標本1（初回、種 20261030）", base / "sample.csv", base / "sample-verdicts.csv"),
                                          ("標本2（新しい標本、種 20261119）", base / "sample-v2" / "sample.csv", base / "sample-v2" / "verdicts.csv")):
        if not sample_csv.is_file() or not verdict_csv.is_file():
            if "sample-v2" in str(sample_csv) and not sample_csv.parent.exists():
                continue  # 標本2の記録が丸ごと無い木（検査用の架空の木など）は標本1だけで数える
            raise NotMeasured(f"{name} の抜き取りか判定の記録が無い")
        sample = {r["id"] for r in read_csv(sample_csv)}
        if not sample:
            raise NotMeasured(f"{name} の抜き取りが0本")
        # 同じ法律の判定が2行あれば後の行（やり直し）を採る。空欄や知らない語は判定として数えない
        verdict_of = {r["id"]: r["判定"] for r in read_csv(verdict_csv) if r["id"] in sample and r["判定"] in ("合格", "不合格")}
        tally = Counter(verdict_of.values())
        state = Counter(ledger_state.get(i, ("", ""))[0] for i in sample)
        still_failed, demoted = state["抜き取り検証で不合格"], state["参考に下げた"]
        unjudged = len(sample) - len(verdict_of)
        # 不合格の判定のうち、台帳で「参考に下げた」でも「不合格のまま」でもないもの＝読み直し・訂正で合格になった法律
        fixed = sum(1 for i, v in verdict_of.items() if v == "不合格" and ledger_state.get(i, ("", ""))[0] not in ("参考に下げた", "抜き取り検証で不合格"))
        ok = ok and unjudged == 0 and still_failed == 0
        parts.append(f"{name}：{len(sample):,} 本中 合格 {tally['合格']:,}・不合格 {tally['不合格']:,}・判定なし {unjudged:,}。"
                     f"不合格のうち 参考に下げた {demoted:,}・訂正（読み直し）で合格 {fixed:,}・不合格のまま {still_failed:,}")
    return {
        "state": "達成" if ok else "未達",
        "now": "／".join(parts),
        "how": "標本ごとの sample.csv と判定（sample-verdicts.csv、sample-v2/verdicts.csv）と台帳の検証状態。標本2の不合格のままは、サイトの値の訂正（sample-v2/correction-candidates.csv）が入ると台帳が判定し直して減る",
    }


def _release_condition(root: Path) -> dict:
    """4. 公開前検査。release_check.py が残した最新の記録を読む（ここでは走らせない）。"""
    records = sorted((root / ".local" / "release-check").glob("*.json"))
    if not records:
        raise NotMeasured("記録が無い")
    steps = json.loads(read_text(records[-1]))
    if not isinstance(steps, list) or not steps:
        raise NotMeasured(f"{records[-1].stem} の記録が空")
    bad = [s["step"] for s in steps if not s["ok"]]
    return {"state": "未達" if bad else "達成",
            "now": f"{records[-1].stem} の記録：{len(steps) - len(bad)}/{len(steps)} 合格" + (f"（失敗：{'、'.join(bad)}）" if bad else ""),
            "how": "python3 scripts/release_check.py の記録（.local/release-check/）。記録より後の変更は見ていない"}


def completion_status(root: Path, logic_counts=None) -> list[dict]:
    """4つの条件の今の状態。state は 達成・一部達成・未達・未実行。測れないものを達成にしない。

    材料が無い・壊れている条件は「未実行」にして先へ進む（1つ読めなくても、ほかの検査の結果は出す）。
    """
    d = root / "data" / "derived"
    conditions = [
        ("評価台帳の全件（法律と議員）", "python3 scripts/build_evaluation_ledger.py build", lambda: _ledger_condition(d, root)),
        ("ロジック検査の違反0", "python3 scripts/check_evaluation_logic.py", lambda: _logic_condition(root, logic_counts)),
        ("抜き取り検証（不合格0が目標）", "python3 scripts/build_evaluation_ledger.py sample", lambda: _sampling_condition(d)),
        ("公開前検査（出典・議員ページ・個人名義）", "python3 scripts/release_check.py", lambda: _release_condition(root)),
    ]
    rows = []
    for no, (name, command, measure) in enumerate(conditions, 1):
        try:
            row = measure()
        except NotMeasured as e:
            row = {"state": "未実行", "now": str(e), "how": command}
        except (OSError, KeyError, TypeError, ValueError) as e:  # 列が無い・JSON が壊れている・派生データが無い
            row = {"state": "未実行", "now": f"読めない（{type(e).__name__}: {e}）", "how": command}
        rows.append({"no": no, "name": name} | row)
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
