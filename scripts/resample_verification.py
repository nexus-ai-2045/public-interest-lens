"""抜き取り検証の2回目（新しい標本、2026-11-19）。初回（種 20261030、118本）とは別の法律を、同じ層の作り方で抜き直す。

  python3 scripts/resample_verification.py sample    # 標本を作る → sample-v2/sample.csv・manifest.json
  python3 scripts/resample_verification.py fetch     # 一次資料を取って .local/sample-v2/sources/{id}.txt に置く（読み手に渡す）
  python3 scripts/resample_verification.py compare   # 2系統（lineA.json・lineB.json）とサイトの値を突き合わせる → verdicts.csv・split-queue.json
  python3 scripts/resample_verification.py resolve   # 不合格を原因で分けて決着 → resolutions.csv・correction-candidates.csv
  python3 scripts/resample_verification.py report    # 集計 → sample-v2/result.json と README の結果の節の数

抽出の手順（初回と同じ規則で、種と母集団だけを変える）：
  1. 今の台帳（build_evaluation_ledger.build_rows、AI は呼ばない）を母集団にする。
  2. 初回の抜き取り（evaluation-ledger-v1/sample.csv）に入った法律を除く。初回と重ねないため。
  3. build_evaluation_ledger.make_sample をそのまま使い、種だけを SEED_V2 に替える（層・各層の枠は初回と同じ規則）。

突き合わせの規則（初回の compare_verification.judge と同じ項目。ただし分類は到達点で読む）：
  類型・経済に効くか・（額のある法律だけ）分野、（参考額だけ）範囲。2系統が一致した項目だけでサイトと比べる。
  範囲は参考額（産業全体の差）だけに当てる。個別の額は法律ごとの推定なので、初回と違い範囲を問わない。
  分野が「コロナ対応」の参考額は、産業ではなく費用便益の群なので、分野・範囲を照合しない。
  サイトの「制度だけ」は到達点で読む（resolve_sample_failures.site_is_institutional。初回の読み直しで決めた規則）。
  割れた項目が合否を左右するときは「割れ」として裁定待ちに出す（rulings.json を置けば反映）。
"""
from __future__ import annotations

import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from scripts.compare_verification import norm_field
from scripts.resolve_sample_failures import site_is_institutional

SEED_V2 = 20261119
LEDGER = ROOT / "data" / "derived" / "evaluation-ledger-v1"
OUT = LEDGER / "sample-v2"
SOURCES = ROOT / ".local" / "sample-v2" / "sources"
UNDECIDED = "判定不能"
# 「コロナ対応」は産業ではなく、コロナ対策の支出の費用便益に当てた群の名前（曝露ランキングからも除く）。分野・範囲の照合をしない
COVID_FIELD = "コロナ対応"


def read_csv(p: Path) -> list[dict]:
    with p.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cmd_sample() -> int:
    from scripts import (
        build_evaluation_ledger as bel,  # 台帳の作り方が、この表（判定）を読むので遅れて読む
    )

    rows = bel.build_rows(bel.load())
    first = {r["id"] for r in read_csv(LEDGER / "sample.csv")}
    pool = [r for r in rows if r["id"] not in first]
    bel.SEED = SEED_V2  # 規則は make_sample のまま、種だけを替える
    sm = bel.make_sample(pool)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "sample.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["層", "id", "題名"])
        w.writeheader()
        w.writerows({"層": bel.stratum(r), "id": r["id"], "題名": r["題名"]} for r in sm)
    by_stratum = Counter(bel.stratum(r) for r in sm)
    pop_stratum = Counter(bel.stratum(r) for r in pool)
    manifest = {
        "種": SEED_V2, "母集団": len(rows), "除いた初回の抜き取り": len(first), "抽出の母集団": len(pool),
        "標本": len(sm), "層の数": len(by_stratum),
        "層ごと": {k: {"母集団": pop_stratum[k], "標本": by_stratum[k]} for k in sorted(by_stratum)},
        "手順": "build_evaluation_ledger.make_sample（初回と同じ層と枠の規則）を、初回の118本を除いた母集団に、種 20261119 で当てた",
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"抜き取り {len(sm)} 本（{len(by_stratum)} 層、種 {SEED_V2}、初回の {len(first)} 本を除いた {len(pool)} 本から）")
    return 0


def _run_fetch(args: list[str]) -> str:
    import subprocess
    for attempt in range(4):
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "fetch_law_source.py"), *args],
                           capture_output=True, text=True, timeout=120, check=False)
        if p.returncode == 0:
            return p.stdout
        time.sleep(2 * (attempt + 1))
    return p.stdout or "取得できない\n"


