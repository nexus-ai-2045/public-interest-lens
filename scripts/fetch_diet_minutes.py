"""国会会議録検索システムAPIを逐次・再開可能に保存する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Callable
try:
    from .register_external_material import register_local_material
except ImportError:
    from register_external_material import register_local_material

BASE_URL = "https://kokkai.ndl.go.jp/api"
ENDPOINT_RECORD_KEYS = {
    "meeting_list": "meetingRecord",
    "meeting": "meetingRecord",
    "speech": "speechRecord",
}


def _write_json(path: Path, value: dict) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return payload


def _default_fetch_json(url: str) -> dict:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("redirect rejected")

    request = urllib.request.Request(url, headers={"User-Agent": "public-interest-lens/0.1"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        payload = response.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError("response too large")
    return json.loads(payload)


def _build_url(endpoint: str, session_from: int, session_to: int, start: int, maximum: int) -> str:
    params = urllib.parse.urlencode(
        {
            "sessionFrom": session_from,
            "sessionTo": session_to,
            "startRecord": start,
            "maximumRecords": maximum,
            "recordPacking": "json",
        }
    )
    return f"{BASE_URL}/{endpoint}?{params}"


def _validate_page(data, endpoint, start, maximum, reported, seen):
    records = data.get(ENDPOINT_RECORD_KEYS[endpoint])
    total = data.get("numberOfRecords")
    next_record = data.get("nextRecordPosition")
    if (type(total) is not int or total < 0 or not isinstance(records, list)
            or (reported is not None and total != reported)
            or type(data.get("startRecord")) is not int or data["startRecord"] != start
            or type(data.get("numberOfReturn")) is not int
            or data["numberOfReturn"] != len(records)
            or len(records) > maximum or start - 1 + len(records) > total):
        raise ValueError("inconsistent page metadata")
    ids = [item.get("speechID" if endpoint == "speech" else "issueID")
           if isinstance(item, dict) else None for item in records]
    if (any(not isinstance(item, str) or not item.strip() for item in ids)
            or len(ids) != len(set(ids)) or seen.intersection(ids)):
        raise ValueError("invalid or duplicate identifier")
    complete = start - 1 + len(records) == total
    if ((complete and next_record is not None)
            or (not complete and (not records or type(next_record) is not int
                                  or next_record != start + len(records)))):
        raise ValueError("invalid pagination")
    return records, total, ids, complete


def _register_page(page_path, url, start, output_dir):
    """中断後も検証済みの同一登録を再利用し、部分登録は保全する。"""
    digest = hashlib.sha256(page_path.read_bytes()).hexdigest()
    storage = output_dir / "external-materials"
    for record_path in sorted(storage.glob(f"page-{start}*/*/record.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
            original = record_path.parent / record["saved_filename"]
            if (record.get("source_url") == url and record.get("sha256") == digest
                    and original.resolve().parent == record_path.parent.resolve()
                    and hashlib.sha256(original.read_bytes()).hexdigest() == digest
                    and record.get("content_verification") == "unverified"):
                return record_path
        except (OSError, ValueError, KeyError, TypeError):
            continue
    # 不完全な登録を上書きせず、別の登録単位へ再試行する。
    task_id = f"page-{start}"
    attempt = 0
    while (storage / task_id).exists():
        attempt += 1
        task_id = f"page-{start}-retry-{attempt}"
    return register_local_material(
        input_path=page_path, source_url=url, task_id=task_id,
        title="国会会議録API取得ページ", purpose="未確認資料の来歴保存",
        storage_root=storage)


def _registered_observation(page, output_dir):
    """取得時刻を証拠記録から復元し、checkpoint外のパスは読まない。"""
    value = page.get("observed_at")
    if not value:
        record_path = Path(page.get("record_path", ""))
        storage = (output_dir / "external-materials").resolve()
        resolved = record_path.resolve(strict=True)
        if not resolved.is_relative_to(storage):
            raise ValueError("checkpoint material path escapes storage root")
        record = json.loads(resolved.read_text(encoding="utf-8"))
        value = record.get("observed_at")
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError("registered observation time is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("registered observation time must include timezone")
    return value


def collect_pages(
    *,
    endpoint: str,
    session_from: int,
    session_to: int,
    output_dir: Path,
    maximum_records: int,
    delay_seconds: float,
    fetch_json: Callable[[str], dict] = _default_fetch_json,
    sleep: Callable[[float], None] = time.sleep,
    max_pages: int | None = None,
    all_pages: bool = False,
) -> dict:
    """ページを直列取得する。完了済みcheckpointはネットワークを呼ばない。"""
    if endpoint not in ENDPOINT_RECORD_KEYS:
        raise ValueError(f"unsupported endpoint: {endpoint}")
    limit = 10 if endpoint == "meeting" else 100
    if not 1 <= maximum_records <= limit:
        raise ValueError(f"maximum_records must be between 1 and {limit}")
    if session_from < 1 or session_to < session_from:
        raise ValueError("invalid session range")
    if not math.isfinite(delay_seconds) or delay_seconds < 3:
        raise ValueError("delay_seconds must be at least 3")
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be positive")
    if max_pages is None and not all_pages:
        raise ValueError("set max_pages or explicitly enable all_pages")

    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "checkpoint.json"
    manifest_path = output_dir / "manifest.json"
    checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8")) if checkpoint_path.exists() else {}
    scope = {"endpoint": endpoint, "session_from": session_from, "session_to": session_to}
    if checkpoint and any(checkpoint.get(key) != value for key, value in scope.items()):
        raise ValueError("checkpoint scope mismatch; use a separate output directory")
    seen = set()
    expected_start = 1
    last_complete = False
    for previous in checkpoint.get("pages", []):
        if last_complete or previous.get("start_record") != expected_start:
            raise ValueError("checkpoint page sequence mismatch")
        payload = (output_dir / "pages" / f"{previous['start_record']:09d}.json").read_bytes()
        if hashlib.sha256(payload).hexdigest() != previous["sha256"]:
            raise ValueError("checkpoint page hash mismatch")
        records, _, ids, last_complete = _validate_page(
            json.loads(payload), endpoint, expected_start, limit,
            checkpoint.get("records_reported"), seen)
        if previous.get("record_count") != len(records):
            raise ValueError("checkpoint page count mismatch")
        _registered_observation(previous, output_dir)
        seen.update(ids)
        expected_start += len(records)
    if checkpoint and (checkpoint.get("schema_version") != "diet-api-checkpoint/v2"
                       or checkpoint.get("records_saved") != len(seen)):
        raise ValueError("checkpoint requires validated v2 migration; use a new directory")
    if checkpoint and (not checkpoint.get("pages")
                       or checkpoint.get("complete") is not last_complete
                       or checkpoint.get("next_record") != (None if last_complete else expected_start)):
        raise ValueError("checkpoint cursor mismatch")

    if checkpoint.get("complete") and manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_observation = checkpoint.get("completed_at") or _registered_observation(
            checkpoint["pages"][-1], output_dir)
        if (existing_manifest.get("status") != "query_exhausted"
                or existing_manifest.get("complete") is not True
                or existing_manifest.get("observed_at") != expected_observation):
            raise ValueError("complete manifest conflicts with checkpoint observation")
        return existing_manifest

    start = int(checkpoint.get("next_record") or 1)
    pages = list(checkpoint.get("pages", []))
    saved = int(checkpoint.get("records_saved", 0))
    reported = checkpoint.get("records_reported")
    pages_this_run = 0

    failure = None
    while not checkpoint.get("complete") and (max_pages is None or pages_this_run < max_pages):
        url = _build_url(endpoint, session_from, session_to, start, maximum_records)
        try:
            if pages:
                sleep(delay_seconds)
            data = fetch_json(url)
            records, total, ids, complete = _validate_page(
                data, endpoint, start, maximum_records, reported, seen)
            page_path = output_dir / "pages" / f"{start:09d}.json"
            if page_path.exists() and json.loads(page_path.read_text(encoding="utf-8")) != data:
                raise ValueError("uncommitted page changed; preserve and use new output directory")
            page_payload = _write_json(page_path, data)
            record_path = _register_page(page_path, url, start, output_dir)
        except (OSError, ValueError, TypeError, AttributeError) as error:
            failure = type(error).__name__
            break
        reported = total
        seen.update(ids)
        page = {
            "start_record": start,
            "record_count": len(records),
            "sha256": hashlib.sha256(page_payload).hexdigest(),
            "source_url": url,
            "record_path": str(record_path),
            "observed_at": _registered_observation({"record_path": str(record_path)}, output_dir),
            "representation": "parsed-json-reserialized",
        }
        pages.append(page)
        saved += len(records)
        pages_this_run += 1
        next_record = data.get("nextRecordPosition")
        checkpoint = {
            "schema_version": "diet-api-checkpoint/v2",
            "endpoint": endpoint,
            "session_from": session_from,
            "session_to": session_to,
            "records_reported": reported,
            "records_saved": saved,
            "next_record": None if complete else int(next_record),
            "complete": complete,
            "completed_at": page["observed_at"] if complete else None,
            "pages": pages,
        }
        _write_json(checkpoint_path, checkpoint)
        if complete:
            break
        start = int(next_record)

    observed_at = (
        checkpoint.get("completed_at")
        or (_registered_observation(checkpoint["pages"][-1], output_dir)
            if checkpoint.get("pages") else datetime.now().astimezone().isoformat(timespec="seconds"))
    )
    manifest = {
        **checkpoint,
        "schema_version": "diet-api-manifest/v1",
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "recorded_by": "codex",
        "observed_at": observed_at,
        "scope": f"NDL Diet Minutes API {endpoint}, sessions {session_from}-{session_to}",
        "status": "failed" if failure else ("query_exhausted" if checkpoint.get("complete") else "capped"),
        "complete": bool(checkpoint.get("complete")) and failure is None,
        "corpus_complete": False,
        "content_verification": "unverified",
        "error_type": failure,
        "records_saved": saved,
    }
    _write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", choices=sorted(ENDPOINT_RECORD_KEYS))
    parser.add_argument("--session-from", type=int, required=True)
    parser.add_argument("--session-to", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--maximum-records", type=int, default=100)
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--max-pages", type=int)
    group.add_argument("--all-pages", action="store_true")
    args = parser.parse_args()
    local_root = Path(__file__).resolve().parents[1] / ".local"
    if not args.output_dir.resolve().is_relative_to(local_root.resolve()):
        parser.error("--output-dir はこのrepoの .local/ 配下にしてください")
    result = collect_pages(
        endpoint=args.endpoint,
        session_from=args.session_from,
        session_to=args.session_to,
        output_dir=args.output_dir,
        maximum_records=args.maximum_records,
        delay_seconds=args.delay_seconds,
        max_pages=args.max_pages,
        all_pages=args.all_pages,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
