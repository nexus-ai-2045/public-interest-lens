from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Callable

try:
    from .register_external_material import register_local_material
    from .official_raw import capture_url, readback
except ImportError:
    from register_external_material import register_local_material
    from official_raw import capture_url, readback

BASE_URL = "https://kokkai.ndl.go.jp/api"
ENDPOINT_RECORD_KEYS = {
    "meeting_list": "meetingRecord",
    "meeting": "meetingRecord",
    "speech": "speechRecord",
}


def _write_json(path: Path, value: dict) -> bytes:
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return payload


def _default_fetch_json(url: str) -> dict:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise ValueError("redirect rejected")

    request = urllib.request.Request(
        url, headers={"User-Agent": "public-interest-lens/0.1"}
    )
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        payload = response.read(20 * 1024 * 1024 + 1)
    if len(payload) > 20 * 1024 * 1024:
        raise ValueError("response too large")
    return json.loads(payload)


def _build_url(
    endpoint: str,
    session_from: int,
    session_to: int,
    start: int,
    maximum: int,
    date_from: str | None = None,
    date_to: str | None = None,
    house: str | None = None,
) -> str:
    query = {
        "sessionFrom": session_from,
        "sessionTo": session_to,
        "startRecord": start,
        "maximumRecords": maximum,
        "recordPacking": "json",
    }
    if date_from is not None:
        query.update(from_=date_from, until=date_to)
        query["from"] = query.pop("from_")
    if house is not None:
        query["nameOfHouse"] = house
    params = urllib.parse.urlencode(query)
    return f"{BASE_URL}/{endpoint}?{params}"


def _validate_page(data, endpoint, start, maximum, reported, seen):
    records = data.get(ENDPOINT_RECORD_KEYS[endpoint])
    total = data.get("numberOfRecords")
    next_record = data.get("nextRecordPosition")
    if (
        type(total) is not int
        or total < 0
        or not isinstance(records, list)
        or (reported is not None and total != reported)
        or type(data.get("startRecord")) is not int
        or data["startRecord"] != start
        or type(data.get("numberOfReturn")) is not int
        or data["numberOfReturn"] != len(records)
        or len(records) > maximum
        or start - 1 + len(records) > total
    ):
        raise ValueError("inconsistent page metadata")
    ids = [
        (
            item.get("speechID" if endpoint == "speech" else "issueID")
            if isinstance(item, dict)
            else None
        )
        for item in records
    ]
    if (
        any(not isinstance(item, str) or not item.strip() for item in ids)
        or len(ids) != len(set(ids))
        or seen.intersection(ids)
    ):
        raise ValueError("invalid or duplicate identifier")
    complete = start - 1 + len(records) == total
    if (complete and next_record is not None) or (
        not complete
        and (
            not records
            or type(next_record) is not int
            or next_record != start + len(records)
        )
    ):
        raise ValueError("invalid pagination")
    return records, total, ids, complete


