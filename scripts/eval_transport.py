"""eval_loop のバッチを、2つの file-backed 系統へ渡して一致行だけ候補にする。

scripts/workflows の木は Claude の Workflow で、Haiku、Sonnet、Opus を名指しする。
このモジュールはその木を起動しない。モデル名を置き換えて実行済みにもしない。
判定は書かない。snapshot、原本の sha256、系統ごとの結果ファイルの位置、packet を作り、
後から置かれた2ファイルを検証して、現行 apply の labels 形の候補だけを書く。

一致は、別 session が同じ input hash に対して出した決定の値だけを見る。
不一致と根拠の無い行は候補に入れない。壊れた JSON、件数の過不足、同じ session の二重使用、
pack より後に変わった入力は、候補を書かずに止まる。apply も、候補に束縛した hash と
今の snapshot、source、inputs が manifest と違うときは、既存 apply を呼ばず表を書かない。
未知の値は 0 にも経済全体にもしない。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from scripts.eval_loop import LineStop, _labels, apply_field, apply_lines, apply_tiebreak

SCHEMA = "eval-transport-v1"
LANE_SCHEMA = "eval-lane-v1"
ALLOWED_PROVIDERS = {"fake", "grok"}
BANNED_MODELS = ("haiku", "sonnet", "opus")
BATCH_NAME = re.compile(r"^[tbl]\d{3}$")
KINDS = ("tiebreak", "field", "lines")

# 木のスキーマ（scripts/workflows/*.js）と同じ候補。木は実行しない。
FIELD_VALUES = (
    "エネルギー", "交通・移動", "労働市場", "半導体・電子", "宿泊・観光", "行政のデジタル化",
    "通信・ネット", "金融", "農林水産", "建設", "住宅・不動産", "教育", "医療・福祉", "製造業",
    "商業", "専門サービス・研究開発", "文化・娯楽・生活サービス", "経済全体",
)
TIEBREAK_KINDS = ("新規", "実質改正", "定型改正", "組織手続", "保留")
TIEBREAK_FIELDS = (
    "金融", "交通・移動", "宿泊・観光", "通信・ネット", "半導体・電子", "エネルギー",
    "労働市場", "行政のデジタル化", "対応表なし", "保留",
)
LINE_PICKS = ("系統1", "系統2", "保留")

FOLDERS = {"tiebreak": ("tiebreak", "t"), "field": ("field", "b"), "lines": ("lines", "l")}
DECISION = {"tiebreak": ("kind", "field"), "field": ("field",), "lines": ("pick",)}
AGREEMENT_KEY = {"tiebreak": "決め方", "field": "how", "lines": "決め方"}


class TransportStop(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _rel(work: Path, path: Path) -> str:
    return path.relative_to(work).as_posix()


def _inside(work: Path, relative: str) -> Path:
    path = (work / relative).resolve()
    try:
        path.relative_to(work.resolve())
    except ValueError as error:
        raise TransportStop("manifest のパスが作業フォルダの外である") from error
    return path


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _read_json(path: Path, label: str) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise TransportStop(f"{label} の JSON が読めない") from error


def _batches(work: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for kind in KINDS:
        folder, prefix = FOLDERS[kind]
        directory = work / folder
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"{prefix}*.json")):
            if not BATCH_NAME.fullmatch(path.stem):
                continue
            found.append((kind, path))
    return found


def _label_contract(kind: str) -> dict[str, object]:
    if kind == "field":
        return {"keys": ["id", "field", "reason"], "field": list(FIELD_VALUES)}
    if kind == "tiebreak":
        return {"keys": ["id", "kind", "field", "reason"], "kind": list(TIEBREAK_KINDS), "field": list(TIEBREAK_FIELDS)}
    return {"keys": ["id", "pick", "reason"], "pick": list(LINE_PICKS)}


def _packet(work: Path, kind: str, batch: str, digest: str, inputs_digest: str, lane: str, snapshot: str, result: str) -> dict[str, object]:
    """親が後で配る file-backed packet。この関数は送らない。"""
    return {
        "schema_version": 1,
        "message_id": f"eval-lane-{kind}-{batch}-{lane}",
        "from": "eval-transport",
        "to": "unassigned-grok-lane",
        "return_to": "codex-thread-01a1315b-725c-7dd2-9abe-6b59a8473183",
        "delivery_class": "normal",
        "reply_mode": "file-backed-result",
        "ack_required": True,
        "return_required": True,
        "idempotency_key": f"eval-lane-{kind}-{batch}-{digest[:12]}-{lane}",
        "correlation_id": "pil-grok-wave-20261022",
        "human_gate": "parent_must_dispatch",
        "max_attempts": 2,
        "source_budget": "この batch の snapshot だけを読む。他系統の結果と他 batch は読まない。実推論の一括起動はしない。",
        "obsidian_check": "対象外。製品の eval_loop を正本にする",
        "scope_route": "指定 snapshot を読み、指定の結果ファイルだけを書く",
        "closure_rule": "親が2系統を回収して verify-lanes を実行する。この packet は起動しない",
        "expected_output_path": result,
        "lane": lane,
        "kind": kind,
        "batch": batch,
        "input_sha256": digest,
        "inputs_sha256": inputs_digest,
        "snapshot_path": snapshot,
        "label_schema": _label_contract(kind),
        "provider": "grok",
        "session_rule": "結果の session_id は、この系統を実際に実行した session の識別子にする。もう一方と同じ値は使わない。",
        "rules": [
            "Haiku、Sonnet、Opus、Workflow の名前を置き換えて実行したことにしない",
            "もう一方の系統の出力を読まない",
            "決められない行は候補の値を作らない。理由の無い行は書かない",
            "額と点数を作らない。未知を 0 や空の分野で埋めない",
        ],
        "work_dir_note": "パスは pack に渡した作業フォルダからの相対パス",
        "launched": False,
    }


def pack_work(work: Path) -> dict[str, object]:
    batches = _batches(work)
    if not batches:
        raise TransportStop("pack するバッチが無い")
    inputs_path = work / "lines" / "inputs.json"
    inputs_bytes = b""
    if any(kind == "lines" for kind, _ in batches):
        if not inputs_path.is_file():
            raise TransportStop("系統の決着があるのに lines/inputs.json が無い")
        inputs_bytes = inputs_path.read_bytes()
    inputs_digest = sha256_bytes(inputs_bytes) if inputs_bytes else ""
    manifest_batches: list[dict[str, object]] = []
    for kind, source in batches:
        raw = source.read_bytes()
        try:
            rows = json.loads(raw)
        except json.JSONDecodeError as error:
            raise TransportStop(f"{source.name} の JSON が読めない") from error
        if not isinstance(rows, list) or not rows or not all(isinstance(row, dict) for row in rows):
            raise TransportStop(f"{source.name} の行が揃っていない")
        ids = [row.get("id") for row in rows]
        if any(not isinstance(item, str) or not item for item in ids) or len(ids) != len(set(ids)):
            raise TransportStop(f"{source.name} の id が揃っていない")
        batch = source.stem
        snapshot = work / "transport" / "snapshots" / kind / f"{batch}.json"
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_bytes(raw)
        digest = sha256_bytes(snapshot.read_bytes())
        relative_snapshot = _rel(work, snapshot)
        entry = {
            "kind": kind,
            "batch": batch,
            "snapshot": relative_snapshot,
            "source": _rel(work, source),
            "input_sha256": digest,
            "inputs_sha256": inputs_digest if kind == "lines" else "",
            "rows": len(rows),
            "ids": ids,
        }
        for lane in ("a", "b"):
            result = f"transport/lanes/{kind}/{batch}.lane-{lane}.json"
            packet_path = work / "transport" / "packets" / f"{kind}-{batch}-{lane}.json"
            _write_json(packet_path, _packet(work, kind, batch, digest, entry["inputs_sha256"], lane, relative_snapshot, result))
            entry[f"lane_{lane}"] = result
            entry[f"packet_{lane}"] = _rel(work, packet_path)
        manifest_batches.append(entry)
    manifest = {"schema": SCHEMA, "launched": False, "batches": manifest_batches}
    manifest_path = work / "transport" / "manifest.json"
    _write_json(manifest_path, manifest)
    return {"batches": len(manifest_batches), "manifest": _rel(work, manifest_path), "launched": False}


def _manifest_entry(work: Path, kind: str, batch: str) -> dict:
    if kind not in KINDS or not BATCH_NAME.fullmatch(batch):
        raise TransportStop("kind または batch が対象外")
    manifest = _read_json(work / "transport" / "manifest.json", "manifest")
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise TransportStop("manifest の形が違う")
    matches = [item for item in manifest.get("batches", []) if isinstance(item, dict) and item.get("kind") == kind and item.get("batch") == batch]
    if len(matches) != 1:
        raise TransportStop("manifest にその batch が無い")
    return matches[0]


def _lane_file(path: Path, expected_lane: str, kind: str, batch: str, digest: str, inputs_digest: str) -> tuple[dict, list[dict]]:
    if not path.is_file():
        raise TransportStop(f"系統{expected_lane} の結果ファイルが無い")
    data = _read_json(path, f"系統{expected_lane}")
    if not isinstance(data, dict):
        raise TransportStop(f"系統{expected_lane} がオブジェクトではない")
    if data.get("schema") != LANE_SCHEMA:
        raise TransportStop(f"系統{expected_lane} の schema が {LANE_SCHEMA} ではない")
    provider = str(data.get("provider", "")).strip().lower()
    model = str(data.get("model", "")).strip().lower()
    if provider not in ALLOWED_PROVIDERS or any(token in provider or token in model for token in BANNED_MODELS):
        raise TransportStop("Claude のモデル名や Workflow 名は Grok の実行結果として受け付けない")
    if data.get("lane") != expected_lane or data.get("kind") != kind or data.get("batch") != batch:
        raise TransportStop(f"系統{expected_lane} の lane、kind、batch が pack と違う")
    if data.get("input_sha256") != digest or str(data.get("inputs_sha256", "")) != inputs_digest:
        raise TransportStop("入力 hash が snapshot と違う")
    session = str(data.get("session_id", "")).strip()
    if not session:
        raise TransportStop("session_id が無い")
    labels = data.get("labels")
    if not isinstance(labels, list):
        raise TransportStop(f"系統{expected_lane} の labels が配列ではない")
    return {"provider": provider, "session_id": session}, labels


def _decision(kind: str, row: dict) -> tuple[str, ...] | None:
    if kind == "field":
        value = row.get("field")
        return (value,) if value in FIELD_VALUES else None
    if kind == "tiebreak":
        kind_value, field = row.get("kind"), row.get("field")
        if kind_value in TIEBREAK_KINDS and field in TIEBREAK_FIELDS:
            return (kind_value, field)
        return None
    pick = row.get("pick")
    return (pick,) if pick in LINE_PICKS else None


def _index(kind: str, labels: list, expected: list[str]) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for row in labels:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise TransportStop("labels の行に id が無い")
        if row["id"] in rows:
            raise TransportStop("同じ id が1系統に2回ある")
        rows[row["id"]] = row
    if len(rows) != len(expected) or set(rows) != set(expected):
        raise TransportStop("件数が snapshot と違う")
    return rows


def _candidate_row(kind: str, row_id: str, decision: tuple[str, ...], reason: str) -> dict[str, str]:
    if kind == "field":
        return {"id": row_id, "field": decision[0], "how": "一致", "reason": reason}
    if kind == "tiebreak":
        return {"id": row_id, "種類": decision[0], "分野": decision[1], "決め方": "一致", "理由": reason}
    return {"id": row_id, "採用": decision[0], "決め方": "一致", "理由": reason}


def _reason(left: dict, right: dict) -> str | None:
    a = str(left.get("reason", "")).strip()
    b = str(right.get("reason", "")).strip()
    if not a or not b:
        return None
    return a if a == b else f"系統A: {a}／系統B: {b}"


def _current_entry(work: Path, kind: str, batch: str) -> dict:
    """manifest の batch と、今の snapshot、source、lines の inputs が同じバイトか確かめる。"""
    entry = _manifest_entry(work, kind, batch)
    snapshot = _inside(work, str(entry["snapshot"]))
    source = _inside(work, str(entry["source"]))
    digest = str(entry["input_sha256"])
    if not snapshot.is_file() or sha256_bytes(snapshot.read_bytes()) != digest:
        raise TransportStop("snapshot が manifest の hash と違う")
    if not source.is_file() or sha256_bytes(source.read_bytes()) != digest:
        raise TransportStop("入力が pack の後に変わっている")
    inputs_digest = str(entry.get("inputs_sha256", ""))
    if kind == "lines":
        inputs = work / "lines" / "inputs.json"
        if not inputs.is_file() or sha256_bytes(inputs.read_bytes()) != inputs_digest:
            raise TransportStop("lines/inputs.json が pack の後に変わっている")
    elif inputs_digest != "":
        raise TransportStop("lines 以外の inputs hash が空ではない")
    return entry


def verify_lanes(work: Path, kind: str, batch: str, lane_a: Path, lane_b: Path, candidate: Path) -> dict[str, object]:
    report_path = work / "transport" / "reports" / f"{kind}-{batch}.json"
    try:
        if lane_a.resolve() == lane_b.resolve():
            raise TransportStop("2系統が同じファイルである")
        entry = _current_entry(work, kind, batch)
        digest = str(entry["input_sha256"])
        inputs_digest = str(entry.get("inputs_sha256", ""))
        meta_a, labels_a = _lane_file(lane_a, "a", kind, batch, digest, inputs_digest)
        meta_b, labels_b = _lane_file(lane_b, "b", kind, batch, digest, inputs_digest)
        if meta_a["session_id"] == meta_b["session_id"]:
            raise TransportStop("同じ session を2系統に使っている")
        expected = list(entry["ids"])
        index_a = _index(kind, labels_a, expected)
        index_b = _index(kind, labels_b, expected)
        agreed: list[dict[str, str]] = []
        held: list[dict[str, str]] = []
        for row_id in expected:
            left, right = index_a[row_id], index_b[row_id]
            decision_a, decision_b = _decision(kind, left), _decision(kind, right)
            reason = _reason(left, right)
            if decision_a is None or decision_b is None:
                held.append({"id": row_id, "hold": "候補外"})
            elif decision_a != decision_b:
                held.append({"id": row_id, "hold": "不一致", "a": "|".join(decision_a), "b": "|".join(decision_b)})
            elif reason is None:
                held.append({"id": row_id, "hold": "根拠なし"})
            else:
                agreed.append(_candidate_row(kind, row_id, decision_a, reason))
        _write_json(candidate, {
            "schema": "eval-candidate-v1",
            "kind": kind,
            "batch": batch,
            "input_sha256": digest,
            "inputs_sha256": inputs_digest,
            "labels": agreed,
        })
        report: dict[str, object] = {
            "status": "candidate",
            "reason": "",
            "agreed": len(agreed),
            "held": held,
            "candidate_written": True,
            "execution": "fake" if "fake" in (meta_a["provider"], meta_b["provider"]) else "declared-grok",
            "live_session_verified": False,
            "launched": False,
        }
    except (TransportStop, OSError) as stop:
        if candidate.exists():
            candidate.unlink()
        report = {
            "status": "stopped",
            "reason": stop.reason if isinstance(stop, TransportStop) else "snapshot または結果ファイルが読めない",
            "agreed": 0,
            "held": [],
            "candidate_written": False,
            "execution": "not-run",
            "live_session_verified": False,
            "launched": False,
        }
    _write_json(report_path, report)
    return report


def apply_candidates(kind: str, candidate: Path, dest: Path | None = None, inputs: Path | None = None,
                     work: Path | None = None, batch: str | None = None) -> int:
    """hash が pack のままの候補だけを、既存の apply_field / apply_tiebreak / apply_lines へ渡す。Workflow の result を併記した候補は書かない。"""
    if work is None or not batch:
        raise TransportStop("apply には作業フォルダと batch が要る")
    if kind not in KINDS:
        raise TransportStop("kind が対象外")
    entry = _current_entry(work, kind, batch)
    payload = _read_json(candidate, "候補")
    if not isinstance(payload, dict):
        raise TransportStop("候補がオブジェクトではない")
    if payload.get("kind") != kind or payload.get("batch") != batch:
        raise TransportStop("候補の kind または batch が指定と違う")
    if payload.get("input_sha256") != entry["input_sha256"] or str(payload.get("inputs_sha256", "")) != str(entry.get("inputs_sha256", "")):
        raise TransportStop("候補の入力 hash が manifest と違う")
    if "result" in payload:
        raise TransportStop("候補に Workflow の result がある")
    try:
        labels = _labels(candidate)
    except (KeyError, TypeError) as error:
        raise TransportStop("候補の labels が配列ではない") from error
    if not isinstance(labels, list):
        raise TransportStop("候補の labels が配列ではない")
    key = AGREEMENT_KEY[kind]
    if any(not isinstance(row, dict) or row.get(key) != "一致" for row in labels):
        raise TransportStop("候補に、2系統の一致以外の行がある")
    if kind == "field":
        return apply_field(candidate, dest)
    if kind == "tiebreak":
        return apply_tiebreak(candidate, dest)
    canonical = (work / "lines" / "inputs.json").resolve()
    if inputs is not None and inputs.resolve() != canonical:
        raise TransportStop("系統の決着の inputs が作業フォルダの lines/inputs.json ではない")
    try:
        # verify-lanes が2系統を確かめ、上で hash が manifest のままと確かめた候補なので、一致を採用してよい
        return apply_lines(candidate, work / "lines" / "inputs.json", dest, agreement_verified=True)
    except LineStop as error:
        # python -m は入口を __main__ としても読み、こちらが import する scripts.eval_loop とは別物になる。
        # 入口の except が比較するのは、このモジュールが上げる TransportStop だけが一致する。
        raise TransportStop(error.reason) from error
