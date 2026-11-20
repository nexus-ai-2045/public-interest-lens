"""抜き取り検証の2回目（新しい標本、2026-11-19）。初回（種 20261030、118本）とは別の法律を、同じ層の作り方で抜き直す。

  python3 scripts/resample_verification.py sample    # 標本を作る → sample-v2/sample.csv・manifest.json
  python3 scripts/resample_verification.py fetch     # 一次資料を取って .local/sample-v2/sources/{id}.txt に置く（読み手に渡す）
  python3 scripts/resample_verification.py compare   # 2系統（lineA.json・lineB.json）とサイトの値を突き合わせる → verdicts.csv・split-queue.json（記録は固定。作り直しは --force）
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
  サイトの「制度だけ」は到達点で読む（evaluation_rules.site_is_institutional。初回の読み直しで決めた規則）。
  割れた項目が合否を左右するときは「割れ」として裁定待ちに出す（rulings.json を置けば反映）。

訂正候補（correction-candidates.csv）の注意：
  類型・経済に効くかの行は primary-source-corrections-v1/corrections.csv と同じ列で、そのまま入れられる。
  ただし合否はサイトの到達点で読むので、経済に効くかの訂正は到達点まで直らないと合格に戻らない。
  分野の行は今の primary_source_corrections（項目は類型・経済に効くかだけ）では読めない。分野を直す経路が要る。
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
from scripts.evaluation_rules import (
    STATE_DEMOTED,
    STATE_FAILED,
    VERDICT_FAIL,
    amount_demoted,
    site_is_institutional,
)

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
        if p.returncode == 0 and p.stdout.strip():
            return p.stdout
        time.sleep(2 * (attempt + 1))
    return "取得できない\n"  # 4回とも失敗：エラーの出力を本文として残さない（次の fetch で取り直す）


def _has_body(text: str) -> bool:
    """取れた議案本文があるか。取得に失敗した本文（空・取得できない）は取り直す。"""
    _head, sep, rest = text.partition("【議案本文】\n")
    body = rest.split("\n\n【会議録】", 1)[0].strip()
    return bool(sep) and bool(body) and not body.startswith("取得できない")


def cmd_fetch() -> int:
    """議案本文と会議録（題名＋提案、その回次）を取り、1本1ファイルにまとめる。読み手はこのファイルだけを読む。"""
    SOURCES.mkdir(parents=True, exist_ok=True)
    for r in read_csv(OUT / "sample.csv"):
        path = SOURCES / f"{r['id']}.txt"
        if path.exists() and _has_body(path.read_text(encoding="utf-8")):
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


def overriding(a: dict, b: dict, ruling: dict | None, confirmed=()) -> list[str]:
    """裁定が、2系統の一致を覆している項目（独立の確認が無いもの）。設計決定0007：採るのは2系統が一致した値なので、
    1つの裁定だけで一致を覆さない。覆すなら別の系統の独立の確認（rulings.json の「確認」）が要り、それまでは割れ（保留）。"""
    return [k for k, v in (ruling or {}).items() if a.get(k) == b.get(k) and v != a.get(k) and k not in confirmed]


def judge(site: dict, a: dict, b: dict, ruling: dict | None = None, confirmed=()) -> tuple[str, list[str], list[str]]:
    """(判定, 食い違い, 割れ)。ruling は裁定 {項目: 値}。2系統が食い違った項目は裁定で決める。
    2系統が一致した項目を裁定が覆すときは、confirmed（独立の確認がある項目）に入っていなければ割れ（保留）にする。"""
    ruling = ruling or {}
    held = set(overriding(a, b, ruling, confirmed))
    diffs, splits = [], []

    def agreed(k: str) -> str | None:
        if k in held:
            return None
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
        if field is None and "主な産業分野" not in held and norm_field(a["主な産業分野"]) == norm_field(b["主な産業分野"]):
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


def cmd_compare(force: bool = False) -> int:
    """verdicts.csv は裁定のあとの記録で、書き換えない（サイトの値が直ったかは台帳が判定し直す）。作り直すときだけ --force。"""
    if (OUT / "verdicts.csv").exists() and not force:
        print("verdicts.csv は記録として固定してある。作り直すときは compare --force")
        return 1
    A = {x["id"]: x for x in json.loads((OUT / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads((OUT / "lineB.json").read_text(encoding="utf-8"))}
    rulings_path = OUT / "rulings.json"
    rulings = json.loads(rulings_path.read_text(encoding="utf-8")) if rulings_path.exists() else {}
    ledger = {r["id"]: r for r in read_csv(LEDGER / "ledger.csv")}
    if (OUT / "verdicts.csv").exists():  # 作り直し：記録した時点のサイトの値で判定し直す（今のサイトの値は台帳が見る）
        ledger = {r["id"]: {"題名": ledger.get(r["id"], {}).get("題名", ""), **{k: r[f"サイト_{k}"] for k in SITE_KEYS}}
                  for r in read_csv(OUT / "verdicts.csv")}
    sample = read_csv(OUT / "sample.csv")
    missing = [r["id"] for r in sample if r["id"] not in A or r["id"] not in B]
    if missing:
        print("2系統の判定が無い：", missing)
        return 1
    rows, queue = [], []
    for s in sample:
        i = s["id"]
        site = ledger[i]
        ru = rulings.get(i, {})
        v, diffs, splits = judge(site, A[i], B[i], ru.get("値"), ru.get("確認", ()))
        if v == "割れ":
            queue.append({"id": i, "題名": site["題名"], "割れ": splits, "A": A[i], "B": B[i],
                          "裁定が一致を覆した項目（独立の確認待ち）": overriding(A[i], B[i], ru.get("値"), ru.get("確認", ()))})
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
    """(値, 理由, 引用, 判定者)。採った値（ruling の「値」）を出した裁定、なければ独立の確認、なければ2系統の一致。
    独立の確認が裁定を覆して2系統の値に戻した項目は、古い裁定の値を出さない。"""
    chosen = ruling.get("値", {}).get(item)
    for r in ruling.get("裁定", []):
        if r["項目"] == item and (chosen is None or r["値"] == chosen):
            return r["値"], r["理由"], r["引用"], r.get("裁定者", ruling.get("裁定者", ""))
    for r in ruling.get("確認の記録", []):
        if r["項目"] == item and r["値"] == chosen:
            return r["値"], r["理由"], (r.get("引用") or [""])[0], f"{r['確認者']}と Haiku 2系統が一致"
    reason = {"類型": a.get("類型の理由", ""), "経済に効くか": a.get("経済の理由", "")}.get(item, "")  # 分野の理由は読み手が書かない
    return a[item], reason, (a.get("引用") or [""])[0], "Haiku 2系統（系統A 議案本文から・系統B 会議録から）が一致"


RES_FIXED = "サイトの訂正で合格"
RES_HELD = "独立の確認待ち（裁定が2系統の一致を覆したため保留）"


def _causes(diffs: list[str], site_kind: str, reach: str) -> list[tuple[str, str]]:
    """食い違いから（原因, 直す項目）。直す項目は 範囲 なら空。"""
    out = []
    for d in diffs:
        head = d.split("：")[0]
        if head == "範囲":
            out.append((CAUSES["範囲"], ""))
        elif head == "類型":
            out.append((CAUSES["類型空" if not site_kind else "類型"], "類型"))
        elif head == "経済に効くか":
            out.append((CAUSES["経済定例" if reach == "効果なし（定例）" else "経済"], "経済に効くか"))
        elif head == "分野":
            out.append((CAUSES["分野"], "主な産業分野"))
    return out


def cmd_resolve() -> int:
    """不合格を原因で分け、決着を決める（AI は呼ばない）。サイトの値は直さない（訂正は primary-source-corrections-v1 の担当）。
    原因は裁定のあとの記録（verdicts.csv）の食い違いで分ける。決着と訂正候補は、今の台帳（ledger.csv）のサイトの値で判定し直して決める：
      合格に戻った → サイトの訂正で合格。範囲だけ → 参考に下げた（すでに順位・議員配分に使っていない）。
      それ以外 → 直す値を correction-candidates.csv に出して訂正候補に回した（額のある法律は直るまで額を参考に下げる）。"""
    A = {x["id"]: x for x in json.loads((OUT / "lineA.json").read_text(encoding="utf-8"))}
    B = {x["id"]: x for x in json.loads((OUT / "lineB.json").read_text(encoding="utf-8"))}
    rulings = json.loads((OUT / "rulings.json").read_text(encoding="utf-8"))
    ledger = {r["id"]: r for r in read_csv(LEDGER / "ledger.csv")}
    res, cands = [], []
    for r in read_csv(OUT / "verdicts.csv"):
        if r["判定"] not in ("不合格", "割れ"):
            continue
        i, ru, cur = r["id"], rulings.get(r["id"], {}), ledger[r["id"]]
        causes = [c for c, _ in _causes([d for d in r["食い違い"].split("／") if d], r["サイト_類型"], r["サイト_到達点"])]
        if r["判定"] == "割れ":
            causes.append("裁定が2系統の一致を覆した（独立の確認待ち）")
        v, now_diffs, _ = judge(cur, A[i], B[i], ru.get("値"), ru.get("確認", ()))
        now = _causes(now_diffs, cur["類型"], cur["到達点"])
        items = [item for _, item in now if item]
        url = (A[i].get("出典URL") or [""])[0]
        before = {"類型": cur["類型"], "経済に効くか": cur["経済に効くか"] or f"（到達点 {cur['到達点']}）", "主な産業分野": cur["分野"]}
        for item in items:
            val, why, quote, who = _value(A[i], B[i], ru, item)
            cands.append({"id": i, "項目": "分野" if item == "主な産業分野" else item, "直した値": val.replace("制度のみ", "制度"),
                          "直す前の値": before[item], "理由": why, "引用": quote, "出典URL": url, "判定者": who,
                          "指示文": "sample-v2/prompt-v2.md（版 v2）" + ("・prompt-adjudicate-v1.md" if ru else ""),
                          "記録": "data/derived/evaluation-ledger-v1/sample-v2/"})
        has_amount = amount_demoted(VERDICT_FAIL, cur["到達点"], cur["確かさ"])  # 台帳（ledger_state）と同じ規則
        if v == "割れ":
            how = RES_HELD
        elif v == "合格":
            how = RES_FIXED
        elif items:
            how = RES_CANDIDATE + ("（額は直るまで参考に下げた扱い）" if has_amount else "")
        else:
            how = RES_DEMOTED
        res.append({"id": i, "層": r["層"], "原因": "／".join(dict.fromkeys(causes)), "決着": how,
                    "理由": r["食い違い"], "今の食い違い": "／".join(now_diffs), "サイトの到達点": cur["到達点"],
                    "参考値（額・円）": cur["額（円）"], "サイトの確かさ": cur["確かさ"]})
    with (OUT / "resolutions.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["id", "層", "原因", "決着", "理由", "今の食い違い", "サイトの到達点", "参考値（額・円）", "サイトの確かさ"])
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
    no_scope = sum(1 for r in res.values() if any(c.startswith("サイト") for c in r["原因"].split("／")))
    lo2, hi2 = wilson(no_scope, n)
    who = Counter(x["正しい側"] for v in rulings.values() for x in v["裁定"])
    by_reach: dict[str, Counter] = {}
    for r in rows:
        by_reach.setdefault(r["サイト_到達点"], Counter())[r["判定"]] += 1
    cand = read_csv(OUT / "correction-candidates.csv")
    out = {
        "定義": "合格＝2系統の独立判定が一致した項目（類型・経済に効くか、額のある法律は分野、参考額は範囲も）が、すべてサイトの値と合う。2系統が割れた項目は裁定者が一次資料で決めた値で比べる。裁定が2系統の一致を覆した項目は、独立の確認が無ければ割れ（保留）として合格にも不合格にも数えない",
        "標本": n,
        "2系統だけの判定（裁定前）": dict(first),
        "裁定後の判定": dict(t),
        "裁定でどちらが正しかったか（項目）": dict(who),
        "不合格率（裁定後）": round(fail / n, 4), "不合格率の95%区間（Wilson）": [round(lo, 4), round(hi, 4)],
        "範囲を除いた不合格（サイトの値の誤り）": no_scope, "その率の95%区間（Wilson）": [round(lo2, 4), round(hi2, 4)],
        "不合格の原因（法律ごと、重なりあり）": dict(Counter(c for r in res.values() for c in r["原因"].split("／"))),
        "決着": dict(Counter(r["決着"] for r in res.values())),
        "決着の無い不合格・割れ": sum(1 for r in rows if r["判定"] in ("不合格", "割れ") and r["id"] not in res),
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


STATE_PASS = "抜き取り検証で合格"
MEMO = "標本2（sample-v2）："


def ledger_state(site: dict, rec: tuple[dict, dict, dict]) -> tuple[str, str]:
    """標本2の法律の検証状態を、今のサイトの値で判定し直して決める（AI は呼ばない）。site は 類型・分類・到達点・分野・確かさ。
    合格：サイトの値が読み直しと合う（訂正されて合った法律はメモに「訂正で合格」）。
    参考に下げた：不合格で、額のある到達点（初回と同じ規則 amount_demoted。評価対象外は額が無いので下げない）か、範囲だけの不合格。
    不合格のまま：額の無い法律で、サイトの値が訂正されるまで（訂正候補は correction-candidates.csv）。"""
    a, b, ru = rec
    v, diffs, splits = judge(site, a, b, ru.get("値"), ru.get("確認", ()))
    if v == "合格":
        fixed = "（訂正で合格）" if ru.get("初回") == "不合格" else ""
        return STATE_PASS, f"{MEMO}合格{fixed}"
    reason = "／".join(diffs) or "割れ（独立の確認待ち）：" + "・".join(splits)
    if v == "不合格" and all(d.startswith("範囲") for d in diffs):
        return STATE_DEMOTED, f"{MEMO}{reason}"
    if amount_demoted(VERDICT_FAIL, site["到達点"], site.get("確かさ", "")):
        return STATE_DEMOTED, f"{MEMO}訂正待ち（額は参考に下げた）：{reason}"
    return STATE_FAILED, f"{MEMO}訂正待ち：{reason}"


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["sample", "fetch", "compare", "resolve", "report"])
    ap.add_argument("--force", action="store_true", help="compare：記録として固定した verdicts.csv を作り直す")
    args = ap.parse_args()
    if args.cmd == "compare":
        return cmd_compare(args.force)
    return {"sample": cmd_sample, "fetch": cmd_fetch, "resolve": cmd_resolve, "report": cmd_report}[args.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
