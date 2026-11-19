"""新しく成立した法律に、AI が独立に付けた振り分けを取り込む（bill-triage-v1 の系統A・B と、系統2）。

成立法の一覧（enacted.csv）に載ったのに振り分けが無い法律は、評価に進めない。会期中は成立のたびに増えるので、
取り込みをこの1本にまとめる。AI の判断はここでは作らない。3本の結果ファイルを確かめて、決まった規則で並べるだけ。

手順：
  1. python3 scripts/apply_new_triage.py prepare --out <作業フォルダ>
       振り分けが無い成立法の input.csv（id・題名・付託委員会（衆／参））と、基準書の写しを系統ごとのフォルダに置く。
  2. 互いの結果を見ない3つの AI が、lane-A・lane-B（spec.md）と lane-L2（criteria.md・criteria-v2-fields.md）の
     output.csv を書く。渡した依頼文は prompt-v1.md・prompt-line2.md として作業フォルダに置く。
  3. python3 scripts/apply_new_triage.py apply --work <作業フォルダ> --model-a <名前> --model-b <名前> --model-line2 <名前>
       triage.csv と bill-triage-v1-line2/labels.csv の末尾に足し、入力・3本の結果・依頼文・記録を
       data/derived/bill-triage-v1/additions/<日付>/ に残す。

採用の決まり（docs/reports/bill-triage-v1.md、設計決定0007 §4）：系統A・B で種類・分野・判定がすべて一致したものだけ採用。
評価対象は指標も一致したものだけ。一致しなければ保留で、人が埋めない。combine() は既存の全行を再現する（tests/test_apply_new_triage.py）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENACTED = ROOT / "data" / "acquired" / "bill-census-full" / "enacted.csv"
V1 = ROOT / "data" / "derived" / "bill-triage-v1"
LINE2 = ROOT / "data" / "derived" / "bill-triage-v1-line2"
SPECS = {"lane-A": [V1 / "spec.md"], "lane-B": [V1 / "spec.md"],
         "lane-L2": [LINE2 / "criteria.md", LINE2 / "criteria-v2-fields.md", V1 / "spec.md"]}
PROMPTS = ("prompt-v1.md", "prompt-line2.md")
V1_COLUMNS = ["id", "種類", "分野", "指標", "判定", "理由"]
LINE2_COLUMNS = ["id", "題名", "付託委員会", "系統2_種類", "系統2_分野", "系統2_指標", "系統2_判定", "系統2_理由"]
HOLD = "保留"
KINDS = {"新規", "実質改正", "定型改正", "組織手続"}
VERDICTS = {"評価対象", "評価対象外"}
NO_FIELD = "対応表なし"


def read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def header(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle), [])


def append(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    """既存の行に触れず末尾に足す。改行はその表の最後の行と同じにする（既存の行の差分を作らない）。"""
    raw = path.read_bytes()
    if not raw.endswith(b"\n"):
        raise ValueError(f"{path.name} の末尾に改行が無い")
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.DictWriter(handle, fieldnames=columns, lineterminator="\r\n" if raw.endswith(b"\r\n") else "\n").writerows(rows)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def law_id(row: dict[str, str]) -> str:
    return f"{row['種別']}-{row['提出回次']}-{row['番号']}"


def untriaged(enacted: list[dict[str, str]], triaged: set[str]) -> list[dict[str, str]]:
    """振り分けが無い成立法の入力行（一覧の順）。材料は題名と付託委員会だけ。"""
    return [{"id": law_id(r), "題名": r["題名"], "付託委員会（衆／参）": f"{r['付託委員会_衆']}／{r['付託委員会_参']}"}
            for r in enacted if law_id(r) not in triaged]


def combine(law: str, a: dict[str, str], b: dict[str, str]) -> dict[str, str]:
    """系統A・B の1行ずつから triage.csv の1行を作る。一致した項目だけ値を入れる。"""
    same = {k: a[k] == b[k] for k in ("種類", "分野", "指標", "判定")}
    if not (same["種類"] and same["分野"] and same["判定"]):
        result = "保留（2系統が不一致）"
    elif a["判定"] == "評価対象" and not same["指標"]:
        result = "保留（指標が不一致）"
    else:
        result = a["判定"]
    out = {"id": law, "結果": result}
    out.update({k: a[k] if same[k] else "" for k in ("種類", "分野", "指標")})
    out.update({f"A_{k}": a[k] for k in V1_COLUMNS[1:]})
    out.update({f"B_{k}": b[k] for k in V1_COLUMNS[1:]})
    return out


# spec.md の「2. 分野」と「3. 指標」の語彙（指標は分野ごと）。
V1_INDICATORS = {
    "金融": {"不良債権比率", "貸出残高", "企業倒産件数"},
    "交通・移動": {"旅客輸送の付加価値", "利用件数", "就業者数"},
    "宿泊・観光": {"宿泊者数", "宿泊業の付加価値", "客室数"},
    "通信・ネット": {"通信業の付加価値", "ブロードバンド普及率", "ネット企業の時価総額"},
    "半導体・電子": {"世界輸出シェア", "生産額"},
    "エネルギー": {"電力価格", "発電構成", "エネルギー効率"},
    "労働市場": {"労働生産性", "賃金", "雇用の流動性"},
    "行政のデジタル化": {"電子申請率", "行政手続きの時間"},
}
OUT_KINDS = {"定型改正", "組織手続"}


def check_v1(rows: list[dict[str, str]], ids: list[str], name: str) -> None:
    """spec.md の語彙と、4（判定）の決まりに合うか。迷いの「保留」は種類・分野・判定のどれにも書いてよい。"""
    if [r.get("id") for r in rows] != ids:
        raise ValueError(f"{name}：id の並びが input.csv と違う")
    for r in rows:
        if set(r) != set(V1_COLUMNS):
            raise ValueError(f"{name}：列が違う {r.get('id')}")
        kind, field, indicator, verdict = r["種類"], r["分野"], r["指標"], r["判定"]
        if kind not in KINDS | {HOLD} or verdict not in VERDICTS | {HOLD} or field not in {*V1_INDICATORS, NO_FIELD, HOLD} or not r["理由"].strip():
            raise ValueError(f"{name}：語彙にない値か、理由が空 {r['id']}")
        if indicator and indicator != HOLD and indicator not in V1_INDICATORS.get(field, set()):
            raise ValueError(f"{name}：分野にない指標 {r['id']}")
        if verdict == "評価対象" and not (kind in KINDS - OUT_KINDS and field in V1_INDICATORS and indicator in V1_INDICATORS[field] | {HOLD}):
            raise ValueError(f"{name}：評価対象なのに、種類・分野・指標が評価対象の条件に合わない {r['id']}")
        if verdict == "評価対象外" and not (kind in OUT_KINDS or field == NO_FIELD):
            raise ValueError(f"{name}：評価対象外なのに、種類も分野も対象外の条件に当たらない {r['id']}")


def check_independent(work: Path, models: dict[str, str]) -> None:
    """2系統が別に付けたことの最低限の確かめ。同じファイル・同じ理由の写し・同じ実行の名前は通さない。"""
    a, b = work / "lane-A" / "output.csv", work / "lane-B" / "output.csv"
    if sha256(a) == sha256(b):
        raise ValueError("lane-A と lane-B の output.csv が同じバイト（2系統の独立が確かめられない）")
    if [r["理由"] for r in read(a)] == [r["理由"] for r in read(b)]:
        raise ValueError("lane-A と lane-B の理由が全行同じ（写しの疑い）")
    if len({models["lane-A"], models["lane-B"], models["lane-L2"]}) < 3:
        raise ValueError("3系統の実行の名前（--model-*）は別々に書く（同じモデルなら別のセッションであることを書き分ける）")


def check_line2(rows: list[dict[str, str]], inputs: list[dict[str, str]]) -> None:
    if [r.get("id") for r in rows] != [r["id"] for r in inputs]:
        raise ValueError("lane-L2：id の並びが input.csv と違う")
    for r, source in zip(rows, inputs):
        if set(r) != set(LINE2_COLUMNS):
            raise ValueError(f"lane-L2：列が違う {r.get('id')}")
        if (r["題名"], r["付託委員会"]) != (source["題名"], source["付託委員会（衆／参）"]):
            raise ValueError(f"lane-L2：題名か付託委員会が input.csv と違う {r['id']}")
        out = r["系統2_種類"] in {"定型改正", "組織手続"} or r["系統2_分野"] in (NO_FIELD, HOLD)
        if r["系統2_種類"] not in KINDS or r["系統2_判定"] != ("評価対象外" if out else "評価対象") or not r["系統2_理由"].strip():
            raise ValueError(f"lane-L2：語彙にない値か、判定が種類・分野と合わないか、理由が空 {r['id']}")


def prepare(out: Path) -> int:
    rows = untriaged(read(ENACTED), {r["id"] for r in read(V1 / "triage.csv")})
    out.mkdir(parents=True, exist_ok=True)
    write(out / "input.csv", list(rows[0]) if rows else ["id", "題名", "付託委員会（衆／参）"], rows)
    for lane, specs in SPECS.items():
        (out / lane).mkdir(exist_ok=True)
        shutil.copyfile(out / "input.csv", out / lane / "input.csv")
        for spec in specs:
            shutil.copyfile(spec, out / lane / spec.name)
    print(f"振り分けが無い成立法 {len(rows)}本 → {out / 'input.csv'}")
    return 0


def apply(work: Path, models: dict[str, str], today: str) -> int:
    inputs = read(work / "input.csv")
    ids = [r["id"] for r in inputs]
    triage = read(V1 / "triage.csv")
    now = untriaged(read(ENACTED), {r["id"] for r in triage})
    if inputs != now:
        raise ValueError("input.csv が、いまの成立法の一覧と振り分けの表から作る入力と違う（prepare からやり直す）")
    if not ids:
        print("振り分けが無い成立法は 0本。何も足さない。")
        return 0
    for lane, specs in SPECS.items():  # 判定に渡した基準書が、いまの正本と同じバイトか
        for spec in specs:
            if sha256(work / lane / spec.name) != sha256(spec):
                raise ValueError(f"{lane}/{spec.name} が正本と違う")
        if sha256(work / lane / "input.csv") != sha256(work / "input.csv"):
            raise ValueError(f"{lane}/input.csv が input.csv と違う")
    a, b, line2 = (read(work / lane / "output.csv") for lane in SPECS)
    check_v1(a, ids, "lane-A")
    check_v1(b, ids, "lane-B")
    check_line2(line2, inputs)
    check_independent(work, models)
    added = [combine(i, x, y) for i, x, y in zip(ids, a, b)]
    if header(V1 / "triage.csv") != ["id", "結果", "種類", "分野", "指標", *(f"{x}_{k}" for x in "AB" for k in V1_COLUMNS[1:])] \
            or header(LINE2 / "labels.csv") != LINE2_COLUMNS:
        raise ValueError("triage.csv か bill-triage-v1-line2/labels.csv の列が想定と違う")
    files = {"input.csv": work / "input.csv", **{f"{lane}.csv": work / lane / "output.csv" for lane in SPECS},
             **{name: work / name for name in PROMPTS}}
    for name, source in files.items():  # 表に書く前に、記録に残すものが全部そろっているか
        if not source.is_file() or not source.read_text(encoding="utf-8").strip():
            raise ValueError(f"記録に残す {name} が無いか空（{source}）")
    for path in (V1 / "triage.csv", LINE2 / "labels.csv"):
        if not path.read_bytes().endswith(b"\n"):
            raise ValueError(f"{path.name} の末尾に改行が無い")
    keep = V1 / "additions" / today
    if keep.exists():
        raise ValueError(f"{keep.relative_to(ROOT)} がもうある（同じ日の2回目は --date に別の名前を付ける。例 2026-11-19-2）")
    keep.mkdir(parents=True)
    for name, source in files.items():
        shutil.copyfile(source, keep / name)
    append(V1 / "triage.csv", header(V1 / "triage.csv"), added)
    append(LINE2 / "labels.csv", LINE2_COLUMNS, line2)
    record = {
        "date": today, "laws": ids,
        "lanes": {"lane-A": {"model": models["lane-A"], "prompt": "prompt-v1.md"}, "lane-B": {"model": models["lane-B"], "prompt": "prompt-v1.md"},
                  "lane-L2": {"model": models["lane-L2"], "prompt": "prompt-line2.md"}},
        "material": "題名と付託委員会（衆／参）だけ。各系統は自分のフォルダの input.csv と基準書だけを読み、互いの結果を見ない",
        "sha256": {**{name: sha256(keep / name) for name in sorted(files)},
                   **{spec.name: sha256(spec) for spec in {s for specs in SPECS.values() for s in specs}}},
        "results": {r["id"]: r["結果"] for r in added},
    }
    (keep / "record.json").write_text(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(added)}本を足した → {keep.relative_to(ROOT)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare").add_argument("--out", type=Path, required=True)
    p = sub.add_parser("apply")
    p.add_argument("--work", type=Path, required=True)
    for lane in ("a", "b", "line2"):
        p.add_argument(f"--model-{lane}", required=True)
    p.add_argument("--date", default=str(datetime.now().astimezone().date()))
    args = parser.parse_args(argv)
    if args.command == "prepare":
        return prepare(args.out)
    return apply(args.work, {"lane-A": args.model_a, "lane-B": args.model_b, "lane-L2": args.model_line2}, args.date)


if __name__ == "__main__":
    sys.exit(main())
