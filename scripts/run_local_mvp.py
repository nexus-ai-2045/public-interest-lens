"""国会会議録の限定取得を検査し、保留理由付きローカル表示データを作る。"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import date, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .fetch_diet_minutes import _default_fetch_json, collect_pages
from .sangiin_bills import fetch_bill_pages

SCHEMA_VERSION = "ranking-dataset/v1"
SOURCE_HOST = "kokkai.ndl.go.jp"


def _fetch_with_retries(url: str, fetch: Callable[[str], dict],
                        sleep: Callable[[float], None]) -> dict:
    """通信失敗だけ最大3回試し、ページの矛盾やリダイレクトは再試行しない。"""
    for attempt in range(3):
        try:
            return fetch(url)
        except OSError:
            if attempt == 2:
                raise
            sleep(3.0)
    raise AssertionError("unreachable")


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def _official_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname == SOURCE_HOST


def _read_verified_speeches(source_dir: Path) -> tuple[list[dict], dict]:
    manifest = _read_json(source_dir / "manifest.json")
    if manifest.get("schema_version") != "diet-api-manifest/v1" or manifest.get("endpoint") != "speech":
        raise ValueError("speech manifest required")
    if manifest.get("status") not in {"capped", "query_exhausted"}:
        raise ValueError("source run did not succeed")
    pages = manifest.get("pages")
    if not isinstance(pages, list) or not pages:
        raise ValueError("source pages missing")
    speeches: list[dict] = []
    ids: set[str] = set()
    next_start = 1
    for entry in pages:
        start = entry.get("start_record")
        if type(start) is not int or start != next_start:
            raise ValueError("source page sequence mismatch")
        path = source_dir / "pages" / f"{start:09d}.json"
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != entry.get("sha256"):
            raise ValueError("source page hash mismatch")
        if not _official_url(entry.get("source_url", "")):
            raise ValueError("source URL is not official")
        record_value = entry.get("record_path")
        if not isinstance(record_value, str) or not record_value:
            raise ValueError("registered source record missing")
        record_path = Path(record_value)
        if not record_path.is_absolute():
            record_path = Path(__file__).resolve().parents[1] / record_path
        record_path = record_path.resolve(strict=True)
        if not record_path.is_relative_to((source_dir / "external-materials").resolve()):
            raise ValueError("registered source path escapes run")
        record = _read_json(record_path)
        filename = record.get("saved_filename")
        if (record.get("schema_version") != "external-material/v1"
                or record.get("source_url") != entry["source_url"]
                or record.get("sha256") != entry["sha256"]
                or not isinstance(filename, str)):
            raise ValueError("registered source metadata mismatch")
        original = (record_path.parent / filename).resolve(strict=True)
        if original.parent != record_path.parent or hashlib.sha256(original.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("registered original hash mismatch")
        page = json.loads(payload)
        records = page.get("speechRecord")
        if (not isinstance(records, list) or page.get("startRecord") != start
                or page.get("numberOfReturn") != len(records)
                or entry.get("record_count") != len(records)):
            raise ValueError("source page metadata mismatch")
        for record in records:
            if not isinstance(record, dict) or not isinstance(record.get("speechID"), str):
                raise ValueError("invalid speech record")
            if record["speechID"] in ids:
                raise ValueError("duplicate speech identifier")
            ids.add(record["speechID"])
            speeches.append(record)
        next_start += len(records)
    if manifest.get("records_saved") != len(speeches):
        raise ValueError("source manifest count mismatch")
    return speeches, manifest


def build_dataset(source_dir: Path, *, as_of: str, candidate_pack: Path | None = None) -> dict:
    """未確認の発言を政策行動や影響に昇格させずに表示データ化する。"""
    cutoff_date = date.fromisoformat(as_of)
    try:
        recent_start = cutoff_date.replace(year=cutoff_date.year - 4)
    except ValueError:
        recent_start = cutoff_date.replace(year=cutoff_date.year - 4, day=28)
    speeches, manifest = _read_verified_speeches(source_dir)
    speech_by_id = {item["speechID"]: item for item in speeches}
    held: list[dict] = []
    candidates = []
    if candidate_pack is not None:
        pack = _read_json(candidate_pack)
        candidates = pack.get("policies")
        if not isinstance(candidates, list) or len(candidates) > 1000:
            raise ValueError("candidate pack must be a bounded list")
        candidate_ids: set[str] = set()
        for candidate in candidates:
            if not isinstance(candidate, dict) or not isinstance(candidate.get("id"), str):
                raise ValueError("invalid candidate")
            if candidate["id"] in candidate_ids:
                raise ValueError("duplicate policy candidate")
            candidate_ids.add(candidate["id"])
            date.fromisoformat(candidate["action_date"])
        candidates = sorted(candidates, key=lambda item: (item["action_date"], item["id"]),
                            reverse=True)
        recent = [item for item in candidates if recent_start <= date.fromisoformat(
            item["action_date"]) <= cutoff_date]
        selected_ids = {item["id"] for item in recent[:3]}
        selected_count = len(selected_ids)
        for candidate in candidates:
            if candidate["id"] not in selected_ids:
                reason = ("outside_recent_four_years" if not recent_start <= date.fromisoformat(
                    candidate["action_date"]) <= cutoff_date else "outside_mvp_limit")
                held.append({"id": candidate["id"], "reason": reason,
                             "sourceSpeechId": candidate.get("source_speech_id")})
                continue
            speech = speech_by_id.get(candidate.get("source_speech_id"))
            quote = candidate.get("quote")
            reason = ("source_speech_missing" if speech is None else
                      "quote_mismatch" if not isinstance(quote, str) or not quote.strip()
                      or quote not in (speech.get("speech") or "") else
                      "bill_action_and_impact_unverified")
            held.append({"id": candidate["id"], "reason": reason,
                         "sourceSpeechId": candidate.get("source_speech_id")})
    else:
        held = [{"id": item["speechID"], "reason": "speech_is_not_action_or_impact",
                 "sourceSpeechId": item["speechID"],
                 **({"sourceUrl": item["speechURL"]} if _official_url(
                     item.get("speechURL", "")) else {})} for item in speeches]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "fictional": False,
        "asOf": as_of,
        "coverage": {
            "scope": manifest.get("scope", "NDL speech query"),
            "assessedPeople": 0,
            "targetPeople": None,
            "sourceStatus": manifest["status"],
            "sourceRecords": len(speeches),
            "assessedPolicies": 0,
            "candidatePolicies": selected_count if candidate_pack is not None else 0,
        },
        "people": [], "policies": [], "involvements": [], "evidence": [],
        "held": held,
    }


def run_local_mvp(source_dir: Path | None, output_dir: Path, *, as_of: str,
                  candidate_pack: Path | None = None,
                  bill_urls: list[str] | None = None) -> dict:
    """成功版だけ切り替え、失敗時は current.json を維持する。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    try:
        if bill_urls:
            dataset = fetch_bill_pages(bill_urls, output_dir, as_of=as_of)
        else:
            if source_dir is None:
                raise ValueError("source directory missing")
            dataset = build_dataset(source_dir, as_of=as_of, candidate_pack=candidate_pack)
        _atomic_json(output_dir / "current.json", dataset)
        result = {"schema_version": "local-mvp-run/v1", "status": "ready",
                  "recorded_at": now, "recorded_by": "codex", "as_of": as_of,
                  "assessed_people": dataset["coverage"]["assessedPeople"],
                  "held_count": len(dataset["held"]),
                  "source_status": dataset["coverage"]["sourceStatus"]}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        result = {"schema_version": "local-mvp-run/v1", "status": "failed",
                  "recorded_at": now, "recorded_by": "codex", "as_of": as_of,
                  "source_status": "failed", "error_type": type(error).__name__, "last_good_preserved":
                  (output_dir / "current.json").is_file()}
    _atomic_json(output_dir / "run-manifest.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path)
    parser.add_argument("--bill-url", action="append", default=[])
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--as-of", default=date.today().isoformat())
    parser.add_argument("--candidate-pack", type=Path)
    parser.add_argument("--session-from", type=int)
    parser.add_argument("--session-to", type=int)
    parser.add_argument("--max-pages", type=int)
    args = parser.parse_args()
    local_root = Path(__file__).resolve().parents[1] / ".local"
    if not args.output_dir.resolve().is_relative_to(local_root.resolve()):
        parser.error("--output-dir must be inside this repository's .local/")
    if args.bill_url:
        if args.source_dir is not None or args.session_from is not None or args.candidate_pack is not None:
            parser.error("--bill-url cannot be combined with NDL source inputs")
        result = run_local_mvp(None, args.output_dir, as_of=args.as_of,
                               bill_urls=args.bill_url)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result["status"] == "ready" else 1
    if args.source_dir is None:
        if args.session_from is None or args.session_to is None or args.max_pages is None:
            parser.error("set --source-dir or bounded --session-from/--session-to/--max-pages")
        source_dir = args.output_dir / "source"
        try:
            source_manifest = collect_pages(
                endpoint="speech", session_from=args.session_from, session_to=args.session_to,
                output_dir=source_dir, maximum_records=100, delay_seconds=3.0,
                max_pages=args.max_pages,
                fetch_json=lambda url: _fetch_with_retries(url, _default_fetch_json, time.sleep))
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            source_manifest = {"status": "failed", "error_type": type(error).__name__}
        if source_manifest["status"] == "failed":
            result = {
                "schema_version": "local-mvp-run/v1", "status": "failed",
                "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "recorded_by": "codex", "as_of": args.as_of,
                "source_status": "failed", "error_type": source_manifest.get("error_type"),
                "last_good_preserved": (args.output_dir / "current.json").is_file(),
            }
            _atomic_json(args.output_dir / "run-manifest.json", result)
            print(json.dumps(result, ensure_ascii=False))
            return 1
    else:
        source_dir = args.source_dir
    result = run_local_mvp(source_dir, args.output_dir, as_of=args.as_of,
                           candidate_pack=args.candidate_pack)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