def cmd_fetch() -> int:
    """議案本文と会議録（題名＋提案、その回次）を取り、1本1ファイルにまとめる。読み手はこのファイルだけを読む。"""
    SOURCES.mkdir(parents=True, exist_ok=True)
    for r in read_csv(OUT / "sample.csv"):
        path = SOURCES / f"{r['id']}.txt"
        if path.exists() and "【議案本文】" in path.read_text(encoding="utf-8"):
            continue
        session = r["id"].split("-")[1]
        title = r["題名"].removesuffix("案")
        honbun = _run_fetch(["honbun", r["id"]])
        kokkai = _run_fetch(["kokkai", f"{title} 提案", session])
        if "該当 0 件" in kokkai or kokkai.startswith("取得できない"):
            kokkai += "\n" + _run_fetch(["kokkai", title, session])
        path.write_text(f"法律：{r['id']} {r['題名']}\n\n【議案本文】\n{honbun}\n\n【会議録】\n{kokkai}\n", encoding="utf-8")
        print(r["id"], "本文" if not honbun.startswith("取得できない") else "本文なし", len(honbun), len(kokkai))
    return 0


def judge(site: dict, a: dict, b: dict, ruling: dict | None = None) -> tuple[str, list[str], list[str]]:
    """(判定, 食い違い, 割れ)。ruling は割れた項目の裁定 {項目: 値}。"""
    ruling = ruling or {}
    diffs, splits = [], []

    def agreed(k: str) -> str | None:
        if k in ruling:
            return ruling[k]
        return a[k] if a[k] == b[k] else None

    kind = agreed("類型")
    if kind is None:
        splits.append("類型")
    elif kind != UNDECIDED and site["類型"] and kind != site["類型"]:
        diffs.append(f"類型：サイト{site['類型']}／独立判定{kind}")
    elif kind != UNDECIDED and not site["類型"]:
        diffs.append(f"類型：サイトは空／独立判定{kind}")
    econ = agreed("経済に効くか")
    inst = site_is_institutional(site)
    if econ is None:
        splits.append("経済に効くか")
    elif econ != UNDECIDED and inst != (econ == "制度のみ"):
        diffs.append(f"経済に効くか：サイト{'制度だけ' if inst else '経済に効く'}（到達点 {site['到達点']}）／独立判定{econ}")
    if site["到達点"].startswith(("参考額", "額")) and site["分野"] != COVID_FIELD:
        sf = norm_field(site["分野"])
        field = agreed("主な産業分野")
        field = norm_field(field) if field is not None else None
        if field is None and norm_field(a["主な産業分野"]) == norm_field(b["主な産業分野"]):
            field = norm_field(a["主な産業分野"])
        if field is None:
            splits.append("主な産業分野")
        elif field != sf:
            diffs.append(f"分野：サイト{sf}／独立判定{field}")
        scope = agreed("範囲") if site["到達点"].startswith("参考額") else "（個別の額は範囲を問わない）"
        if scope is None:
            splits.append("範囲")
        elif scope == "産業の一部（狭い特例）":
            diffs.append("範囲：法律の対象は産業の一部なのに、産業全体の差を額に当てている")
        elif scope == "産業を特定できない" and sf != "経済全体":
            diffs.append(f"範囲：産業を特定できない法律に産業「{sf}」を当てている")
    verdict = "不合格" if diffs else ("割れ" if splits else "合格")
    return verdict, diffs, splits


SITE_KEYS = ("類型", "分類", "到達点", "経済に効くか", "分野", "額（円）", "確かさ")


