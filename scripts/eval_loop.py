"""毎日の評価ループの入出力：queue.json をバッチに分け、AI の木（scripts/workflows/）の結果を表に取り込む。

木の中身は Haiku 2系統 → Sonnet 突き合わせ → Opus 整合確認（docs/自動更新.md の「評価ループ」）。
このスクリプトは判定をしない。バッチを作ることと、結果を決まった表に書くことだけをする。

使い方：
  python3 -m scripts.eval_loop prepare --out <作業フォルダ>
      → <作業フォルダ>/tiebreak/t000.json…（8本ずつ）、field/b000.json…（6本ずつ）、lines/l000.json…（8本ずつ）を作り、木に渡す n を出す
  python3 -m scripts.eval_loop pack --work <作業フォルダ>
      → 各バッチの snapshot、原本の sha256、2系統の結果ファイルの位置、file-backed packet を書く。判定も起動もしない
  python3 -m scripts.eval_loop verify-lanes --work <作業フォルダ> --kind field|tiebreak|lines --batch <b000> --lane-a <結果> --lane-b <結果> --candidate <候補.json>
      → 別 session の2結果が同じ入力 hash で一致した行だけを、現行 apply の labels 形で書く
  python3 -m scripts.eval_loop apply-candidates --work <作業フォルダ> --kind field|tiebreak|lines --batch <b000> --candidate <候補.json> [--inputs <inputs.json>] [--dest <表.csv>]
      → 候補の kind、batch、入力 hash が manifest と一致するときだけ既存の apply へ渡す。違うときは表を書かない。--dest を省くと本番の表へ書く
  python3 -m scripts.eval_loop apply-tiebreak <木の結果.json>
      → data/derived/bill-triage-v1/tiebreak.csv に足す（同じ id は新しい結果で置き換える）
  python3 -m scripts.eval_loop apply-field <木の結果.json>
      → data/derived/ai-field-v1/labels.csv に足す（同じ id は新しい結果で置き換える）
  python3 -m scripts.eval_loop apply-lines <木の結果.json> <作業フォルダ>/lines/inputs.json
      → data/derived/bill-triage-v2/tiebreak-lines.csv に足す（振り分け v2 の2系統の食い違いを、第3の判定者がどちらの系統を採るかで決めたもの）
      決め方「一致」は2系統の証跡を確かめていないので保留に落とす。一致を採用するのは verify-lanes → apply-candidates の経路だけ
木の結果.json は Workflow の出力そのもの（{"result": {"labels": [...]}} か {"labels": [...]}）。
Grok へ渡す経路は pack と verify-lanes で、Workflow の Haiku、Sonnet、Opus を起動しない。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

from scripts import daily_update

ROOT = Path(__file__).resolve().parents[1]
DERIVED = ROOT / "data" / "derived"
TIEBREAK = DERIVED / "bill-triage-v1" / "tiebreak.csv"
TIEBREAK_HEADER = ["id", "種類", "分野", "決め方", "理由"]
FIELD = DERIVED / "ai-field-v1" / "labels.csv"
FIELD_HEADER = ["id", "分野", "決め方", "理由"]
LINES = DERIVED / "bill-triage-v2" / "tiebreak-lines.csv"
# 系統1の値・系統2の値：判定したときの入力（判定|種類|分野|指標|理由）、概要の値：そのとき渡した会議録の要約（何をする・狙い）の指紋。
# 題名：判定したときの題名。空なら古い行で、題名の一致は見ない。
# どれかが今と違えば run-impact-v1.mjs は TB2 を当てず、agreement で保留に戻って翌朝また判定する
LINES_HEADER = ["id", "採用", "決め方", "理由", "系統1の値", "系統2の値", "概要の値", "題名"]


def value1(row: dict[str, str] | None) -> str:
    return "|".join((row["結果"], row["種類"], row["分野"], row["指標"], row["理由"])) if row else ""


def value2(row: dict[str, str] | None) -> str:
    return "|".join((row["系統2_判定"], row["系統2_種類"], row["系統2_分野"], row["系統2_指標"], row["系統2_理由"])) if row else ""


def overview_value(what: str, aim: str) -> str:
    """何をする・狙いの sha256 の先頭16桁（app/scripts/run-impact-v1.mjs と同じ式）。"""
    return hashlib.sha256(f"{what}\n{aim}".encode("utf-8")).hexdigest()[:16]


TIEBREAK_SIZE, FIELD_SIZE, LINES_SIZE = 8, 6, 8


def _read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _batches(rows: list, size: int, folder: Path, prefix: str) -> int:
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{prefix}*.json"):
        old.unlink()
    for start in range(0, len(rows), size):
        (folder / f"{prefix}{start // size:03d}.json").write_text(json.dumps(rows[start:start + size], ensure_ascii=False, indent=1), encoding="utf-8")
    return (len(rows) + size - 1) // size


def prepare(out: Path, fixture: dict | None = None) -> dict[str, int]:
    if fixture is None:
        queue = daily_update.evaluation_queue()
        triage = {r["id"]: r for r in _read(DERIVED / "bill-triage-v1" / "triage.csv")}
        line1 = {r["id"]: r for r in _read(DERIVED / "bill-triage-v2" / "labels-line1.csv")}
        line2 = {r["id"]: r for r in _read(DERIVED / "bill-triage-v2" / "labels-line2.csv")}
        overview = {r["id"]: r for r in _read(DERIVED / "law-overviews-v1" / "overviews.csv")}
    else:
        queue = {key: fixture.get(key, []) for key in ("振り分けの決着", "分野ラベル", "系統の決着")}
        triage = {r["id"]: r for r in fixture.get("triage", [])}
        line1 = {r["id"]: r for r in fixture.get("line1", [])}
        line2 = {r["id"]: r for r in fixture.get("line2", [])}
        overview = {r["id"]: r for r in fixture.get("overview", [])}
    tiebreak = [{
        "id": item["id"], "題名": item["題名"],
        "A": {"種類": triage[item["id"]]["A_種類"], "分野": triage[item["id"]]["A_分野"], "理由": triage[item["id"]]["A_理由"]},
        "B": {"種類": triage[item["id"]]["B_種類"], "分野": triage[item["id"]]["B_分野"], "理由": triage[item["id"]]["B_理由"]},
        "決める項目": [k for k in ("種類", "分野") if not triage[item["id"]][k]],
    } for item in queue["振り分けの決着"]]
    field = [{"id": item["id"], "title": item["題名"]} for item in queue["分野ラベル"]]

    def line(row: dict[str, str] | None, prefix: str, verdict: str) -> dict[str, str]:
        row = row or {}
        return {"判定": row.get(verdict, ""), "種類": row.get(prefix + "種類", ""), "分野": row.get(prefix + "分野", ""),
                "指標": row.get(prefix + "指標", ""), "理由": row.get(prefix + "理由", "")}

    lines = [{
        "id": item["id"], "題名": item["題名"],
        "系統1": line(line1.get(item["id"]), "", "結果"),
        "系統2": line(line2.get(item["id"]), "系統2_", "系統2_判定"),
        # 国会会議録の提案理由・討論の要約（law-overviews-v1）。題名だけで種類が決まらないときの材料。無ければ空。
        "何をする": overview.get(item["id"], {}).get("何をする", ""), "狙い": overview.get(item["id"], {}).get("狙い", ""),
    } for item in queue.get("系統の決着", [])]
    counts = {"tiebreak": _batches(tiebreak, TIEBREAK_SIZE, out / "tiebreak", "t"), "field": _batches(field, FIELD_SIZE, out / "field", "b"),
              "lines": _batches(lines, LINES_SIZE, out / "lines", "l")}
    # 木に渡した入力の指紋。apply-lines は今の表ではなくこれを残す（判定中に表が変わっても、判定した入力と結び付く）
    (out / "lines" / "inputs.json").write_text(json.dumps(
        {x["id"]: {"系統1の値": value1(line1.get(x["id"])), "系統2の値": value2(line2.get(x["id"])),
                   "概要の値": overview_value(x["何をする"], x["狙い"]), "題名": x["題名"]} for x in lines}, ensure_ascii=False, indent=1), encoding="utf-8")
    return counts


def _labels(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("result", data)["labels"]


def _merge(path: Path, header: list[str], new: list[dict[str, str]]) -> int:
    rows = {r["id"]: r for r in _read(path)}
    for row in new:
        rows[row["id"]] = row
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(rows.values(), key=lambda r: r["id"]))
    return len(new)


def apply_tiebreak(result: Path, dest: Path | None = None) -> int:
    return _merge(dest or TIEBREAK, TIEBREAK_HEADER, [
        # モデルがキーを「种類」（簡体字）で返すことがあるので、どちらでも読む。
        {"id": x["id"], "種類": x.get("種類") or x.get("种類", ""), "分野": x["分野"], "決め方": x["決め方"], "理由": x["理由"]}
        for x in _labels(result)])


def apply_field(result: Path, dest: Path | None = None) -> int:
    return _merge(dest or FIELD, FIELD_HEADER, [
        {"id": x["id"], "分野": x["field"], "決め方": x["how"], "理由": x["reason"]} for x in _labels(result)])


NO_OVERVIEW = overview_value("", "")


def hold_without_overview(row: dict[str, str], title: str) -> dict[str, str]:
    """規則 L1（学習記録 2026-10-18）：提案理由の要約が無い一部改正は、期限延長・手続の整理か中身の改正か題名からは
    決まらないので、評価対象・実質改正の系統を採っていても保留に戻す。同じ型（要約が無いのに推測で実質改正にする、
    時限法の改正で保留と実質改正が混在する）が 2026-10-17 と 2026-10-18 に出た。2026-10-18 は前日に保留だった
    閣法-155-14 などを、新しい資料なしに実質改正とした。"""
    if row["採用"] not in {"系統1", "系統2"} or row["概要の値"] != NO_OVERVIEW or "一部を改正" not in title:
        return row
    # 評価対象外（分野が無い）に決まる系統は、額を作らないので触らない
    if row[f"{row['採用']}の値"].split("|")[:2] != ["評価対象", "実質改正"]:
        return row
    return {**row, "採用": "保留", "決め方": "規則で保留",
            "理由": "要約の無い一部改正で、期限延長・手続の整理か中身の改正か題名から決まらない（規則 L1）"}


class LineStop(Exception):
    """同じ id の題名が一つに決まらないときは、表を書く前に止まる。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def line_agreement_proven(reported_pick: str, reported_how: str, lane_a: dict | None, lane_b: dict | None) -> bool:
    """決め方「一致」の自己申告だけでは採用しない。両 lane の session が異なり、入力 hash が同じで、
    pick が互いにかつ報告された採用と等しく、系統1か系統2で、理由が両方にあるときだけ真。
    入力 hash は eval_transport の lane ファイルと同じ2つ（input_sha256 = snapshot、inputs_sha256 = lines/inputs.json）。
    #150 の「同じ入力」の見方（系統1・系統2・概要・題名の指紋）はこの2つが同じバッチから来ることで担保される。
    lane の欠落・pick の改変・保留・同じ session・hash の食い違いは偽。新しい決め方は作らない。
    偽のとき呼び出し側は採用せず、既存の非採用（Sonnetが決定・Opusが修正・保留）のままにする。"""
    if reported_how != "一致" or reported_pick not in {"系統1", "系統2"}:
        return False
    if not lane_a or not lane_b:
        return False
    session_a, session_b = lane_a.get("session_id"), lane_b.get("session_id")
    if not session_a or session_a == session_b:
        return False
    for key in ("input_sha256", "inputs_sha256"):
        digest = lane_a.get(key)
        if not digest or digest != lane_b.get(key):
            return False
    pick = lane_a.get("pick")
    if pick not in {"系統1", "系統2"} or pick != lane_b.get("pick") or pick != reported_pick:
        return False
    if not str(lane_a.get("reason", "")).strip() or not str(lane_b.get("reason", "")).strip():
        return False
    return True


