"""全件検査の仕組み（bulk-logic-audit-fanout）。「額を計算済みで共有額により画面外」の法律の
範囲・分類を、短い仕事に分けて Haiku に並行で配り、全部回収して表にする。

機械処理（トークンを使わない）はこのスクリプト、モデルの判断は束ごとの子だけ。手順は docs/全件検査の手順.md。

  flag       段1 失敗パターンの旗を全件に付ける（範囲・共有額・桁外れ・分類の型）
  plan       対象を束に分け、Haiku の A/B 2系統の入力ファイルとプロンプトを出す（--calibrate で正解既知の118本）
  collect    返却を全部読み、欠け・形式違反・重複を検出し、判定表・法律ごとの根拠記録・方法の説明の元データを出す
  disputed   A/B が割れた件を Sonnet 段へ、Sonnet でも決まらない件を Opus 段へ（入力とプロンプトを出す）
  sample     各種類・各判定から抜き取り、実物確認用のリストを出す
  calibrate  正解既知の118本の結果で、段ごとの当たり率（一致・誤検出・見逃し）を出す

使い方：python3 scripts/audit_fanout.py plan --out .local/audit-fanout
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.evaluation_rules import (
    VERDICT_FAIL,
    is_demoted,
    narrow_whole_economy,
)

DERIVED = ROOT / "data" / "derived"
LEDGER = DERIVED / "evaluation-ledger-v1" / "ledger.csv"
SAMPLE_VERDICTS = DERIVED / "evaluation-ledger-v1" / "sample-verdicts.csv"
CALIB_TRUTH = DERIVED / "audit-fanout-v1" / "calibration-truth.csv"  # 較正の正解（額ありの母集団。作り方は audit_corpus.py truth）
MACRO = DERIVED / "macro-v1" / "macro.csv"
BASELINE = DERIVED / "evaluation-ledger-v1" / "audit-fanout-baseline.json"
PUBLISHED = DERIVED / "audit-fanout-v1"
PROMPT_DIR = ROOT / "prompts" / "audit_fanout"
OVERVIEWS = DERIVED / "law-overviews-v1" / "overviews.csv"
PROMPT_FILES = {"haiku": "judge.txt", "sonnet": "arbitrate.txt", "opus": "arbitrate.txt"}

BUNDLE_SIZE = 40  # トークン効率のため大きめ（--size で変更）
MACRO_ORIGIN = "全体指標"
DEMOTED_STATE = "参考に下げた"
RANGE_VALUES = ("全体", "一部", "不明")
CLASS_VALUES = ("評価対象", "制度整備", "不明")
CONFIDENCE = ("高", "中", "低")
QUESTIONS = {"範囲": ("全体", "一部"), "分類": ("評価対象", "制度整備")}  # (合格の値, 不合格の値)
WEIGHT_VALUES = ("はい", "いいえ", "不明", "該当なし")  # 重みが観測できるか（範囲が全体なら該当なし）
ALLOWED = {"範囲": RANGE_VALUES, "分類": CLASS_VALUES, "確信度": CONFIDENCE, "重み観測": WEIGHT_VALUES}
TEXT_FIELDS = ("使った前提", "計算や比較", "判定理由", "確認できなかった点", "探した場所", "重みの手がかり", "model", "prompt_version")
REQUIRED = ("id", "範囲", "分類", "読んだ出典", "確信度", "小問", "根拠引用", "仮定") + TEXT_FIELDS
YES, NO, UNSURE = "はい", "いいえ", "不明"
SUBQ_KEYS = ("範囲1", "範囲2", "分類1", "分類2")  # 範囲1 限定されるか／範囲2 産業全体に及ぶか／分類1 付加価値を直接動かすか／分類2 整理に限られるか
STRENGTHS = ("強", "中", "弱")
MIN_QUOTE = 6
FROZEN_FILE = PUBLISHED / "frozen-sample.csv"
CORPUS_CAP = 3000
PASS, FAIL, UNKNOWN, PENDING = "合格", "不合格", "確認不能", "未決"
NOT_ASKED = "未検査"  # 機械で不合格と決まり、モデルに聞かなかった問い
MACHINE_STAGE = "機械判定"
INSTITUTIONAL_WORDS = ("期限", "延長", "廃止", "整備", "手続", "組織", "設置", "名称", "施行")
HARD_FLAGS = ("範囲:狭い題名に経済全体", "範囲:付加価値1年分超", "分類:制度語")
READ_PLACES = (
    "入力の資料欄（law-overviews-v1/overviews.csv と macro-v1/macro.csv の該当行。--corpus で渡した原文を含む）",
)


# ---------- 入出力 ----------

def today() -> str:
    return datetime.now(tz=UTC).date().isoformat()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def write_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def prompt_files_hash() -> str:
    h = hashlib.sha256()
    for name in sorted(set(PROMPT_FILES.values())):
        h.update(name.encode() + b"\0" + (PROMPT_DIR / name).read_bytes())
    return h.hexdigest()


def git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def prompt_version() -> str:
    """返却に写させる版。git の SHA と prompts/ 以下のファイルのハッシュ。較正の有効性は後ろのハッシュだけで見る。"""
    return f"{git_sha()[:12]}+{prompt_files_hash()[:12]}"


def files_hash_of(version: str) -> str:
    return version.split("+", 1)[-1]


# ---------- 段1 対象と旗 ----------

def select_targets(ledger: list[dict]) -> list[dict]:
    """額を計算済みで共有額（同じ額が2本以上）により画面外になる法律。降格済みは除く。"""
    macro = [r for r in ledger if r["額（円）"] and r["付加価値の由来"].startswith(MACRO_ORIGIN)]
    shared = Counter(r["額（円）"] for r in macro)
    return sorted((r for r in macro if shared[r["額（円）"]] >= 2 and r["検証状態"] != DEMOTED_STATE), key=lambda r: r["id"])


def shared_counts(ledger: list[dict]) -> Counter:
    return Counter(r["額（円）"] for r in ledger if r["額（円）"] and r["付加価値の由来"].startswith(MACRO_ORIGIN))


def japan_ceiling() -> int | None:
    try:
        from scripts.build_public_ranking import japan_value_added_max
        return japan_value_added_max()
    except (ImportError, OSError, KeyError, ValueError):  # 入力の表が無い環境では桁外れの旗を付けない
        return None


def flag_law(row: dict, industry: str, shared: int, ceiling: int | None) -> list[str]:
    flags = []
    if narrow_whole_economy(row["題名"], industry, row["分野"]):
        flags.append("範囲:狭い題名に経済全体")
    if industry == "_T" or row["分野"] == "経済全体":
        flags.append("範囲:産業全体の額")
    if ceiling and row["額（円）"]:
        m = re.search(r"-?\d+", row["額（円）"].split("中央値=")[-1])
        ratio = abs(int(m.group())) / ceiling if m else 0
        if ratio > 1:
            flags.append("範囲:付加価値1年分超")
        elif ratio >= 0.5:
            flags.append("範囲:付加価値1年分の半分以上")
    if shared >= 2:
        flags.append(f"共有額:{shared}本")
    if any(w in row["題名"] for w in INSTITUTIONAL_WORDS):
        flags.append("分類:制度語")
    if row["経済に効くか"].startswith("判定不能"):
        flags.append("分類:判定不能")
    if row["分類"] in ("評価対象外", "保留"):
        flags.append(f"分類:台帳で{row['分類']}")
    return flags


def source_text(lid: str, overview: dict | None, macro: dict | None, corpus: Path | None) -> str:
    """子が引用してよい資料（引用検査はこの文字列に対して行う）。"""
    parts = []
    if overview:
        parts += [f"{k}：{overview[k]}" for k in ("何をする", "狙い", "反対側の心配", "材料") if overview.get(k, "").strip()]
    if macro:
        parts += [f"{k}：{macro[k]}" for k in ("分野", "産業", "窓", "比較国", "計算式の要素") if macro.get(k, "").strip()]
    if corpus is not None and (corpus / f"{lid}.txt").exists():
        parts.append("原文：" + (corpus / f"{lid}.txt").read_text(encoding="utf-8")[:CORPUS_CAP])
    return "\n".join(parts) or "なし"


def build_targets(ledger: list[dict], macro: list[dict], ids: list[str] | None = None, ceiling: int | None = None,
                  overviews: list[dict] | None = None, corpus: Path | None = None) -> list[dict]:
    """束に入れる法律の行（台帳の要点・旗・資料）。ids を渡すとその法律（較正・凍結標本用）。"""
    by_id = {r["id"]: r for r in ledger}
    industry = {r["id"]: r["産業"] for r in macro}
    macro_by = {r["id"]: r for r in macro}
    over_by = {r["id"]: r for r in overviews or []}
    shared = shared_counts(ledger)
    rows = select_targets(ledger) if ids is None else [by_id[i] for i in sorted(ids) if i in by_id]
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "題名": r["題名"], "分野": r["分野"], "額（円）": r["額（円）"],
            "共有本数": shared.get(r["額（円）"], 0), "産業": industry.get(r["id"], ""),
            "到達点": r["到達点"], "確かさ": r["確かさ"],
            "旗": flag_law(r, industry.get(r["id"], ""), shared.get(r["額（円）"], 0), ceiling),
            "資料": source_text(r["id"], over_by.get(r["id"]), macro_by.get(r["id"]), corpus),
        })
        out[-1]["機械判定"] = machine_decision(out[-1])
    return out


def share_groups(ledger: list[dict], macro: list[dict]) -> list[dict]:
    """同じ額を共有する法律の群（共有額の総枠配分は別 PR。ここは本数と業界×期間を出すだけ）。"""
    macro_by = {r["id"]: r for r in macro}
    groups: dict[str, list[str]] = defaultdict(list)
    for r in ledger:
        if r["額（円）"] and r["付加価値の由来"].startswith(MACRO_ORIGIN):
            groups[r["額（円）"]].append(r["id"])
    out = []
    for amount, ids in groups.items():
        if len(ids) >= 2:
            pairs = sorted({(macro_by.get(i, {}).get("産業", ""), macro_by.get(i, {}).get("窓", "")) for i in ids})
            out.append({"額（円）": amount, "本数": len(ids), "業界×期間": [{"産業": a, "窓": b} for a, b in pairs], "ids": sorted(ids)})
    return sorted(out, key=lambda g: (-g["本数"], g["額（円）"]))


def cp_upper(k: int, n: int, alpha: float = 0.05) -> float:
    """不合格が n 本中 k 本のときの、不合格率の片側 (1-alpha) 上限（Clopper-Pearson）。k=0 なら約 3/n。"""
    if n <= 0:
        return 1.0
    if k >= n:
        return 1.0
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        cdf = sum(math.comb(n, i) * mid**i * (1 - mid) ** (n - i) for i in range(k + 1))
        lo, hi = (mid, hi) if cdf > alpha else (lo, mid)
    return round(hi, 4)


def frozen_rows(ledger: list[dict], n: int, seed: int, excluded: set[str]) -> list[dict]:
    """検証用の無作為標本（単純無作為抽出）。調整用の118本は除く。seed を固定して再現でき、各件の抽出確率 π=n/N を記録する。"""
    pool = sorted(r["id"] for r in select_targets(ledger) if r["id"] not in excluded)
    n = min(n, len(pool))
    return [{"id": i, "N": len(pool), "抽出確率": n / len(pool)} for i in sorted(random.Random(seed).sample(pool, n))]


def frozen_ids(ledger: list[dict], n: int, seed: int, excluded: set[str]) -> list[str]:
    return [r["id"] for r in frozen_rows(ledger, n, seed, excluded)]


def ppi_rate(f_all: list[int], f_lab: list[int], y_lab: list[int], z: float = 1.96) -> dict:
    """単純な PPI（prediction-powered inference）による不合格率。f_all=全件の機械+モデルの予測（1=不合格）、
    f_lab・y_lab=標本の予測と実物確認の正解。推定＝全件の予測の平均＋標本での（正解−予測）の平均。区間は正規近似（95%）。"""
    def var(v: list[float]) -> float:
        m = sum(v) / len(v)
        return sum((x - m) ** 2 for x in v) / (len(v) - 1) if len(v) > 1 else 0.0

    big_n, n = len(f_all), len(y_lab)
    resid = [y - f for f, y in zip(f_lab, y_lab, strict=True)]
    est = sum(f_all) / big_n + sum(resid) / n
    se = math.sqrt(var(f_all) / big_n + var(resid) / n)
    return {"推定": round(est, 4), "下限95%": round(max(0.0, est - z * se), 4), "上限95%": round(min(1.0, est + z * se), 4), "全件": big_n, "標本": n}


def machine_decision(t: dict) -> dict | None:
    """機械で決まる件。狭い題名に経済全体の額（規則 L2）は、範囲が「一部」で不合格と決まる。モデルには聞かない。"""
    if "範囲:狭い題名に経済全体" in t["旗"]:
        return {"範囲": "一部", "理由": "狭い題名（特例・特定など）に経済全体の額を当てている（evaluation_rules の L2）"}
    return None


def flag_counts(targets: list[dict]) -> dict[str, int]:
    return {"narrow_whole_economy": sum("範囲:狭い題名に経済全体" in t["旗"] for t in targets),
            "oversize": sum("範囲:付加価値1年分超" in t["旗"] for t in targets)}


# ---------- plan ----------

def render_prompt(stage: str, bundle: str, system: str, input_path: str, return_path: str, version: str) -> str:
    text = (PROMPT_DIR / PROMPT_FILES[stage]).read_text(encoding="utf-8")
    for k, v in {"stage": stage, "bundle": bundle, "system": system, "input_path": input_path, "return_path": return_path, "prompt_version": version}.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def child_row(t: dict, prior: dict | None = None) -> dict:
    row = {"id": t["id"], "題名": t["題名"], "分野": t["分野"], "額（円）": t["額（円）"], "共有本数": t["共有本数"], "ヒント": t["旗"], "資料": t["資料"]}
    if prior:
        row["前の判定"] = prior
    return row


def add_bundle(manifest: dict, out: Path, stage: str, number: int, system: str, rows: list[dict]) -> dict:
    name = f"{stage[0]}{number:03d}-{system}"
    in_rel, ret_rel, pr_rel = f"{stage}/in/{name}.jsonl", f"returns/{stage}/{name}.jsonl", f"{stage}/prompt/{name}.txt"
    write_jsonl(out / in_rel, rows)
    (out / pr_rel).parent.mkdir(parents=True, exist_ok=True)
    (out / pr_rel).write_text(render_prompt(stage, name, system, str(out / in_rel), str(out / ret_rel), manifest["prompt_version"]), encoding="utf-8")
    b = {"stage": stage, "bundle": name, "system": system, "ids": [r["id"] for r in rows], "input": in_rel, "prompt": pr_rel, "return": ret_rel}
    manifest["bundles"].append(b)
    return b


def plan(out: Path, targets: list[dict], mode: str, size: int = BUNDLE_SIZE) -> dict:
    manifest = {"mode": mode, "created": today(), "prompt_version": prompt_version(),
                "target_n": len(targets), "bundle_size": size, "bundles": []}
    write_jsonl(out / "targets.jsonl", targets)
    asked = [t for t in targets if not t.get("機械判定")]
    manifest["machine_decided"] = len(targets) - len(asked)
    for n, i in enumerate(range(0, len(asked), size), 1):
        chunk = asked[i:i + size]
        add_bundle(manifest, out, "haiku", n, "A", [child_row(t) for t in chunk])
        add_bundle(manifest, out, "haiku", n, "B", [child_row(t) for t in reversed(chunk)])  # 同じ束を、並びを変えて独立に
    write_json(out / "manifest.json", manifest)
    return manifest


# ---------- collect ----------

def derive_range(r1: str, r2: str) -> str:
    """範囲の小問（限定されるか・産業全体に及ぶか）から範囲を導く。矛盾・不足は不明。"""
    return {(YES, NO): "一部", (NO, YES): "全体", (YES, UNSURE): "一部", (UNSURE, NO): "一部"}.get((r1, r2), "不明")


def derive_class(c1: str, c2: str) -> str:
    """分類の小問（付加価値を直接動かすか・整理に限られるか）から分類を導く。矛盾・不足は不明。"""
    return {(YES, NO): "評価対象", (NO, YES): "制度整備", (YES, UNSURE): "評価対象", (UNSURE, NO): "評価対象",
            (NO, UNSURE): "制度整備", (UNSURE, YES): "制度整備"}.get((c1, c2), "不明")


def squash(text: str) -> str:
    return "".join(str(text).split())


def validate_evidence(obj: dict, corpus: str | None) -> str | None:
    """小問と範囲・分類の整合、根拠引用が資料に実在するか、仮定の形。"""
    sub = obj["小問"]
    if not isinstance(sub, dict) or any(sub.get(k) not in (YES, NO, UNSURE) for k in SUBQ_KEYS):
        return "小問が不正（範囲1・範囲2・分類1・分類2 を はい／いいえ／不明 で）"
    if derive_range(sub["範囲1"], sub["範囲2"]) != obj["範囲"] or derive_class(sub["分類1"], sub["分類2"]) != obj["分類"]:
        return "小問の答えと範囲・分類が整合しない"
    quotes = obj["根拠引用"]
    decided = obj["範囲"] != "不明" or obj["分類"] != "不明"
    if not isinstance(quotes, list) or (decided and not quotes):
        return "根拠引用が無い（判定したなら資料の文言を1つ以上）"
    for q in quotes:
        if not isinstance(q, dict) or not isinstance(q.get("出典"), str) or not isinstance(q.get("引用"), str):
            return "根拠引用の形が不正（出典と引用の辞書）"
        text = squash(q["引用"])
        if len(text) < MIN_QUOTE:
            return f"引用が短すぎる（{MIN_QUOTE}文字以上）"
        if corpus is not None and text not in squash(corpus):
            return f"引用が資料に実在しない: {q['引用'][:30]}"
    ass = obj["仮定"]
    if not isinstance(ass, list) or (not ass and obj["使った前提"].strip() != "なし"):
        return "仮定の一覧が無い（前提を使ったなら1つ以上）"
    for a in ass:
        if not isinstance(a, dict) or not str(a.get("内容", "")).strip() or a.get("強さ") not in STRENGTHS or not str(a.get("影響", "")).strip():
            return "仮定の形が不正（内容・強さ（強中弱）・外したときの影響）"
    return None


def validate_line(obj: object, allowed_ids: set[str], version: str, corpus: dict[str, str] | None = None) -> str | None:
    """形式違反の理由。問題なければ None。corpus を渡すと引用検査（実在の突合）をする。"""
    if not isinstance(obj, dict):
        return "JSON の対象が辞書でない"
    for k in REQUIRED:
        if k not in obj:
            return f"必須欄が無い: {k}"
    if obj["id"] not in allowed_ids:
        return "束に無い法律 ID"
    for k, vals in ALLOWED.items():
        if obj[k] not in vals:
            return f"{k} の値が選択肢外: {obj[k]!r}"
    for k in TEXT_FIELDS:
        if not isinstance(obj[k], str) or not obj[k].strip():
            return f"空欄（無いときは「なし」と書く）: {k}"
    src = obj["読んだ出典"]
    if not isinstance(src, list) or not src or any(not isinstance(s, str) or not s.strip() for s in src):
        return "読んだ出典が空（場所を1つ以上）"
    if obj["prompt_version"] != version:
        return "prompt_version が入力と違う"
    if (obj["範囲"] == "不明" or obj["分類"] == "不明") and obj["確認できなかった点"].strip() == "なし":
        return "不明なのに確認できなかった点が「なし」"
    return validate_evidence(obj, None if corpus is None else corpus.get(obj["id"], ""))


def read_returns(out: Path, manifest: dict, corpus: dict[str, str] | None = None) -> dict:
    """{(stage, system): {id: 判定}}、未回収の束、欠けた件、形式違反、重複。"""
    judged: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    owner: dict[tuple[str, str, str], str] = {}
    unreturned, missing, violations, duplicates = [], [], [], []
    for b in manifest["bundles"]:
        path = out / b["return"]
        if not path.exists():
            unreturned.append(b["bundle"])
            continue
        seen: set[str] = set()
        key = (b["stage"], b["system"])
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                violations.append({"bundle": b["bundle"], "line": n, "reason": "JSON として読めない"})
                continue
            why = validate_line(obj, set(b["ids"]), manifest["prompt_version"], corpus)
            if why:
                violations.append({"bundle": b["bundle"], "line": n, "id": obj.get("id") if isinstance(obj, dict) else None, "reason": why})
                continue
            lid = obj["id"]
            if lid in seen or (key[0], key[1], lid) in owner:
                duplicates.append({"bundle": b["bundle"], "id": lid, "other": owner.get((key[0], key[1], lid), b["bundle"])})
                continue
            seen.add(lid)
            owner[(key[0], key[1], lid)] = b["bundle"]
            judged[key][lid] = obj
        for lid in b["ids"]:
            if lid not in seen:
                missing.append({"bundle": b["bundle"], "id": lid})
    return {"judged": judged, "unreturned": unreturned, "missing": missing, "violations": violations, "duplicates": duplicates}


def question_state(lid: str, q: str, judged: dict) -> dict:
    """1つの問いの最終値。A==B ならそれ、割れたら Sonnet（A か B と一致すれば採用）、なお割れたら Opus。"""
    a, b = judged.get(("haiku", "A"), {}).get(lid), judged.get(("haiku", "B"), {}).get(lid)
    if not a or not b:
        return {"value": None, "state": PENDING, "stage": "haiku待ち", "agree": None}
    av, bv = a[q], b[q]
    if av == bv:
        return {"value": av, "state": "decided", "stage": "haiku一致", "agree": True}
    s = judged.get(("sonnet", "S"), {}).get(lid)
    if s is None:
        return {"value": None, "state": PENDING, "stage": "sonnet待ち", "agree": False}
    if s[q] in (av, bv) and s[q] != "不明":
        return {"value": s[q], "state": "decided", "stage": "sonnet裁定", "agree": False, "model": s["model"]}
    o = judged.get(("opus", "S"), {}).get(lid)
    if o is None:
        return {"value": None, "state": PENDING, "stage": "opus待ち", "agree": False}
    return {"value": o[q], "state": "decided", "stage": "opus裁定", "agree": False, "model": o["model"]}


def question_verdict(q: str, st: dict) -> str:
    if st["state"] != "decided":
        return PENDING
    if st["value"] == QUESTIONS[q][0]:
        return PASS
    if st["value"] == QUESTIONS[q][1]:
        return FAIL
    return UNKNOWN


def law_verdict(per_q: dict[str, str]) -> str:
    if FAIL in per_q.values():
        return FAIL
    if PENDING in per_q.values():
        return PENDING
    if UNKNOWN in per_q.values():
        return UNKNOWN
    return PASS


def _short(rec: dict) -> dict:
    keys = ("範囲", "分類", "小問", "使った前提", "仮定", "読んだ出典", "根拠引用", "計算や比較", "判定理由", "確認できなかった点", "探した場所", "確信度", "重み観測", "重みの手がかり", "model")
    return {k: rec[k] for k in keys}


def law_records(manifest: dict, targets: list[dict], judged: dict) -> list[dict]:
    """法律ごとの根拠記録（画面の refBasis に写せる形）。"""
    version = manifest["prompt_version"]
    prompt = {"files": sorted(set(PROMPT_FILES.values())), "version": version, "filesHash": files_hash_of(version)}
    out = []
    for t in targets:
        lid = t["id"]
        md = t.get("機械判定")
        if md:
            out.append(machine_record(t, md, prompt))
            continue
        states = {q: question_state(lid, q, judged) for q in QUESTIONS}
        per_q = {q: question_verdict(q, states[q]) for q in QUESTIONS}
        verdict = law_verdict(per_q)
        stages = [states[q]["stage"] for q in QUESTIONS]
        judgments = {name: _short(judged[key][lid]) for name, key in (("A", ("haiku", "A")), ("B", ("haiku", "B")), ("Sonnet", ("sonnet", "S")), ("Opus", ("opus", "S"))) if lid in judged.get(key, {})}
        decisive = next((judgments[n] for n in ("Opus", "Sonnet", "A") if n in judgments), None) if verdict != PENDING else None
        demoted = verdict == FAIL and is_demoted(VERDICT_FAIL, t["到達点"], t["確かさ"])
        adjud = sorted({st["model"] for st in states.values() if st.get("model")})
        rec = {
            "id": lid, "題名": t["題名"], "判定": verdict, "問いごとの判定": per_q,
            "値": {q: states[q]["value"] for q in QUESTIONS}, "参考に下げる": demoted,
            "段": {q: states[q]["stage"] for q in QUESTIONS}, "裁定者のモデル": adjud,
            "haikuAB": {q: states[q]["agree"] for q in QUESTIONS},
            "根拠": decisive, "判定の記録": judgments,
            "仮定": [{"仮定ID": assumption_id(a["内容"]), "強さ": a["強さ"], "影響": a["影響"]} for a in (decisive or {}).get("仮定", [])],
            "入力にした資料": list(READ_PLACES), "旗": t["旗"], "プロンプト": prompt,
            "使ったモデル": sorted({j["model"] for j in judgments.values()}),
        }
        rec["refBasis"] = (f"範囲={rec['値']['範囲']}・分類={rec['値']['分類']}（{'・'.join(sorted(set(stages)))}）。"
                           + (decisive["判定理由"] if decisive else "判定待ち"))[:300]
        out.append(rec)
    return out


def assumption_id(text: str) -> str:
    return "A-" + hashlib.sha1(squash(text).encode()).hexdigest()[:8]


def assumption_ledger(records: list[dict]) -> list[dict]:
    """仮定の共通台帳：仮定ID→内容、強さ、使った法律。仮定を変えたとき影響する法律を洗い出せる。"""
    led: dict[str, dict] = {}
    for r in records:
        for j in r["判定の記録"].values():
            for a in j.get("仮定", []):
                e = led.setdefault(assumption_id(a["内容"]), {"仮定ID": assumption_id(a["内容"]), "内容": a["内容"], "強さ": Counter(), "影響の例": a["影響"], "法律": set()})
                e["強さ"][a["強さ"]] += 1
                e["法律"].add(r["id"])
    return [{**e, "強さ": dict(e["強さ"]), "法律": sorted(e["法律"]), "本数": len(e["法律"])} for e in sorted(led.values(), key=lambda e: (-len(e["法律"]), e["仮定ID"]))]


def machine_record(t: dict, md: dict, prompt: dict) -> dict:
    """機械で不合格と決まった件の記録。モデルを使っていない（使ったモデルは空）。"""
    per_q = {q: (FAIL if q in md else NOT_ASKED) for q in QUESTIONS}
    basis = {"範囲": md["範囲"], "判定理由": md["理由"], "使った前提": "題名の語の規則（評価の規則 L2）", "読んだ出典": ["scripts/evaluation_rules.py"],
             "計算や比較": "題名の語と、額の産業（_T）・分野（経済全体）の突合", "確認できなかった点": "なし", "探した場所": "なし", "確信度": "高", "model": "script"}
    return {"id": t["id"], "題名": t["題名"], "判定": FAIL, "問いごとの判定": per_q, "値": {"範囲": md["範囲"], "分類": None},
            "参考に下げる": is_demoted(VERDICT_FAIL, t["到達点"], t["確かさ"]), "段": {q: MACHINE_STAGE for q in QUESTIONS},
            "裁定者のモデル": [], "haikuAB": {q: None for q in QUESTIONS}, "根拠": basis, "判定の記録": {}, "仮定": [], "入力にした資料": ["題名・産業・分野（台帳と macro.csv）"],
            "旗": t["旗"], "プロンプト": prompt, "使ったモデル": [],
            "refBasis": ("機械判定：" + md["理由"])[:300]}


def build_table(records: list[dict]) -> list[dict]:
    rows = []
    for kind in ("範囲", "分類", "総合"):
        c = Counter()
        for r in records:
            v = r["判定"] if kind == "総合" else r["問いごとの判定"][kind]
            if v == NOT_ASKED:
                continue
            c[v] += 1
            c["machine"] += r["段"]["範囲"] == MACHINE_STAGE
            if v == FAIL and r["参考に下げる"]:
                c["demoted"] += 1
        rows.append({"種類": kind, "検査数": sum(c[k] for k in (PASS, FAIL, UNKNOWN, PENDING)), "機械判定": c["machine"], "合格": c[PASS], "不合格": c[FAIL], "参考に下げた": c["demoted"],
                     "確認不能": c[UNKNOWN], "未決": c[PENDING]})
    return rows


def stage_stats(records: list[dict]) -> dict:
    """段ごとの一致率など（方法の説明の元データ）。"""
    stats = {}
    for q in QUESTIONS:
        both = [r for r in records if r["haikuAB"][q] is not None]
        agree = sum(1 for r in both if r["haikuAB"][q])
        stats[q] = {"haikuABそろった件": len(both), "一致": agree, "一致率": round(agree / len(both), 4) if both else None,
                    "sonnet裁定": sum(r["段"][q] == "sonnet裁定" for r in records), "opus裁定": sum(r["段"][q] == "opus裁定" for r in records)}
    return stats


# ---------- 較正 ----------

def verdict_from(values: dict[str, str]) -> str:
    return law_verdict({q: (PASS if values[q] == QUESTIONS[q][0] else FAIL if values[q] == QUESTIONS[q][1] else UNKNOWN) for q in QUESTIONS})


def rates(pairs: list[tuple[str, str]], n_total: int) -> dict:
    """pairs=(予測, 正解)。予測が合格/不合格のものだけ。一致率は全件（判定できなかった件は不一致）が分母。"""
    truth_pass = [p for p in pairs if p[1] == PASS]
    truth_fail = [p for p in pairs if p[1] == FAIL]
    n_tp = sum(1 for p in truth_pass)
    n_tf = sum(1 for p in truth_fail)
    return {
        "正解の合格数": n_tp, "正解の不合格数": n_tf,
        "判定できた件": len(pairs), "全件": n_total,
        "一致率": round(sum(1 for p in pairs if p[0] == p[1]) / n_total, 4) if n_total else None,
        "誤検出率": round(sum(1 for p in truth_pass if p[0] == FAIL) / n_tp, 4) if n_tp else None,  # 正解は合格なのに不合格と判定
        "見逃し率": round(sum(1 for p in truth_fail if p[0] == PASS) / n_tf, 4) if n_tf else None,  # 正解は不合格なのに合格と判定
    }


def calibration(records: list[dict], judged: dict, truth: dict[str, str], targets: list[dict], version: str) -> dict:
    ids = [t["id"] for t in targets if t["id"] in truth]
    by_rec = {r["id"]: r for r in records}
    by_t = {t["id"]: t for t in targets}

    def sys_pairs(key: tuple[str, str]) -> list[tuple[str, str]]:
        res = []
        for i in ids:
            j = judged.get(key, {}).get(i)
            if j:
                v = verdict_from(j)
                if v in (PASS, FAIL):
                    res.append((v, truth[i]))
        return res

    flag_pairs = [(FAIL if any(f in by_t[i]["旗"] for f in HARD_FLAGS) else PASS, truth[i]) for i in ids]
    agreed = [i for i in ids if all(by_rec[i]["haikuAB"][q] for q in QUESTIONS)]
    agreed_pairs = [(by_rec[i]["判定"], truth[i]) for i in agreed if by_rec[i]["判定"] in (PASS, FAIL)]
    final_pairs = [(by_rec[i]["判定"], truth[i]) for i in ids if by_rec[i]["判定"] in (PASS, FAIL)]
    stages = {
        "段1 旗（スクリプト）": rates(flag_pairs, len(ids)),
        "段2 Haiku A": rates(sys_pairs(("haiku", "A")), len(ids)),
        "段2 Haiku B": rates(sys_pairs(("haiku", "B")), len(ids)),
        "段2 A/B 一致した件のみ": rates(agreed_pairs, len(agreed)),
        "段3 最終（Sonnet・Opus 裁定後）": rates(final_pairs, len(ids)),
    }
    return {"generated": today(), "n": len(ids), "promptVersion": version, "promptFilesHash": files_hash_of(version),
            "stages": stages, "final": stages["段3 最終（Sonnet・Opus 裁定後）"],
            "undecided": sum(1 for i in ids if by_rec[i]["判定"] in (PENDING, UNKNOWN))}


def calibration_warnings(cal: dict | None, thresholds: dict, current_hash: str) -> list[str]:
    """基準以下・未実施・プロンプト差し替え後の較正は、全件に回さず報告する旨の警告にする。"""
    stop = "全件に回さず、調整役へ報告すること"
    if not cal:
        return [f"較正が未実施（calibrate の結果が無い）。{stop}"]
    w = []
    f = cal["final"]
    if cal["n"] < thresholds["min_samples"]:
        w.append(f"較正の件数 {cal['n']} が基準 {thresholds['min_samples']} 未満")
    if f["一致率"] is None or f["一致率"] < thresholds["min_agreement"]:
        w.append(f"較正の一致率 {f['一致率']} が基準 {thresholds['min_agreement']} 未満")
    if f["見逃し率"] is not None and f["見逃し率"] > thresholds["max_miss_rate"]:
        w.append(f"較正の見逃し率 {f['見逃し率']} が基準 {thresholds['max_miss_rate']} 超")
    if f.get("正解の合格数", 0) < thresholds.get("min_truth_pass", 0):
        w.append(f"較正の正解の合格が {f.get('正解の合格数', 0)} 本で、誤検出率は測れない（基準 {thresholds['min_truth_pass']} 本以上）。誤検出の害は参考への降格にとどまる（参考値と根拠は出し続ける）が、合格と判定した法律は全件を別系統で再確認すること")
    elif f["誤検出率"] is not None and f["誤検出率"] > thresholds["max_false_alarm_rate"]:
        w.append(f"較正の誤検出率 {f['誤検出率']} が基準 {thresholds['max_false_alarm_rate']} 超")
    if cal.get("promptFilesHash") != current_hash:
        w.append("較正のあとに判定プロンプトが替わった。較正をやり直す")
    return [f"{x}。{stop}" for x in w]


def load_baseline(path: Path = BASELINE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- sample ----------

def sample_rows(records: list[dict], per_group: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = []
    for kind in ("範囲", "分類", "総合"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            groups[r["判定"] if kind == "総合" else r["問いごとの判定"][kind]].append(r)
        for verdict in (PASS, FAIL, UNKNOWN):
            pool = sorted(groups.get(verdict, []), key=lambda r: r["id"])
            for r in rng.sample(pool, min(per_group, len(pool))):
                j = r["根拠"] or {}
                out.append({"種類": kind, "判定": verdict, "id": r["id"], "題名": r["題名"], "範囲": r["値"]["範囲"], "分類": r["値"]["分類"],
                            "段": "・".join(sorted(set(r["段"].values()))), "判定理由": j.get("判定理由", ""),
                            "読んだ出典": " | ".join(j.get("読んだ出典", [])), "実物確認（一致/不一致）": "", "実物での所見": ""})
    return out


# ---------- disputed ----------

def disputed_ids(records: list[dict], stage: str) -> list[str]:
    want = "sonnet待ち" if stage == "sonnet" else "opus待ち"
    return [r["id"] for r in records if want in r["段"].values()]


def plan_disputed(out: Path, manifest: dict, targets: list[dict], records: list[dict], judged: dict, stage: str, force: bool = False) -> list[dict]:
    if any(b["stage"] == stage for b in manifest["bundles"]) and not force:
        raise SystemExit(f"{stage} 段の束はもうある。作り直すなら --force")
    manifest["bundles"] = [b for b in manifest["bundles"] if b["stage"] != stage]
    ids = set(disputed_ids(records, stage))
    by_t = {t["id"]: t for t in targets}
    rows = []
    for lid in sorted(ids):
        prior = {n: _short(judged[k][lid]) for n, k in (("A", ("haiku", "A")), ("B", ("haiku", "B")), ("Sonnet", ("sonnet", "S"))) if lid in judged.get(k, {})}
        rows.append(child_row(by_t[lid], prior))
    new = [add_bundle(manifest, out, stage, n, "S", rows[i:i + BUNDLE_SIZE]) for n, i in enumerate(range(0, len(rows), BUNDLE_SIZE), 1)]
    write_json(out / "manifest.json", manifest)
    return new


# ---------- CLI ----------

def load_state(out: Path) -> tuple[dict, list[dict], dict, list[dict]]:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    targets = [json.loads(x) for x in (out / "targets.jsonl").read_text(encoding="utf-8").splitlines() if x]
    ret = read_returns(out, manifest, {t["id"]: t["資料"] for t in targets})
    return manifest, targets, ret, law_records(manifest, targets, ret["judged"])


def cmd_plan(a: argparse.Namespace) -> int:
    ledger, macro, over = read_csv(LEDGER), read_csv(MACRO), read_csv(OVERVIEWS)
    ceiling = japan_ceiling()
    corpus = Path(a.corpus) if a.corpus else None
    if a.calibrate:
        ids = [r["id"] for r in read_csv(CALIB_TRUTH)]
        targets, mode = build_targets(ledger, macro, ids, ceiling, over, corpus), "calibrate"
    elif a.frozen:
        ids = [r["id"] for r in read_csv(FROZEN_FILE)]
        targets, mode = build_targets(ledger, macro, ids, ceiling, over, corpus), "frozen"
    else:
        targets, mode = build_targets(ledger, macro, None, ceiling, over, corpus), "full"
    m = plan(Path(a.out), targets, mode, a.size)
    groups = share_groups(ledger, macro)
    write_json(Path(a.out) / "share-groups.json", groups)
    print(json.dumps({"mode": mode, "対象": len(targets), "機械で決着（モデルに回さない）": m["machine_decided"], "モデルに回す": len(targets) - m["machine_decided"], "束": len(m["bundles"]) // 2, "子の本数（A/B）": len(m["bundles"]),
                      "旗": flag_counts(targets), "共有額グループ": {"数": len(groups), "最大本数": groups[0]["本数"] if groups else 0},
                      "prompt_version": m["prompt_version"]}, ensure_ascii=False))
    return 0


def cmd_flag(a: argparse.Namespace) -> int:
    targets = build_targets(read_csv(LEDGER), read_csv(MACRO), None, japan_ceiling())
    c = Counter(f.split(":")[0] + ":" + f.split(":")[1].rstrip("0123456789本") for t in targets for f in t["旗"])
    print(json.dumps({"対象": len(targets), "旗の件数": dict(c), "違反": flag_counts(targets)}, ensure_ascii=False))
    if a.write_baseline:
        base = load_baseline() if BASELINE.exists() else {}
        base["flag_violations"] = flag_counts(targets)
        write_json(BASELINE, base)
    return 0


def cmd_collect(a: argparse.Namespace) -> int:
    out = Path(a.out)
    manifest, targets, ret, records = load_state(out)
    base = load_baseline()
    table, stats = build_table(records), stage_stats(records)
    cal_path = Path(a.calibration) if a.calibration else (PUBLISHED / "calibration.json" if (PUBLISHED / "calibration.json").exists() else out / "calibration.json")
    cal = json.loads(cal_path.read_text(encoding="utf-8")) if cal_path.exists() else None
    warnings = [] if manifest["mode"] == "calibrate" else calibration_warnings(cal, base["calibration"], files_hash_of(manifest["prompt_version"]))
    result = {"mode": manifest["mode"], "対象": len(targets), "未回収の束": ret["unreturned"], "欠け": ret["missing"],
              "形式違反": ret["violations"], "重複": ret["duplicates"], "表": table, "警告": warnings}
    fails = sum(1 for r in records if r["判定"] == FAIL)
    if manifest["mode"] == "frozen":
        result["凍結標本"] = {"n": len(records), "不合格": fails, "不合格率": round(fails / len(records), 4) if records else None,
                         "上限95%": cp_upper(fails, len(records)), "注": "凍結標本の結果は規則・プロンプトの調整に使わない"}
        print(f"凍結標本 n={len(records)} 不合格 {fails} 本、不合格率の95%上限 {result['凍結標本']['上限95%']}")
    ledger_ass = assumption_ledger(records)
    write_jsonl(out / "assumptions.jsonl", ledger_ass)
    write_json(out / "collect.json", result)
    write_jsonl(out / "basis.jsonl", records)
    method = {"generated": today(), "mode": manifest["mode"], "promptVersion": manifest["prompt_version"],
              "promptFiles": sorted(set(PROMPT_FILES.values())), "promptFilesHash": files_hash_of(manifest["prompt_version"]),
              "flow": ["段1 旗（スクリプト）", "段2 Haiku A/B（互いに見ない）", "段3 割れたら Sonnet、なお割れたら Opus"],
              "calibration": cal, "thresholds": base["calibration"], "stageAgreement": stats, "table": table,
              "models": sorted({m for r in records for m in r["使ったモデル"]}), "assumptionCount": len(ledger_ass),
              "frozen": result.get("凍結標本")}
    write_json(out / "methodology.json", method)
    if a.publish:
        write_json(PUBLISHED / "methodology.json", method)
    print("種類\t検査数\t機械判定\t合格\t不合格\t参考に下げた\t確認不能\t未決")
    for r in table:
        print("\t".join(str(r[k]) for k in ("種類", "検査数", "機械判定", "合格", "不合格", "参考に下げた", "確認不能", "未決")))
    print(f"未回収の束 {len(ret['unreturned'])} 欠け {len(ret['missing'])} 形式違反 {len(ret['violations'])} 重複 {len(ret['duplicates'])}")
    if ret["unreturned"]:
        print("未回収：" + " ".join(ret["unreturned"]))
    for w in warnings:
        print("警告：" + w, file=sys.stderr)
    return 2 if (a.strict and (warnings or ret["unreturned"] or ret["violations"] or ret["missing"] or ret["duplicates"])) else 0


def cmd_disputed(a: argparse.Namespace) -> int:
    out = Path(a.out)
    manifest, targets, ret, records = load_state(out)
    new = plan_disputed(out, manifest, targets, records, ret["judged"], a.stage, a.force)
    print(json.dumps({"stage": a.stage, "件": sum(len(b["ids"]) for b in new), "束": len(new)}, ensure_ascii=False))
    return 0


def cmd_frozen(a: argparse.Namespace) -> int:
    if FROZEN_FILE.exists() and not a.refreeze:
        raise SystemExit(f"凍結済み: {FROZEN_FILE}（作り直しは --refreeze。凍結標本を調整に使ったなら、その標本はもう検証に使えない）")
    ledger = read_csv(LEDGER)
    rows = frozen_rows(ledger, a.n, a.seed, {r["id"] for r in read_csv(SAMPLE_VERDICTS)})
    by_id = {r["id"]: r for r in ledger}
    FROZEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    with FROZEN_FILE.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "題名", "seed", "n", "N", "抽出確率", "凍結日"])
        for r in rows:
            w.writerow([r["id"], by_id[r["id"]]["題名"], a.seed, len(rows), r["N"], r["抽出確率"], today()])
    print(f"凍結 {len(rows)} 本（N={rows[0]['N']}、抽出確率 {rows[0]['抽出確率']:.4f}）（seed={a.seed}、118本を除く）→ {FROZEN_FILE}")
    return 0


def cmd_ppi(a: argparse.Namespace) -> int:
    """凍結標本の実物確認（truth.csv：id,判定,prompt_version）と全件の判定から、不合格率の PPI 推定を出す。"""
    out = Path(a.out)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    recs = {json.loads(x)["id"]: json.loads(x) for x in (out / "basis.jsonl").read_text(encoding="utf-8").splitlines() if x}
    truth = read_csv(Path(a.truth))
    if any(r["prompt_version"] != manifest["prompt_version"] for r in truth):
        raise SystemExit("正解の prompt_version が全件の実行と違う。LLM とプロンプト版を固定してから正解を取ること")
    if any(r["id"] not in recs or recs[r["id"]]["判定"] not in (PASS, FAIL) for r in truth):
        raise SystemExit("標本に全件の判定が無い・未決・確認不能がある。先に全部回収する")
    if len({r["抽出確率"] for r in read_csv(FROZEN_FILE)}) != 1:
        raise SystemExit("抽出確率が一様でない（この PPI は単純無作為抽出が前提）")
    f_all = [1 if r["判定"] == FAIL else 0 for r in recs.values() if r["判定"] in (PASS, FAIL)]
    est = ppi_rate(f_all, [1 if recs[r["id"]]["判定"] == FAIL else 0 for r in truth], [1 if r["判定"] == FAIL else 0 for r in truth])
    write_json(out / "ppi.json", est)
    print(json.dumps(est, ensure_ascii=False))
    return 0


def cmd_sample(a: argparse.Namespace) -> int:
    if a.frozen:
        return cmd_frozen(a)
    out = Path(a.out)
    _, _, _, records = load_state(out)
    rows = sample_rows(records, a.n, a.seed)
    path = out / "sample.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["id"])
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} 件 → {path}")
    return 0


def cmd_calibrate(a: argparse.Namespace) -> int:
    out = Path(a.out)
    manifest, targets, ret, records = load_state(out)
    if manifest["mode"] != "calibrate":
        raise SystemExit("calibrate は plan --calibrate で作った作業場だけに使う")
    truth = {r["id"]: r["判定"] for r in read_csv(CALIB_TRUTH)}
    cal = calibration(records, ret["judged"], truth, targets, manifest["prompt_version"])
    write_json(out / "calibration.json", cal)
    if a.publish:
        write_json(PUBLISHED / "calibration.json", cal)
    for name, s in cal["stages"].items():
        print(f"{name}\t一致率 {s['一致率']}\t誤検出率 {s['誤検出率']}\t見逃し率 {s['見逃し率']}\t判定できた {s['判定できた件']}/{s['全件']}")
    for w in calibration_warnings(cal, load_baseline()["calibration"], files_hash_of(manifest["prompt_version"])):
        print("警告：" + w, file=sys.stderr)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("plan", cmd_plan), ("collect", cmd_collect), ("disputed", cmd_disputed), ("sample", cmd_sample), ("calibrate", cmd_calibrate)):
        s = sub.add_parser(name)
        s.add_argument("--out", default=".local/audit-fanout", help="作業場（束・返却・結果）")
        s.set_defaults(fn=fn)
        if name == "plan":
            s.add_argument("--calibrate", action="store_true", help="正解既知の calibration-truth.csv（額ありの母集団）を対象にする")
            s.add_argument("--size", type=int, default=BUNDLE_SIZE)
            s.add_argument("--frozen", action="store_true", help="凍結した無作為標本（sample --frozen で作る）を対象にする")
            s.add_argument("--corpus", default="", help="<法律ID>.txt の原文を置いた場所（資料欄に入り、引用検査の対象になる）")
        if name == "collect":
            s.add_argument("--calibration", default="")
            s.add_argument("--publish", action="store_true", help="方法の説明の元データを data/derived/audit-fanout-v1 にも書く")
            s.add_argument("--strict", action="store_true", help="警告・未回収・形式違反があれば終了コード2")
        if name == "disputed":
            s.add_argument("--stage", choices=("sonnet", "opus"), required=True)
            s.add_argument("--force", action="store_true")
        if name == "sample":
            s.add_argument("--n", type=int, default=3, help="種類×判定ごとの抜き取り件数（--frozen では標本の本数）")
            s.add_argument("--frozen", action="store_true", help="検証用の無作為標本を凍結する（118本は除く）")
            s.add_argument("--refreeze", action="store_true")
            s.add_argument("--seed", type=int, default=0)
        if name == "calibrate":
            s.add_argument("--publish", action="store_true")
    pp = sub.add_parser("ppi")
    pp.add_argument("--out", required=True, help="全件の作業場（collect 済み）")
    pp.add_argument("--truth", required=True, help="凍結標本の実物確認（id,判定,prompt_version）")
    pp.set_defaults(fn=cmd_ppi)
    f = sub.add_parser("flag")
    f.add_argument("--write-baseline", action="store_true")
    f.set_defaults(fn=cmd_flag)
    a = p.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