def cmd_compare() -> int:
    A = {x["id"]: x for x in json.loads((OUT / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads((OUT / "lineB.json").read_text(encoding="utf-8"))}
    rulings_path = OUT / "rulings.json"
    rulings = json.loads(rulings_path.read_text(encoding="utf-8")) if rulings_path.exists() else {}
    ledger = {r["id"]: r for r in read_csv(LEDGER / "ledger.csv")}
    sample = read_csv(OUT / "sample.csv")
    missing = [r["id"] for r in sample if r["id"] not in A or r["id"] not in B]
    if missing:
        print("2系統の判定が無い：", missing)
        return 1
    rows, queue = [], []
    for s in sample:
        i = s["id"]
        site = ledger[i]
        v, diffs, splits = judge(site, A[i], B[i], rulings.get(i, {}).get("値"))
        if v == "割れ":
            queue.append({"id": i, "題名": site["題名"], "割れ": splits, "A": A[i], "B": B[i]})
        rows.append({"id": i, "層": s["層"], "判定": v, "食い違い": "／".join(diffs + [f"割れ:{x}" for x in splits if v == "割れ"]),
                     **{f"サイト_{k}": site[k] for k in SITE_KEYS}})
    with (OUT / "verdicts.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (OUT / "split-queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(Counter(r["判定"] for r in rows), "裁定待ち", len(queue))
    return 0


CAUSES = {
    "範囲": "仕組み：参考額は産業全体の差で、法律の範囲（産業の一部）に合わせていない",
    "類型": "サイトの類型の誤り",
    "類型空": "サイトの類型の欠け（値が無い）",
    "経済定例": "サイトの定例の当てはめの誤り（定例・延長だけでなく中身を変えていた）",
    "経済": "サイトの経済に効くかの誤り",
    "分野": "サイトの分野の誤り（曝露ランキングの産業の群に効く）",
}
RES_DEMOTED = "参考に下げた"
RES_CANDIDATE = "訂正候補に回した"
CAND_HEADER = ["id", "項目", "直した値", "直す前の値", "理由", "引用", "出典URL", "判定者", "指示文", "記録"]


def _value(a: dict, b: dict, ruling: dict, item: str) -> tuple[str, str, str, str]:
    """(値, 理由, 引用, 判定者)。裁定があれば裁定、なければ2系統の一致。"""
    for r in ruling.get("裁定", []):
        if r["項目"] == item:
            return r["値"], r["理由"], r["引用"], r.get("裁定者", ruling.get("裁定者", ""))
    reason = a.get("類型の理由" if item == "類型" else "経済の理由", "")
    return a[item], reason, (a.get("引用") or [""])[0], "Haiku 2系統（系統A 議案本文から・系統B 会議録から）が一致"


def cmd_resolve() -> int:
    """不合格を原因で分け、決着を決める（AI は呼ばない）。サイトの値は直さない（訂正は primary-source-corrections-v1 の担当）。
    範囲だけの不合格：参考額を参考に下げた（すでに順位・議員配分に使っていない）。
    それ以外：直す値を correction-candidates.csv に出して訂正候補に回した。額のある法律は、直るまで額を参考に下げた扱い。"""
    A = {x["id"]: x for x in json.loads((OUT / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads((OUT / "lineB.json").read_text(encoding="utf-8"))}
    rulings = json.loads((OUT / "rulings.json").read_text(encoding="utf-8"))
    res, cands = [], []
    for r in read_csv(OUT / "verdicts.csv"):
        if r["判定"] != "不合格":
            continue
        i, ru = r["id"], rulings.get(r["id"], {})
        diffs = [d for d in r["食い違い"].split("／") if d]
        causes, items = [], []
        for d in diffs:
            head = d.split("：")[0]
            if head == "範囲":
                causes.append(CAUSES["範囲"])
            elif head == "類型":
                causes.append(CAUSES["類型空" if not r["サイト_類型"] else "類型"])
                items.append(("類型", r["サイト_類型"]))
            elif head == "経済に効くか":
                causes.append(CAUSES["経済定例" if r["サイト_到達点"] == "効果なし（定例）" else "経済"])
                items.append(("経済に効くか", r["サイト_経済に効くか"] or f"（到達点 {r['サイト_到達点']}）"))
            elif head == "分野":
                causes.append(CAUSES["分野"])
                items.append(("主な産業分野", r["サイト_分野"]))
        url = (A[i].get("出典URL") or [""])[0]
        for item, before in items:
            v, why, quote, who = _value(A[i], B[i], ru, item)
            cands.append({"id": i, "項目": "分野" if item == "主な産業分野" else item, "直した値": v.replace("制度のみ", "制度"),
                          "直す前の値": before, "理由": why, "引用": quote, "出典URL": url, "判定者": who,
                          "指示文": "sample-v2/prompt-v2.md（版 v2）" + ("・prompt-adjudicate-v1.md" if ru else ""),
                          "記録": "data/derived/evaluation-ledger-v1/sample-v2/"})
        has_amount = r["サイト_到達点"].startswith(("参考額", "額", "国の収支"))
        if items:
            how = RES_CANDIDATE + ("（額は直るまで参考に下げた扱い）" if has_amount else "")
        else:
            how = RES_DEMOTED
        res.append({"id": i, "層": r["層"], "原因": "／".join(dict.fromkeys(causes)), "決着": how,
                    "理由": "／".join(diffs), "サイトの到達点": r["サイト_到達点"], "参考値（額・円）": r["サイト_額（円）"],
                    "サイトの確かさ": r["サイト_確かさ"]})
    with (OUT / "resolutions.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["id", "層", "原因", "決着", "理由", "サイトの到達点", "参考値（額・円）", "サイトの確かさ"])
        w.writeheader()
        w.writerows(res)
    with (OUT / "correction-candidates.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, CAND_HEADER)
        w.writeheader()
        w.writerows(cands)
    print(Counter(x["決着"] for x in res), "訂正候補", Counter(c["項目"] for c in cands))
    return 0


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5
    return ((c - h) / d, (c + h) / d)


def cmd_report() -> int:
    rows = read_csv(OUT / "verdicts.csv")
    A = {x["id"]: x for x in json.loads((OUT / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads((OUT / "lineB.json").read_text(encoding="utf-8"))}
    rulings = json.loads((OUT / "rulings.json").read_text(encoding="utf-8"))
    res = {r["id"]: r for r in read_csv(OUT / "resolutions.csv")}
    n = len(rows)
    site = lambda r: {k: r[f"サイト_{k}"] for k in ("類型", "分類", "到達点", "分野")}
    first = Counter(judge(site(r), A[r["id"]], B[r["id"]])[0] for r in rows)
    t = Counter(r["判定"] for r in rows)
    fail = t["不合格"]
    lo, hi = wilson(fail, n)
    no_scope = sum(1 for r in rows if r["判定"] == "不合格" and res[r["id"]]["決着"] != RES_DEMOTED)
    lo2, hi2 = wilson(no_scope, n)
    who = Counter(x["正しい側"] for v in rulings.values() for x in v["裁定"])
    by_reach: dict[str, Counter] = {}
    for r in rows:
        by_reach.setdefault(r["サイト_到達点"], Counter())[r["判定"]] += 1
    cand = read_csv(OUT / "correction-candidates.csv")
    out = {
        "定義": "合格＝2系統の独立判定が一致した項目（類型・経済に効くか、額のある法律は分野、参考額は範囲も）が、すべてサイトの値と合う。割れた項目とサイトと食い違った項目は裁定者が一次資料で決めた値で比べる",
        "標本": n,
        "2系統だけの判定（裁定前）": dict(first),
        "裁定後の判定": dict(t),
        "裁定でどちらが正しかったか（項目）": dict(who),
        "不合格率（裁定後）": round(fail / n, 4), "不合格率の95%区間（Wilson）": [round(lo, 4), round(hi, 4)],
        "範囲を除いた不合格（サイトの値の誤り）": no_scope, "その率の95%区間（Wilson）": [round(lo2, 4), round(hi2, 4)],
        "不合格の原因（法律ごと、重なりあり）": dict(Counter(c for r in res.values() for c in r["原因"].split("／"))),
        "決着": dict(Counter(r["決着"] for r in res.values())),
        "不合格のまま（決着なし）": fail - len(res),
        "訂正候補（項目）": dict(Counter(c["項目"] for c in cand)),
        "到達点ごと（裁定後）": {k: dict(v) for k, v in sorted(by_reach.items())},
    }
    (OUT / "result.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


def load_record() -> dict[str, tuple[dict, dict, dict]]:
    """台帳が読む：{id: (系統A, 系統B, 裁定)}。記録が無ければ空。"""
    if not (OUT / "lineA.json").is_file():
        return {}
    A = {x["id"]: x for x in json.loads((OUT / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads((OUT / "lineB.json").read_text(encoding="utf-8"))}
    p = OUT / "rulings.json"
    rulings = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    first = {r["id"]: r["判定"] for r in read_csv(OUT / "verdicts.csv")} if (OUT / "verdicts.csv").exists() else {}
    return {i: (a, B[i], {**rulings.get(i, {}), "初回": first.get(i, "")}) for i, a in A.items() if i in B}


STATE_PASS, STATE_FAILED, STATE_DEMOTED = "抜き取り検証で合格", "抜き取り検証で不合格", "参考に下げた"
MEMO = "標本2（sample-v2）："


def ledger_state(site: dict, rec: tuple[dict, dict, dict]) -> tuple[str, str]:
    """標本2の法律の検証状態を、今のサイトの値で判定し直して決める（AI は呼ばない）。
    サイトの値が訂正されて読み直しの値と合えば合格。範囲だけの不合格は参考に下げた（参考額は産業全体の差）。
    それ以外の不合格は、訂正されるまで不合格のまま（訂正候補は correction-candidates.csv）。"""
    a, b, ru = rec
    v, diffs, _ = judge(site, a, b, ru.get("値"))
    if v == "合格":
        fixed = "（訂正で合格）" if ru.get("初回") == "不合格" else ""
        return STATE_PASS, f"{MEMO}合格{fixed}"
    if v == "不合格" and all(d.startswith("範囲") for d in diffs):
        return STATE_DEMOTED, f"{MEMO}{'／'.join(diffs)}"
    return STATE_FAILED, f"{MEMO}訂正待ち：{'／'.join(diffs) or '裁定待ち'}"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["sample", "fetch", "compare", "resolve", "report"])
    cmd = ap.parse_args().cmd
    return {"sample": cmd_sample, "fetch": cmd_fetch, "compare": cmd_compare, "resolve": cmd_resolve, "report": cmd_report}[cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
