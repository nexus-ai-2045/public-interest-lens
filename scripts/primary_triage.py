"""振り分けの当て直し（primary-triage-v1、2026-11-19）。測る側の法律の類型・経済に効くか・主な産業分野を、題名ではなく一次資料から決め直す。

  python3 scripts/primary_triage.py targets                 測る側の全件 → primary-triage-v1/all/targets.csv
  python3 scripts/primary_triage.py pilot [--n 10]          試走の標本（到達点で層を分け、種固定）→ pilot/targets.csv
  python3 scripts/primary_triage.py fetch --set pilot       一次資料を取って .local/primary-triage-v1/sources/{id}.txt に置く
  python3 scripts/primary_triage.py prompts --set pilot     読み手ごとの指示文を .local/primary-triage-v1/prompts/{line}/{id}.md に書く
  python3 scripts/primary_triage.py queue --set pilot       2系統（{set}/lineA.json・lineB.json）から、採用と裁定待ちに分ける → {set}/queue.json と裁定の指示文
  python3 scripts/primary_triage.py apply --set pilot       2系統と裁定（{set}/rulings.json）から labels.csv の行を作る（同じ id の行は置き換える）
  python3 scripts/primary_triage.py estimate                試走の実測（pilot/usage.json）から全件の費用と所要時間を見積もる → pilot/estimate.json

根本原因（/mnt/project-files/analysis/抜き取り不合格の根本原因_2026-11-19.md の 1-2）に対する直し：
  入力：題名だけ → 議案本文＋会議録（系統Aは本文を先に、系統Bは会議録を先に。入力の読み順を分けて独立に近づける）。
  一致の取り方：割れ・判定不能・確信が低い・サイトの値を変える項目は、空や経済全体に倒さず Sonnet が裁定する。
  定義：類型・経済に効くかは読み直しの指示文（reverification-v1/prompt-v1.md）にそろえる（税法の年度改正は実質改正）。
出力 labels.csv は primary-source-corrections-v1/corrections.csv と同じ列。AI の判定の記録（bill-triage-v1 など）は書き換えない。
AI はこのスクリプトからは呼ばない。読み手・裁定者はスレッドが Haiku・Sonnet のサブエージェントで動かし、結果の JSON を {set}/ に置く。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.compare_verification import FIELDS, norm_field
from scripts.resolve_sample_failures import site_is_institutional

DERIVED = ROOT / "data" / "derived"
LEDGER = DERIVED / "evaluation-ledger-v1"
OUT = DERIVED / "primary-triage-v1"
LABELS = OUT / "labels.csv"
LOCAL = ROOT / ".local" / "primary-triage-v1"
SOURCES = LOCAL / "sources"
# 読み手の指示文の版。試走（pilot）は v1、それより後の組は v2（定型改正に給与法の定例改定の例を1行足した）。
# 組ごとの版は prompts が {組}/versions.json に書き、apply はそれを読む（無ければ v1）。
PROMPTS = {"v1": OUT / "prompt-v1.md", "v2": OUT / "prompt-v2.md"}
PROMPT_CURRENT = "v2"
PROMPT_ADJ = OUT / "prompt-adjudicate-v1.md"
PROMPT_ADJ_VERSION = "primary-triage-v1/prompt-adjudicate-v1.md（版 v1）"
PILOT_SEED = 20261120
UNDECIDED = "判定不能"
AMOUNT_GROUPS = ("参考額", "額")
COVID_FIELD = "コロナ対応"  # 産業ではなく費用便益の群の名前（resample_verification と同じ扱い）
KINDS = ("新規", "実質改正", "定型改正", "組織手続")
WHOLE_LABEL = "経済全体（産業を特定できない）"
# 測る側：評価対象外（制度・対応表なし）以外の到達点。評価対象外の見落とし（実は経済に効く）は別の任意の段で拾う
NOT_MEASURED = ("評価対象外",)
ITEMS = ("類型", "経済に効くか", "主な産業分野")
LINES = {"A": "系統A：議案本文（理由と条文）を先に読み、会議録で補う。", "B": "系統B：会議録（提案理由の説明・委員長報告）を先に読み、議案本文で補う。"}
CORR_HEADER = ["id", "項目", "直した値", "直す前の値", "理由", "引用", "出典URL", "判定者", "指示文", "記録"]
# 試走の層：到達点ごとの本数（合計 10）。参考額は経済に効くかが空（一度も聞いていない）の法律を厚くする（連鎖の誤りの主因）
PILOT_STRATA = {
    ("参考額", "空"): 4, ("参考額", "判定済み"): 1, ("効果なし（定例）", ""): 2, ("保留", ""): 1, ("測定できない", ""): 1, ("額", ""): 1,
}


def read_csv(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p: Path, header: list[str], rows: list[dict]) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def set_dir(name: str) -> Path:
    return OUT / name


def reach_group(reach: str) -> str:
    for head in ("参考額", "額", "効果なし（定例）", "保留", "測定できない", "国の収支"):
        if reach.startswith(head):
            return head
    return reach


def measured(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["到達点"] not in NOT_MEASURED]


def site_values(r: dict) -> dict[str, str]:
    """サイトの主張。経済に効くかは到達点で読む（resolve_sample_failures の規則）。
    分野は額のある到達点（参考額・額）だけをサイトの主張とみなす。ほかの到達点の分野は額に使っていないので空（主張なし）にする
    （台帳の値は「サイト_台帳の分野」に写し、labels.csv の「直す前の値」に残す）。
    「保留」の類型と「コロナ対応」の分野は定義の語でない（類型が未決・費用便益の群の名前）ので、主張なし（空）として扱う。"""
    field = r["分野"] if reach_group(r["到達点"]) in AMOUNT_GROUPS and r["分野"] != COVID_FIELD else ""
    kind = r["類型"] if r["類型"] in KINDS else ""
    return {"類型": kind, "経済に効くか": "制度のみ" if site_is_institutional(r) else "経済に効く", "主な産業分野": field}


TARGET_HEADER = ["id", "題名", "到達点", "サイト_類型", "サイト_経済に効くか", "サイト_台帳の経済に効くか", "サイト_分野", "サイト_台帳の分野", "サイト_台帳の類型"]


def target_row(r: dict) -> dict:
    s = site_values(r)
    return {"id": r["id"], "題名": r["題名"], "到達点": r["到達点"], "サイト_類型": s["類型"], "サイト_経済に効くか": s["経済に効くか"],
            "サイト_台帳の経済に効くか": r["経済に効くか"], "サイト_分野": s["主な産業分野"],
            "サイト_台帳の分野": r["分野"], "サイト_台帳の類型": r["類型"]}


def cmd_targets(_: argparse.Namespace) -> int:
    rows = measured(read_csv(LEDGER / "ledger.csv"))
    write_csv(set_dir("all") / "targets.csv", TARGET_HEADER, [target_row(r) for r in rows])
    print(f"測る側 {len(rows)} 本", Counter(reach_group(r["到達点"]) for r in rows))
    return 0


def stratum(t: dict) -> tuple[str, str]:
    """試走の層（PILOT_STRATA の鍵）。参考額は経済に効くかが空かどうかで分ける。"""
    g = reach_group(t["到達点"])
    if g == "参考額":
        return (g, "空" if t["サイト_台帳の経済に効くか"] == "" else "判定済み")
    return (g, "")


def cmd_pilot(a: argparse.Namespace) -> int:
    """到達点の層ごとに種固定で抜く。初回の抜き取り（sample.csv）と、一次資料で直し済みの法律（corrections.csv）は除く。"""
    done = {r["id"] for r in read_csv(LEDGER / "sample.csv")} | {r["id"] for r in read_csv(DERIVED / "primary-source-corrections-v1" / "corrections.csv")}
    pool = [r for r in measured(read_csv(LEDGER / "ledger.csv")) if r["id"] not in done]
    if a.n != sum(PILOT_STRATA.values()):
        print(f"--n は層の合計 {sum(PILOT_STRATA.values())} だけ（本数を変えるなら PILOT_STRATA を直す）")
        return 2
    rng = random.Random(PILOT_SEED)
    picked: list[dict] = []
    for (group, econ), n in PILOT_STRATA.items():
        cands = [r for r in pool if reach_group(r["到達点"]) == group
                 and (not econ or (econ == "空") == (r["経済に効くか"] == ""))]
        picked += rng.sample(sorted(cands, key=lambda r: r["id"]), min(n, len(cands)))
    write_csv(set_dir("pilot") / "targets.csv", TARGET_HEADER, [target_row(r) for r in picked])
    print(f"試走 {len(picked)} 本（種 {PILOT_SEED}）", Counter(reach_group(r["到達点"]) for r in picked))
    return 0


def _run_fetch(args: list[str]) -> str:
    import subprocess
    import time
    p = None
    for attempt in range(4):
        try:
            p = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_law_source.py"), *args],
                               capture_output=True, text=True, timeout=120, check=False)
        except subprocess.TimeoutExpired:
            p = None
        if p is not None and p.returncode == 0:
            return p.stdout
        time.sleep(2 * (attempt + 1))
    return (p.stdout if p else "") or "取得できない\n"


def fetched_ok(text: str) -> bool:
    """資料ファイルが本文と会議録の両方を取れているか。取れなかったファイルは次の fetch で取り直す。"""
    if "【議案本文】" not in text or "【会議録】" not in text:
        return False
    honbun, kokkai = text.split("【議案本文】", 1)[1].split("【会議録】", 1)
    return not honbun.strip().startswith("取得できない") and bool(kokkai.strip()) and not kokkai.strip().startswith("取得できない")


def cmd_fetch(a: argparse.Namespace) -> int:
    """議案本文と会議録（題名＋提案、その回次）を取り、1本1ファイルにまとめる（resample_verification.fetch と同じ形）。"""
    SOURCES.mkdir(parents=True, exist_ok=True)
    stats = Counter()
    for r in read_csv(set_dir(a.set) / "targets.csv"):
        path = SOURCES / f"{r['id']}.txt"
        if path.exists() and fetched_ok(path.read_text(encoding="utf-8")):
            stats["既にある"] += 1
            continue
        session = r["id"].split("-")[1]
        title = r["題名"].removesuffix("案")
        honbun = _run_fetch(["honbun", r["id"]])
        kokkai = _run_fetch(["kokkai", f"{title} 提案", session])
        if "該当 0 件" in kokkai or kokkai.startswith("取得できない"):
            kokkai += "\n" + _run_fetch(["kokkai", title, session])
        path.write_text(f"法律：{r['id']} {r['題名']}\n\n【議案本文】\n{honbun}\n\n【会議録】\n{kokkai}\n", encoding="utf-8")
        stats["本文あり" if not honbun.startswith("取得できない") else "本文なし"] += 1
    print(dict(stats))
    return 0


def prompt_version(v: str) -> str:
    return f"primary-triage-v1/prompt-{v}.md（版 {v}）"


def set_prompt_version(name: str) -> str:
    p = set_dir(name) / "versions.json"
    return json.loads(p.read_text(encoding="utf-8"))["読み手"] if p.exists() else "v1"


def cmd_prompts(a: argparse.Namespace) -> int:
    v = a.version or PROMPT_CURRENT
    body = PROMPTS[v].read_text(encoding="utf-8")
    vp = set_dir(a.set) / "versions.json"
    vp.parent.mkdir(parents=True, exist_ok=True)
    vp.write_text(json.dumps({"読み手": v, "裁定": "v1"}, ensure_ascii=False) + "\n", encoding="utf-8")
    n = 0
    for r in read_csv(set_dir(a.set) / "targets.csv"):
        for line, order in LINES.items():
            out = LOCAL / a.set / f"line{line}" / f"{r['id']}.json"
            text = (body.replace("{id}", r["id"]).replace("{title}", r["題名"]).replace("{source}", str((SOURCES / f"{r['id']}.txt").relative_to(ROOT)))
                    .replace("{order}", order).replace("{line}", line).replace("{out}", str(out.relative_to(ROOT))))
            p = LOCAL / "prompts" / f"line{line}" / f"{r['id']}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            out.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
            n += 1
    print(f"指示文 {n} 件 → {LOCAL / 'prompts'}")
    return 0


def norm(item: str, v: str) -> str:
    v = (v or "").strip()
    if item == "主な産業分野":
        return norm_field(v) if v not in ("", UNDECIDED) else v
    return v


def canonical(item: str, v: str) -> str:
    """labels.csv に書く値。corrections.csv と同じ語（経済に効くかは「制度」、分野は19区分の正式名）にそろえ、定義に無い値は止める。"""
    if item == "経済に効くか":
        v = v.replace("制度のみ", "制度")
        if v not in ("経済に効く", "制度", UNDECIDED):
            raise ValueError(f"経済に効くかの値「{v}」が定義に無い")
        return v
    if item == "主な産業分野":
        f = norm(item, v)
        if f == "経済全体":
            return WHOLE_LABEL
        if f not in FIELDS:
            raise ValueError(f"分野の値「{v}」が19区分に無い")
        return f
    if v not in KINDS:
        raise ValueError(f"類型の値「{v}」が定義に無い")
    return v


def needs_ruling(site: dict, a: dict, b: dict) -> dict[str, str]:
    """{項目: 裁定に回す理由}。空なら2系統の一致をそのまま採用する。"""
    out: dict[str, str] = {}
    low = "低" in (a.get("確信"), b.get("確信"))
    for item in ITEMS:
        va, vb = norm(item, a.get(item, "")), norm(item, b.get(item, ""))
        if UNDECIDED in (va, vb) or not va or not vb:
            out[item] = "判定不能"
        elif va != vb:
            out[item] = "割れ"
        elif low:
            out[item] = "確信が低い"
        elif site[item] and va != norm(item, site[item]):  # サイトに値（主張）が無い項目は埋めるだけなので裁定に回さない
            out[item] = "値の変更"
    return out


def _load_line(d: Path, line: str) -> dict[str, dict]:
    p = d / f"line{line}.json"
    return {x["id"]: x for x in json.loads(p.read_text(encoding="utf-8"))} if p.exists() else {}


def site_of(t: dict) -> dict[str, str]:
    return {"類型": t["サイト_類型"], "経済に効くか": t["サイト_経済に効くか"], "主な産業分野": t["サイト_分野"]}


def cmd_queue(a: argparse.Namespace) -> int:
    d = set_dir(a.set)
    A, B = _load_line(d, "A"), _load_line(d, "B")
    targets = read_csv(d / "targets.csv")
    missing = [t["id"] for t in targets if t["id"] not in A or t["id"] not in B]
    if missing:
        print("2系統の判定が無い：", missing)
        return 1
    body = PROMPT_ADJ.read_text(encoding="utf-8")
    queue = []
    for t in targets:
        i = t["id"]
        why = needs_ruling(site_of(t), A[i], B[i])
        if not why:
            continue
        case = LOCAL / a.set / "adjudicate" / f"{i}.json"
        out = LOCAL / a.set / "rulings" / f"{i}.json"
        case.parent.mkdir(parents=True, exist_ok=True)
        out.parent.mkdir(parents=True, exist_ok=True)
        item = {"id": i, "題名": t["題名"], "到達点": t["到達点"],
                "争点": [{"項目": k, "裁定に回す理由": v, "サイト": site_of(t)[k] or "（空）", "系統A": A[i].get(k, ""), "系統B": B[i].get(k, "")} for k, v in why.items()],
                "系統A": A[i], "系統B": B[i]}
        case.write_text(json.dumps(item, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        (LOCAL / "prompts" / "adjudicate").mkdir(parents=True, exist_ok=True)
        (LOCAL / "prompts" / "adjudicate" / f"{i}.md").write_text(
            body.replace("{id}", i).replace("{case}", str(case.relative_to(ROOT))).replace("{out}", str(out.relative_to(ROOT)))
            .replace("{source}", str((SOURCES / f"{i}.txt").relative_to(ROOT))), encoding="utf-8")
        queue.append({"id": i, "争点": why})
    (d / "queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reasons = Counter(v for q in queue for v in q["争点"].values())
    print(f"{len(targets)} 本中 裁定待ち {len(queue)} 本（項目 {sum(reasons.values())}）", dict(reasons))
    return 0


def decide(t: dict, a: dict, b: dict, ruling: dict | None, reader_version: str = "v1") -> list[dict]:
    """1本の決着。項目ごとに (値, 判定者, 理由, 引用)。判定不能も行に残す（経済に効くかは判定不能として扱う。類型・分野は行を置かない）。"""
    site = site_of(t)
    why = needs_ruling(site, a, b)
    ruled = {r["項目"]: r for r in (ruling or {}).get("裁定", [])}
    url = ";".join(dict.fromkeys((a.get("出典URL") or []) + (b.get("出典URL") or [])))
    rows = []
    for item in ITEMS:
        if item in why:
            if item not in ruled:
                raise ValueError(f"{t['id']}：{item} は裁定待ち（{why[item]}）なのに rulings.json に裁定が無い")
            r = ruled[item]
            value, who, reason, quote = r["値"], f"Sonnet 裁定（{why[item]}、正しい側：{r.get('正しい側', '')}）", r["理由"], r.get("引用", "")
            version = f"{prompt_version(reader_version)}・{PROMPT_ADJ_VERSION}"
        else:
            value = a[item]
            who = "Haiku 2系統（系統A 議案本文から・系統B 会議録から）が一致"
            reason = a.get({"類型": "類型の理由", "経済に効くか": "経済の理由", "主な産業分野": "分野の理由"}[item], "")
            quote, version = (a.get("引用") or [""])[0], prompt_version(reader_version)
        if value == UNDECIDED and item != "経済に効くか":
            continue
        name = "分野" if item == "主な産業分野" else item
        out_value = canonical(item, value)
        before = {"類型": t.get("サイト_台帳の類型", site["類型"]), "主な産業分野": t.get("サイト_台帳の分野", site["主な産業分野"]),
                  "経済に効くか": t["サイト_台帳の経済に効くか"] or f"（未判定・到達点 {t['到達点']}）"}[item]
        rows.append({"id": t["id"], "項目": name, "直した値": out_value, "直す前の値": before or "（空）", "理由": reason, "引用": quote,
                     "出典URL": url, "判定者": who, "指示文": version, "記録": f"data/derived/primary-triage-v1/{t.get('_set', '')}/"})
    return rows


def differs_from_site(site: dict[str, str], row: dict[str, str]) -> bool:
    """labels.csv の行が、サイトの主張（値がある項目だけ）と違うか。"""
    item = "主な産業分野" if row["項目"] == "分野" else row["項目"]
    claim = site[item]
    if not claim:
        return False
    try:
        return canonical(item, claim) != row["直した値"]
    except ValueError:  # サイトの値が定義の語でなければ、違う値として数える
        return True


def cmd_apply(a: argparse.Namespace) -> int:
    d = set_dir(a.set)
    A, B = _load_line(d, "A"), _load_line(d, "B")
    rp = d / "rulings.json"
    rulings = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else {}
    targets = read_csv(d / "targets.csv")
    missing = [t["id"] for t in targets if t["id"] not in A or t["id"] not in B]
    if missing:
        print("2系統の判定が無い：", missing)
        return 1
    new = []
    for t in targets:
        t["_set"] = a.set
        new += decide(t, A[t["id"]], B[t["id"]], rulings.get(t["id"]), set_prompt_version(a.set))
    ids = {t["id"] for t in targets}
    kept = [r for r in read_csv(LABELS) if r["id"] not in ids]
    rows = sorted(kept + new, key=lambda r: (r["id"], ITEMS.index("主な産業分野" if r["項目"] == "分野" else r["項目"])))
    write_csv(LABELS, CORR_HEADER, rows)
    changed = sum(1 for r in new if differs_from_site(site_of(next(t for t in targets if t["id"] == r["id"])), r))
    print(f"{len(targets)} 本 → 行 {len(new)}（サイトの主張と違う値 {changed}）", Counter((r["項目"], r["直した値"]) for r in new).most_common(8))
    return 0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    ph = k / n
    c = z * math.sqrt(ph * (1 - ph) / n + z * z / (4 * n * n))
    d = 1 + z * z / n
    return (max(0.0, (ph + z * z / (2 * n) - c) / d), min(1.0, (ph + z * z / (2 * n) + c) / d))


def ruling_rate(pilot: list[dict], ruled: set[str], all_targets: list[dict]) -> dict:
    """裁定に回る率（1本あたり）。試走の層ごとの率を、全件での層の割合で重みづける（試走は定例などを厚く抜いたので素の平均は偏る）。
    試走に無い層（国の収支など）は試走全体の率で置く。"""
    by: dict[tuple, list[int]] = {}
    for t in pilot:
        by.setdefault(stratum(t), []).append(int(t["id"] in ruled))
    raw = len(ruled & {t["id"] for t in pilot}) / len(pilot)
    share = Counter(stratum(t) for t in all_targets)
    n_all = len(all_targets)
    weighted = sum(cnt / n_all * (statistics.mean(by[k]) if k in by else raw) for k, cnt in share.items())
    lo, hi = wilson(sum(sum(v) for v in by.values()), len(pilot))
    return {"素の率": round(raw, 3), "層で重みづけた率": round(weighted, 3), "素の率の95%区間（Wilson）": [round(lo, 3), round(hi, 3)],
            "層ごと（試走の本数・裁定の本数・全件の本数）": {f"{g}{'・' + e if e else ''}": [len(by.get((g, e), [])), sum(by.get((g, e), [])), share[(g, e)]]
                                                   for (g, e) in sorted(share, key=lambda k: -share[k])}}


def cmd_estimate(_: argparse.Namespace) -> int:
    """pilot/usage.json（実測）から全件を見積もる。

    usage.json：{"単価": {モデル: [入力, 出力] ドル/100万トークン}, "段階単価": {モデル: {"閾値": 入力トークン, "単価": [入力, 出力]}},
    "並行": {役割: 本数}, "呼び出し": [{"役割": "読み手|裁定", "モデル", "id", "入力トークン", "出力トークン", "秒"}], "取得": {"本数", "秒"}}。
    入力・出力の内訳が無い呼び出しは "合計トークン" と "入力の比" で分ける。
    費用は2つ出す。基本：段階単価なし。上限：入力が閾値を超えた呼び出しを段階単価で数える（合計トークンは複数ターンの和で、
    1回の入力ではないので、上限側に倒れる）。"""
    d = set_dir("pilot")
    u = json.loads((d / "usage.json").read_text(encoding="utf-8"))
    targets = read_csv(set_dir("all") / "targets.csv")
    pilot = read_csv(d / "targets.csv")
    rulings = json.loads((d / "rulings.json").read_text(encoding="utf-8"))
    n_all, n_pilot = len(targets), len(pilot)
    calls = u["呼び出し"]
    rate = ruling_rate(pilot, set(rulings), targets)

    def tokens(c: dict) -> tuple[float, float]:
        if "入力トークン" in c:
            return c["入力トークン"], c["出力トークン"]
        tot = c["合計トークン"]
        return tot * u["入力の比"], tot * (1 - u["入力の比"])

    def cost(c: dict, tiered: bool) -> float:
        tin, tout = tokens(c)
        pin, pout = u["単価"][c["モデル"]]
        tier = u.get("段階単価", {}).get(c["モデル"])
        if tiered and tier and tin > tier["閾値"]:
            pin, pout = tier["単価"]
        return (tin * pin + tout * pout) / 1e6

    per_law = {"読み手": 2.0, "裁定": rate["層で重みづけた率"]}
    out: dict = {"試走の本数": n_pilot, "全件の本数": n_all, "裁定に回る率": rate, "役割": {}}
    total = {"基本": 0.0, "上限": 0.0}
    total_sec = 0.0
    for role in ("読み手", "裁定"):
        cs = [c for c in calls if c["役割"] == role]
        if not cs:
            continue
        n_calls = per_law[role] * n_all
        base = n_calls * statistics.mean(cost(c, False) for c in cs)
        upper = n_calls * statistics.mean(cost(c, True) for c in cs)
        sec = statistics.mean(c["秒"] for c in cs)
        wall = n_calls * sec / u["並行"][role]
        total["基本"] += base
        total["上限"] += upper
        total_sec += wall
        out["役割"][role] = {"モデル": cs[0]["モデル"], "1本あたりの呼び出し": round(per_law[role], 3), "全件の呼び出し": round(n_calls),
                            "1回の入力トークン（平均）": round(statistics.mean(tokens(c)[0] for c in cs)),
                            "1回の出力トークン（平均）": round(statistics.mean(tokens(c)[1] for c in cs)), "1回の秒（平均）": round(sec),
                            "費用（ドル、基本）": round(base, 2), "費用（ドル、上限：段階単価）": round(upper, 2),
                            "所要（時間、並行 {} 本）".format(u["並行"][role]): round(wall / 3600, 2)}
    adj = out["役割"].get("裁定")
    if adj:
        hi = rate["素の率の95%区間（Wilson）"][1]
        out["裁定の率が区間の上端のとき"] = {"全件の呼び出し": round(hi * n_all),
                                     "裁定の費用（ドル、基本）": round(adj["費用（ドル、基本）"] / per_law["裁定"] * hi, 2)}
    fetch_sec = u["取得"]["秒"] / u["取得"]["本数"] * n_all
    out["一次資料の取得"] = {"1本の秒（平均）": round(u["取得"]["秒"] / u["取得"]["本数"], 1), "全件（時間、直列）": round(fetch_sec / 3600, 2)}
    out["合計"] = {"費用（ドル、基本）": round(total["基本"], 2), "費用（ドル、上限：段階単価）": round(total["上限"], 2),
                 "AI の所要（時間）": round(total_sec / 3600, 2), "取得を足した所要（時間）": round((total_sec + fetch_sec) / 3600, 2)}
    out["前提"] = u.get("前提", "")
    (d / "estimate.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("targets").set_defaults(fn=cmd_targets)
    sp = sub.add_parser("pilot")
    sp.add_argument("--n", type=int, default=10)
    sp.set_defaults(fn=cmd_pilot)
    for name, fn in (("fetch", cmd_fetch), ("prompts", cmd_prompts), ("queue", cmd_queue), ("apply", cmd_apply)):
        s = sub.add_parser(name)
        s.add_argument("--set", default="pilot", help="pilot（試走）か all（全件。ねくの了承の後）")
        if name == "prompts":
            s.add_argument("--version", choices=sorted(PROMPTS), help=f"読み手の指示文の版（既定 {PROMPT_CURRENT}）")
        s.set_defaults(fn=fn)
    sub.add_parser("estimate").set_defaults(fn=cmd_estimate)
    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