def _valid_observation(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ValueError("registered observation time is invalid") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("registered observation time must include timezone")
    return value


def _readable_body_count(endpoint: str, records: list[dict]) -> int:
    if endpoint == "meeting_list":
        return 0
    if endpoint == "meeting":
        records = [
            {
                **speech,
                "date": speech.get("date") or meeting.get("date"),
                "imageKind": speech.get("imageKind") or meeting.get("imageKind"),
            }
            for meeting in records
            if isinstance(meeting, dict)
            for speech in meeting.get("speechRecord", [])
            if isinstance(speech, dict)
        ]
    count = 0
    for record in records:
        if (
            not isinstance(record, dict)
            or record.get("imageKind") != "会議録"
            or not isinstance(record.get("speech"), str)
            or not record["speech"].strip()
        ):
            continue
        event_date = record.get("date")
        try:
            if not isinstance(event_date, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", event_date
            ):
                continue
            date.fromisoformat(event_date)
        except ValueError:
            continue
        count += 1
    return count


def _verified_material(
    record_path: Path,
    *,
    roots: tuple[Path, ...],
    url: str,
    digest: str,
    expected_bytes: int,
) -> dict:
    resolved = record_path.resolve(strict=True)
    if not any(resolved.is_relative_to(root.resolve()) for root in roots):
        raise ValueError("registered material path escapes storage root")
    record = json.loads(resolved.read_text(encoding="utf-8"))
    name = record.get("saved_filename")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise ValueError("registered original name invalid")
    original = (resolved.parent / name).resolve(strict=True)
    if original.parent != resolved.parent:
        raise ValueError("registered original escapes storage root")
    payload = original.read_bytes()
    if (
        record.get("schema_version") != "external-material/v1"
        or record.get("source_url") != url
        or record.get("sha256") != digest
        or record.get("bytes") != expected_bytes
        or len(payload) != expected_bytes
        or hashlib.sha256(payload).hexdigest() != digest
    ):
        raise ValueError("registered material metadata mismatch")
    _valid_observation(record.get("observed_at"))
    return record


def _register_page(page_path, url, start, output_dir, material_root, observed_at):
    digest = hashlib.sha256(page_path.read_bytes()).hexdigest()
    storage = material_root
    roots = (storage, output_dir / "external-materials")
    for root in roots:
        for record_path in sorted(root.glob(f"page-{start}*/*/record.json")):
            try:
                record = _verified_material(
                    record_path,
                    roots=roots,
                    url=url,
                    digest=digest,
                    expected_bytes=page_path.stat().st_size,
                )
                if record.get("content_verification") == "unverified":
                    return record_path, record["observed_at"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
    task_id = f"page-{start}"
    attempt = 0
    while (storage / task_id).exists():
        attempt += 1
        task_id = f"page-{start}-retry-{attempt}"
    record_path = register_local_material(
        input_path=page_path,
        source_url=url,
        task_id=task_id,
        title="国会会議録API取得ページ",
        purpose="未確認資料の来歴保存",
        storage_root=storage,
        observed_at=observed_at,
    )
    return record_path, observed_at


def _registered_observation(page, output_dir, material_root=None):
    record_path = Path(page.get("record_path", ""))
    if not record_path.is_absolute():
        record_path = Path(__file__).resolve().parents[1] / record_path
    page_path = output_dir / "pages" / f"{page['start_record']:09d}.json"
    record = _verified_material(
        record_path,
        roots=(
            material_root or output_dir / "external-materials",
            output_dir / "external-materials",
        ),
        url=page["source_url"],
        digest=page["sha256"],
        expected_bytes=page_path.stat().st_size,
    )
    if page.get("observed_at") and page["observed_at"] != record["observed_at"]:
        raise ValueError("checkpoint observation mismatch")
    return record["observed_at"]


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
    date_from: str | None = None,
    date_to: str | None = None,
    house: str | None = None,
    material_root: Path | None = None,
    fetch_raw: Callable[[str], dict] | None = None,
    expected_records: int | None = None,
) -> dict:
    if endpoint not in ENDPOINT_RECORD_KEYS:
        raise ValueError(f"unsupported endpoint: {endpoint}")
    if expected_records is not None and (
        type(expected_records) is not int or expected_records < 0
    ):
        raise ValueError("expected inventory count must be a nonnegative integer")
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
    if (date_from is None) != (date_to is None):
        raise ValueError("date_from and date_to must be supplied together")
    if date_from is not None:
        for value in (date_from, date_to):
            if not isinstance(value, str) or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}", value
            ):
                raise ValueError("dates must be YYYY-MM-DD")
            date.fromisoformat(value)
        if date_from > date_to:
            raise ValueError("date range is reversed")
    if house not in (None, "衆議院", "参議院", "両院", "両院協議会"):
        raise ValueError("unsupported house")
    repo_local = Path(__file__).resolve().parents[1] / ".local"
    legacy_inline_storage = (
        material_root is None
        and not output_dir.resolve().is_relative_to(repo_local.resolve())
    )
    material_root = material_root or (
        output_dir / "external-materials"
        if legacy_inline_storage
        else repo_local / "external-materials"
    )
    if not legacy_inline_storage and (
        material_root.resolve() == output_dir.resolve()
        or material_root.resolve().is_relative_to(output_dir.resolve())
    ):
        raise ValueError("material root must be separate from output directory")

    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "checkpoint.json"
    manifest_path = output_dir / "manifest.json"
    checkpoint = (
        json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint_path.exists()
        else {}
    )
    if (
        checkpoint
        and expected_records is not None
        and checkpoint.get("records_reported") != expected_records
    ):
        raise ValueError("checkpoint total differs from frozen inventory")
    scope = {
        "endpoint": endpoint,
        "session_from": session_from,
        "session_to": session_to,
        "date_from": date_from,
        "date_to": date_to,
        "house": house,
    }
    if checkpoint and any(checkpoint.get(key) != value for key, value in scope.items()):
        raise ValueError("checkpoint scope mismatch; use a separate output directory")
    seen = set()
    expected_start = 1
    last_complete = False
    for previous in checkpoint.get("pages", []):
        if last_complete or previous.get("start_record") != expected_start:
            raise ValueError("checkpoint page sequence mismatch")
        if previous.get("source_url") != _build_url(
            endpoint,
            session_from,
            session_to,
            expected_start,
            maximum_records,
            date_from,
            date_to,
            house,
        ):
            raise ValueError("checkpoint source URL differs from fixed query")
        payload = (
            output_dir / "pages" / f"{previous['start_record']:09d}.json"
        ).read_bytes()
        if hashlib.sha256(payload).hexdigest() != previous["sha256"]:
            raise ValueError("checkpoint page hash mismatch")
        records, _, ids, last_complete = _validate_page(
            json.loads(payload),
            endpoint,
            expected_start,
            limit,
            checkpoint.get("records_reported"),
            seen,
        )
        if previous.get("record_count") != len(records):
            raise ValueError("checkpoint page count mismatch")
        _registered_observation(previous, output_dir, material_root)
        seen.update(ids)
        expected_start += len(records)
    if checkpoint and (
        checkpoint.get("schema_version") != "diet-api-checkpoint/v2"
        or checkpoint.get("records_saved") != len(seen)
    ):
        raise ValueError(
            "checkpoint requires validated v2 migration; use a new directory"
        )
    if checkpoint and (
        not checkpoint.get("pages")
        or checkpoint.get("complete") is not last_complete
        or checkpoint.get("next_record") != (None if last_complete else expected_start)
    ):
        raise ValueError("checkpoint cursor mismatch")

    if checkpoint.get("complete") and manifest_path.exists():
        existing_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_observation = checkpoint.get(
            "completed_at"
        ) or _registered_observation(checkpoint["pages"][-1], output_dir, material_root)
        if (
            existing_manifest.get("status") != "query_exhausted"
            or existing_manifest.get("complete") is not True
            or existing_manifest.get("observed_at") != expected_observation
            or existing_manifest.get("pages") != checkpoint["pages"]
            or existing_manifest.get("records_saved") != checkpoint["records_saved"]
        ):
            raise ValueError("complete manifest conflicts with checkpoint observation")
        readable = sum(
            _readable_body_count(
                endpoint,
                json.loads(
                    (
                        output_dir / "pages" / f"{entry['start_record']:09d}.json"
                    ).read_text(encoding="utf-8")
                )[ENDPOINT_RECORD_KEYS[endpoint]],
            )
            for entry in checkpoint["pages"]
        )
        if existing_manifest.get("readable_body_count", readable) != readable:
            raise ValueError("complete manifest readable count mismatch")
        existing_manifest.setdefault("readable_body_count", readable)
        existing_manifest.setdefault("confirmed_action_evidence_count", 0)
        return existing_manifest

    start = int(checkpoint.get("next_record") or 1)
    pages = list(checkpoint.get("pages", []))
    saved = int(checkpoint.get("records_saved", 0))
    reported = checkpoint.get("records_reported", expected_records)
    pages_this_run = 0

    failure = None
    while not checkpoint.get("complete") and (
        max_pages is None or pages_this_run < max_pages
    ):
        url = _build_url(
            endpoint,
            session_from,
            session_to,
            start,
            maximum_records,
            date_from,
            date_to,
            house,
        )
        try:
            use_raw = fetch_raw is not None or fetch_json is _default_fetch_json
            if pages and not use_raw:
                sleep(delay_seconds)
            if use_raw:
                raw_receipt = (
                    fetch_raw(url)
                    if fetch_raw is not None
                    else capture_url(
                        url,
                        material_root=material_root,
                        control_root=material_root.parent / "full-acquisition",
                        task_id=f"ndl-{hashlib.sha256((str(output_dir.resolve()) + '|' + url).encode()).hexdigest()[:24]}",
                        title="国会会議録API原レスポンス",
                        allowed_hosts={"kokkai.ndl.go.jp"},
                        delay_seconds=delay_seconds,
                    )
                )
                raw_payload = readback(raw_receipt, material_root)
                if raw_receipt["url"] != url or raw_receipt["status"] != 200:
                    raise ValueError(
                        "NDL raw HTTP response was not 200; receipt preserved"
                    )
                data = json.loads(raw_payload)
                observed_at = raw_receipt["observed_at"]
            else:
                data = fetch_json(url)
                observed_at = datetime.now().astimezone().isoformat(timespec="seconds")
            if (
                expected_records is not None
                and data.get("numberOfRecords") != expected_records
            ):
                raise ValueError("response total differs from frozen inventory")
            records, total, ids, complete = _validate_page(
                data, endpoint, start, maximum_records, reported, seen
            )
            page_path = output_dir / "pages" / f"{start:09d}.json"
            if page_path.exists() and (
                page_path.read_bytes() != raw_payload
                if use_raw
                else json.loads(page_path.read_text(encoding="utf-8")) != data
            ):
                raise ValueError(
                    "uncommitted page changed; preserve and use new output directory"
                )
            if use_raw:
                page_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = page_path.with_suffix(".json.tmp")
                temporary.write_bytes(raw_payload)
                temporary.replace(page_path)
                page_payload = raw_payload
                record_path = Path(raw_receipt["record_path"])
            else:
                page_payload = _write_json(page_path, data)
                record_path, observed_at = _register_page(
                    page_path, url, start, output_dir, material_root, observed_at
                )
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
            "observed_at": observed_at,
            "representation": (
                "http-response-body-bytes" if use_raw else "parsed-json-reserialized"
            ),
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
            "date_from": date_from,
            "date_to": date_to,
            "house": house,
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

    observed_at = checkpoint.get("completed_at") or (
        _registered_observation(checkpoint["pages"][-1], output_dir, material_root)
        if checkpoint.get("pages")
        else datetime.now().astimezone().isoformat(timespec="seconds")
    )
    manifest = {
        **checkpoint,
        "schema_version": "diet-api-manifest/v1",
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "recorded_by": "codex",
        "observed_at": observed_at,
        "scope": f"NDL Diet Minutes API {endpoint}, sessions {session_from}-{session_to}",
        "status": (
            "failed"
            if failure
            else ("query_exhausted" if checkpoint.get("complete") else "capped")
        ),
        "complete": bool(checkpoint.get("complete")) and failure is None,
        "corpus_complete": False,
        "content_verification": "unverified",
        "error_type": failure,
        "records_saved": saved,
        "readable_body_count": sum(
            _readable_body_count(
                endpoint,
                json.loads(
                    (
                        output_dir / "pages" / f"{entry['start_record']:09d}.json"
                    ).read_text(encoding="utf-8")
                )[ENDPOINT_RECORD_KEYS[endpoint]],
            )
            for entry in pages
        ),
        "confirmed_action_evidence_count": 0,
        "raw_response_pages": sum(
            p.get("representation") == "http-response-body-bytes" for p in pages
        ),
        "derived_response_pages": sum(
            p.get("representation") != "http-response-body-bytes" for p in pages
        ),
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
    parser.add_argument("--date-from")
    parser.add_argument("--date-to")
    parser.add_argument("--house", choices=["衆議院", "参議院", "両院", "両院協議会"])
    parser.add_argument("--material-root", type=Path)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--max-pages", type=int)
    group.add_argument("--all-pages", action="store_true")
    args = parser.parse_args()
    resolved_output = args.output_dir.resolve()
    expected_local = Path(__file__).resolve().parents[1] / ".local"
    if args.material_root is not None:
        root = args.material_root.resolve()
        if (
            root.name != "external-materials"
            or root.parent.name != ".local"
            or args.material_root.is_symlink()
        ):
            parser.error(
                "--material-root は既存repoの .local/external-materials にしてください"
            )
        expected_local = root.parent
    diet_root = expected_local / "diet"
    if (
        not resolved_output.is_relative_to(diet_root.resolve())
        or resolved_output == diet_root.resolve()
        or args.output_dir.absolute() != resolved_output
    ):
        parser.error(
            "--output-dir はmaterial rootと同じrepoの .local/diet/<bounded-shard> にしてください"
        )
    result = collect_pages(
        endpoint=args.endpoint,
        session_from=args.session_from,
        session_to=args.session_to,
        output_dir=args.output_dir,
        maximum_records=args.maximum_records,
        delay_seconds=args.delay_seconds,
        max_pages=args.max_pages,
        all_pages=args.all_pages,
        date_from=args.date_from,
        date_to=args.date_to,
        house=args.house,
        material_root=args.material_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