def _titles(folder: Path) -> dict[str, str]:
    titles: dict[str, str] = {}
    for path in sorted(folder.glob("l*.json")):
        for row in json.loads(path.read_text(encoding="utf-8")):
            bill_id = row["id"]
            title = row["題名"]
            previous = titles.get(bill_id)
            if previous is not None and previous != title:
                raise LineStop("同じ id の題名が違う")
            titles[bill_id] = title
    return titles


def hold_unproven_agreement(row: dict[str, str]) -> dict[str, str]:
    """2系統の証跡を確かめていない経路から来た決め方「一致」は、自己申告なので採用せず保留にする。"""
    if row["決め方"] != "一致":
        return row
    return {**row, "採用": "保留", "決め方": "規則で保留",
            "理由": "決め方「一致」に2系統の証跡が無い（自己申告だけでは採用しない。verify-lanes → apply-candidates を通す）"}


def apply_lines(result: Path, inputs: Path, dest: Path | None = None, agreement_verified: bool = False) -> int:
    """inputs：prepare が書いた <作業フォルダ>/lines/inputs.json（判定に渡した入力の指紋）。題名は指紋にあればそれ、無ければ同じフォルダのバッチ。同じ id の題名が違うときは表を書かず止まる。
    agreement_verified：verify-lanes が2系統の lane（別 session・同じ入力 hash・同じ pick・理由あり）を確かめた候補だけ真。
    偽（apply-lines の直接取り込み）のときは「一致」を保留に落とす。"""
    judged = json.loads(inputs.read_text(encoding="utf-8"))
    titles = _titles(inputs.parent)
    rows = []
    for label in _labels(result):
        seen = judged[label["id"]]
        title = seen.get("題名") or titles.get(label["id"], "")
        row = hold_without_overview({
            "id": label["id"], "採用": label["採用"], "決め方": label["決め方"], "理由": label["理由"],
            "系統1の値": seen["系統1の値"], "系統2の値": seen["系統2の値"], "概要の値": seen["概要の値"], "題名": title,
        }, title)
        if not agreement_verified:
            row = hold_unproven_agreement(row)
        rows.append({**row, "題名": title})
    return _merge(dest or LINES, LINES_HEADER, rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--out", type=Path, required=True)
    prepare_cmd.add_argument("--fixture", type=Path, help="試験用の queue JSON。本番の derived は読まない")
    sub.add_parser("pack", help="snapshot、原本 hash、2系統の packet を書く。判定はしない").add_argument("--work", type=Path, required=True)
    verify_cmd = sub.add_parser("verify-lanes", help="2系統の結果を検証し、一致行だけを labels 候補にする")
    verify_cmd.add_argument("--work", type=Path, required=True)
    verify_cmd.add_argument("--kind", choices=["tiebreak", "field", "lines"], required=True)
    verify_cmd.add_argument("--batch", required=True)
    verify_cmd.add_argument("--lane-a", type=Path, required=True)
    verify_cmd.add_argument("--lane-b", type=Path, required=True)
    verify_cmd.add_argument("--candidate", type=Path, required=True)
    apply_cmd = sub.add_parser("apply-candidates", help="hash が一致する候補だけを現行 apply の表へ書く")
    apply_cmd.add_argument("--work", type=Path, required=True)
    apply_cmd.add_argument("--kind", choices=["tiebreak", "field", "lines"], required=True)
    apply_cmd.add_argument("--batch", required=True)
    apply_cmd.add_argument("--candidate", type=Path, required=True)
    apply_cmd.add_argument("--inputs", type=Path)
    apply_cmd.add_argument("--dest", type=Path, help="省くと本番の表へ書く")
    sub.add_parser("apply-tiebreak").add_argument("result", type=Path)
    sub.add_parser("apply-field").add_argument("result", type=Path)
    lines_cmd = sub.add_parser("apply-lines")
    lines_cmd.add_argument("result", type=Path)
    lines_cmd.add_argument("inputs", type=Path)
    args = parser.parse_args(argv)
    if args.command == "prepare":
        fixture = json.loads(args.fixture.read_text(encoding="utf-8")) if args.fixture else None
        print(json.dumps(prepare(args.out, fixture), ensure_ascii=False))
    elif args.command == "pack":
        from scripts.eval_transport import TransportStop, pack_work
        try:
            print(json.dumps(pack_work(args.work), ensure_ascii=False))
        except (TransportStop, json.JSONDecodeError) as error:
            print(getattr(error, "reason", "バッチの JSON が読めない"), file=sys.stderr)
            return 2
    elif args.command == "verify-lanes":
        from scripts.eval_transport import verify_lanes
        report = verify_lanes(args.work, args.kind, args.batch, args.lane_a, args.lane_b, args.candidate)
        print(json.dumps({key: report[key] for key in ("status", "reason", "agreed", "execution", "live_session_verified", "launched")}, ensure_ascii=False))
        return 0 if report["status"] == "candidate" else 2
    elif args.command == "apply-candidates":
        from scripts.eval_transport import TransportStop, apply_candidates
        try:
            count = apply_candidates(args.kind, args.candidate, args.dest, args.inputs, args.work, args.batch)
        except (TransportStop, LineStop, json.JSONDecodeError, KeyError) as error:
            print(getattr(error, "reason", "候補の JSON が読めない"), file=sys.stderr)
            return 2
        print(f"候補 {count} 行")
    elif args.command == "apply-tiebreak":
        print(f"tiebreak.csv に {apply_tiebreak(args.result)} 行")
    elif args.command == "apply-lines":
        try:
            count = apply_lines(args.result, args.inputs)
        except LineStop as error:
            print(error.reason, file=sys.stderr)
            return 2
        print(f"tiebreak-lines.csv に {count} 行")
    else:
        print(f"labels.csv に {apply_field(args.result)} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
