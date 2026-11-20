"""公開ランキングの新しさ。入力と、出典チェックの結果と、中身を一つのハッシュに結ぶ。

mtime では、手で確かさを書き換えたファイルが入力より新しいと作り直されない。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.build_public_ranking import INPUTS

SOURCE_KEYS = ("heldOut", "mismatch", "match", "items", "notApplicable")


def hash_path(path: Path) -> Path:
    return Path(path).with_name(Path(path).name + ".publish-hash.json")


def body_digest(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def source_check_digest(summary: dict) -> str:
    picked = {key: summary[key] for key in SOURCE_KEYS}
    blob = json.dumps(picked, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def fingerprint(body: str, inputs: dict, source: str) -> str:
    material = {"body": body, "inputs": inputs, "sourceCheck": source}
    blob = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def record(payload: dict, summary: dict) -> dict:
    body = body_digest(payload)
    source = source_check_digest(summary)
    inputs = payload["generatedFrom"]["inputs"]
    return {"fingerprint": fingerprint(body, inputs, source), "body": body, "sourceCheck": source}


def current_input_hashes() -> dict[str, str] | None:
    hashes = {}
    for name, path in INPUTS.items():
        if not path.is_file():
            return None
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def ranking_is_fresh(path: Path) -> bool:
    """記録した公開ハッシュが、今の中身・入力・出典チェックの結果と一致するときだけ真。"""
    side = hash_path(path)
    if not path.is_file() or not side.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        recorded = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict) or not isinstance(recorded, dict):
        return False
    generated = payload.get("generatedFrom")
    inputs = generated.get("inputs") if isinstance(generated, dict) else None
    source = recorded.get("sourceCheck")
    if not isinstance(inputs, dict) or not isinstance(source, str):
        return False
    body = body_digest(payload)
    if body != recorded.get("body"):
        return False
    current = current_input_hashes()
    if current != inputs:
        return False
    return fingerprint(body, inputs, source) == recorded.get("fingerprint")
