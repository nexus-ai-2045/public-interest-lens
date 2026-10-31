"""全件検査の資料（法律の原文）と、較正の追加標本をそろえる。機械処理だけ（モデルは使わない）。

  fetch  対象の法律の議案本文を衆議院のページから取り、<出力>/<法律ID>.txt に置く（audit_fanout plan --corpus に渡す）。
         題名・回次・号数が一致しないページは置かない（fetch_bill_text.verify）。長い本文は頭と末尾（理由）を残す。
  extra  較正（118本）に足す追加標本を、対象（plan --out の targets.jsonl）から無作為に引く。
         118本と凍結標本は除く。正解づくりは別（モデルの判定を見せずに原文で決める）。

  truth  較正の正解 calibration-truth.csv を作る。母集団は額ありの法律。元の正解（sample-verdicts の118本のうち額あり）に、
         モデルの判定を見せず原文で決めた Opus の判定（--opus の JSONL）を重ねる。Opus が不明の法律は正解に入れない。
         Opus の判定：合格＝範囲が全体かつ分類が評価対象、不合格＝範囲が一部または分類が制度整備、他は不明。

使い方：
  python3 scripts/audit_corpus.py fetch --targets .local/audit-full/targets.jsonl --out .local/audit-corpus
  python3 scripts/audit_corpus.py extra --targets .local/audit-full/targets.jsonl --n 40 --seed 20261031 --out .local/audit-truth/extra-ids.txt
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
import urllib.request
from pathlib import Path

from scripts import fetch_bill_text as fb

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_VERDICTS = ROOT / "data/derived/evaluation-ledger-v1/sample-verdicts.csv"
FROZEN = ROOT / "data/derived/audit-fanout-v1/frozen-sample.csv"
HEAD, TAIL = 6000, 2000


def read_targets(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def fetch_one(row: dict) -> tuple[str, str]:
    """(本文, 失敗理由)。"""
    m = re.fullmatch(r"(衆法|参法|閣法)-(\d+)-(\d+)", row["id"])
    if not m:
        return "", "IDの形式が違う"
    kind, kai, num = m.group(1), int(m.group(2)), int(m.group(3))
    url = f"{fb.BASE}g{kai:03d}{fb.CODE[kind][0]}{num:03d}.htm"
    try:
        lines = fb.page_lines(urllib.request.urlopen(url, timeout=30).read())
    except Exception as e:  # noqa: BLE001 404 など。理由に型名を残す
        return "", f"取得できず（{type(e).__name__}）"
    why = fb.verify(lines, row["題名"], kind, kai, num)
    if why:
        return "", why
    i = next(k for k, ln in enumerate(lines) if ln.endswith("号") and "第" in ln)
    body = "\n".join(ln for ln in lines[i + 1:] if not ln.startswith(("ホームページについて", "Webアクセシビリティ")))
    if len(body) > HEAD + TAIL:
        body = body[:HEAD] + "\n……（中略）……\n" + body[-TAIL:]
    return body, ""


def cmd_fetch(a: argparse.Namespace) -> None:
    rows = read_targets(Path(a.targets))
    if a.ids:
        want = set(Path(a.ids).read_text(encoding="utf-8").split())
        rows = [r for r in rows if r["id"] in want]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    log, ok = [], 0
    for r in rows:
        dst = out / f"{r['id']}.txt"
        if dst.exists():
            ok += 1
            continue
        body, why = fetch_one(r)
        if body:
            dst.write_text(body, encoding="utf-8")
            ok += 1
        else:
            log.append({"id": r["id"], "理由": why})
        time.sleep(a.sleep)
    (out / "_failed.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"対象": len(rows), "取得": ok, "取得できず": len(log)}, ensure_ascii=False))


def cmd_extra(a: argparse.Namespace) -> None:
    used = {r["id"] for r in csv.DictReader(SAMPLE_VERDICTS.open(encoding="utf-8"))}
    if FROZEN.exists():
        used |= {r["id"] for r in csv.DictReader(FROZEN.open(encoding="utf-8"))}
    pool = sorted(r["id"] for r in read_targets(Path(a.targets)) if r["id"] not in used)
    pick = sorted(random.Random(a.seed).sample(pool, a.n))
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(pick) + "\n", encoding="utf-8")
    print(json.dumps({"母集団": len(pool), "引いた": len(pick), "seed": a.seed}, ensure_ascii=False))


def opus_verdict(d: dict) -> str:
    if d["範囲"] == "一部" or d["分類"] == "制度整備":
        return "不合格"
    if d["範囲"] == "全体" and d["分類"] == "評価対象":
        return "合格"
    return "不明"


def cmd_truth(a: argparse.Namespace) -> None:
    ledger = {r["id"]: r for r in csv.DictReader((ROOT / "data/derived/evaluation-ledger-v1/ledger.csv").open(encoding="utf-8"))}
    has_amount = lambda i: ledger[i]["到達点"].startswith(("参考額", "額（個別"))
    opus: dict[str, dict] = {}
    for f in a.opus:
        for line in Path(f).read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                opus[d["id"]] = d
    rows = []
    for r in csv.DictReader(SAMPLE_VERDICTS.open(encoding="utf-8")):
        if has_amount(r["id"]):
            rows.append({"id": r["id"], "判定": r["判定"], "出所": "元の正解（2系統Sonnet＋Opus・題名から）", "元の正解": r["判定"], "Opus範囲": "", "Opus分類": "", "Opus確信度": ""})
    have = {r["id"] for r in rows}
    for i, d in sorted(opus.items()):
        if i not in have:
            rows.append({"id": i, "判定": "", "出所": "", "元の正解": "", "Opus範囲": "", "Opus分類": "", "Opus確信度": ""})
    out = []
    for r in rows:
        d = opus.get(r["id"])
        if d:
            v = opus_verdict(d)
            r.update({"Opus範囲": d["範囲"], "Opus分類": d["分類"], "Opus確信度": d["確信度"]})
            if v == "不明":
                continue  # 決まらないものは正解に入れない（分母から外す）
            r["判定"], r["出所"] = v, "Opus（モデルの判定を見せず、議案本文で）"
        out.append(r)
    dst = Path(a.out)
    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, ["id", "判定", "出所", "元の正解", "Opus範囲", "Opus分類", "Opus確信度"], lineterminator="\n")
        w.writeheader()
        w.writerows(out)
    changed = sum(1 for r in out if r["元の正解"] and r["元の正解"] != r["判定"])
    print(json.dumps({"正解の本数": len(out), "うち合格": sum(r["判定"] == "合格" for r in out), "元の正解を取り直した本数": sum(1 for r in out if r["Opus範囲"] and r["元の正解"]),
                      "うち判定が変わった": changed, "Opusが不明で外した": len(rows) - len(out)}, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--targets", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--ids", help="この一覧（空白区切り）の法律だけ取る")
    f.add_argument("--sleep", type=float, default=0.4)
    f.set_defaults(fn=cmd_fetch)
    e = sub.add_parser("extra")
    e.add_argument("--targets", required=True)
    e.add_argument("--n", type=int, required=True)
    e.add_argument("--seed", type=int, required=True)
    e.add_argument("--out", required=True)
    e.set_defaults(fn=cmd_extra)
    t = sub.add_parser("truth")
    t.add_argument("--opus", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.set_defaults(fn=cmd_truth)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
