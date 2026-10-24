#!/usr/bin/env python3
"""技術を止めた側の出典URLを、既存collectorの完全バイト保存へ渡す。

保存先は明示した .local/external-materials。/mnt/project-files と別の private-m2 へは書かない。
--out は旧 raw の読み取り専用。既存の URL と sha256 は上書きしない。

取得、ローカル抽出、照合は別関数。本文の保存も抽出文字も、文字数では切らない。
取得規則が未確認、またはツールが失敗している間は、本文へ通信しない。
明示的な禁止とは別の結果名にする。

使い方:
  python3 scripts/fetch_blocking_originals.py --material-root .local/external-materials
  python3 scripts/fetch_blocking_originals.py --material-root .local/external-materials --phase extract
  python3 scripts/fetch_blocking_originals.py --material-root .local/external-materials --phase verify

抽出は batches/<run-id>/text/ と、照合が読む batches/<run-id>/index.csv。
未完了の取得は終了コード 1。--limit で残った項目がある間は抽出へ進んだことにしない。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .collect_official_raw import collect_plan
    from .official_raw import atomic_json, readback
    from .path_guard import inside_without_links
    from .register_external_material import register_local_material, validate_task_id
except ImportError:
    from collect_official_raw import collect_plan
    from official_raw import atomic_json, readback
    from path_guard import inside_without_links
    from register_external_material import register_local_material, validate_task_id


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "acquired" / "blocking-actors"
RUN_ID = "blocking-originals"
INDEX_FIELDS = [
    "URL",
    "状態",
    "HTTP",
    "バイト",
    "sha256",
    "種類",
    "ページ数",
    "テキスト",
    "取得時刻",
]


def source_urls(data: Path = DATA) -> list[str]:
    urls = []
    for f in sorted(data.glob("*/*.csv")):
        with f.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                u = (r.get("出典URL") or "").strip()
                if u.startswith("http") and u not in urls:
                    urls.append(u)
    return urls


def key(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:16]


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"):
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(raw: bytes, content_type: str = "") -> str:
    m = re.search(rb"charset=[\"']?([\w-]+)", raw[:4000])
    h = re.search(r"charset=([\w-]+)", content_type)
    cs = m.group(1).decode() if m else (h.group(1) if h else "utf-8")
    if cs.lower() in ("shift_jis", "shift-jis", "sjis", "x-sjis"):
        cs = "cp932"
    for enc in (cs, "utf-8", "cp932", "euc-jp"):
        try:
            s = raw.decode(enc)
            break
        except (LookupError, UnicodeDecodeError):
            continue
    else:
        s = raw.decode("utf-8", "replace")
    p = _Text()
    p.feed(s)
    return re.sub(r"\n\s*\n+", "\n", "".join(p.out))


class ExtractStatus(OSError):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.extract_status = status


def pdf_text(path: Path) -> str:
    if shutil.which("pdftotext") is None:
        raise ExtractStatus(
            "unextracted", "pdftotext is unavailable; raw bytes were left unchanged"
        )
    try:
        completed = subprocess.run(
            ["pdftotext", "-enc", "UTF-8", str(path), "-"],
            capture_output=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as error:
        raise ExtractStatus(
            "failed", "pdftotext timed out; partial text was discarded"
        ) from error
    except FileNotFoundError as error:
        raise ExtractStatus(
            "unextracted", "pdftotext is unavailable; raw bytes were left unchanged"
        ) from error
    if completed.returncode != 0:
        raise ExtractStatus("failed", "pdftotext failed; partial text was discarded")
    return completed.stdout.decode("utf-8", "replace")


def _dedupe(urls: list[str]) -> list[str]:
    seen = []
    for url in urls:
        if url not in seen:
            seen.append(url)
    return seen


def _admitted(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 443)
        and not parsed.fragment
    )


def _roots(material_root: Path) -> tuple[Path, Path]:
    material_root = Path(material_root)
    if (
        material_root.is_symlink()
        or material_root.parent.is_symlink()
        or material_root.name != "external-materials"
        or material_root.parent.name != ".local"
    ):
        raise ValueError("material root must be private .local/external-materials")
    lexical_local = material_root.parent
    lexical_control = lexical_local / "full-acquisition"
    if lexical_control.is_symlink() or inside_without_links(lexical_local, lexical_control) is None:
        raise ValueError("full-acquisition escaped private root")
    material_root.mkdir(parents=True, exist_ok=True)
    resolved = material_root.resolve()
    local = resolved.parent
    if (
        resolved.is_symlink()
        or local.is_symlink()
        or local.name != ".local"
        or resolved.name != "external-materials"
        or not resolved.is_relative_to(local)
    ):
        raise ValueError("material root must be private .local/external-materials")
    control = local / "full-acquisition"
    if control.is_symlink() or inside_without_links(local, control) is None:
        raise ValueError("full-acquisition escaped private root")
    return resolved, control


def _item_id(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:16]}"


def _plan_for(urls: list[str], run_id: str) -> tuple[dict, list[dict]]:
    validate_task_id(run_id)
    held = []
    admitted = []
    for url in _dedupe(urls):
        if _admitted(url):
            admitted.append(url)
        else:
            held.append({"url": url, "reason": "outside_https_allowlist"})
    hosts = sorted({urlsplit(url).hostname for url in admitted})
    robots = [f"https://{host}/robots.txt" for host in hosts]
    items = [
        {
            "id": _item_id("r", host),
            "url": f"https://{host}/robots.txt",
            "title": "取得規則",
            "kind": "robots",
        }
        for host in hosts
    ]
    for url in admitted:
        if url in robots:
            continue
        items.append(
            {
                "id": _item_id("d", url),
                "url": url,
                "title": "官公庁原本",
                "kind": "document",
            }
        )
    plan = {"run_id": run_id, "allowed_hosts": hosts, "items": items}
    for item in items:
        validate_task_id(item["id"])
        validate_task_id(f"{run_id}-{item['id']}-a3")
    return plan, held


def _write_plan(path: Path, plan: dict, *, local: Path) -> None:
    payload = (json.dumps(plan, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if path.is_symlink() or inside_without_links(local, path) is None:
        raise ValueError("plan escaped private root")
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("frozen plan changed; use a new batch identifier")
        return
    parent = path.parent
    if parent.is_symlink() or inside_without_links(local, parent) is None:
        raise ValueError("plan escaped private root")
    parent.mkdir(parents=True, exist_ok=True)
    pinned_parent = inside_without_links(local, parent)
    temp = path.with_suffix(path.suffix + ".tmp")
    pinned_temp = inside_without_links(local, temp)
    if (
        temp.is_symlink()
        or pinned_parent is None
        or pinned_temp is None
        or pinned_temp.parent != pinned_parent
    ):
        raise ValueError("plan escaped private root")
    temp.write_bytes(payload)
    pinned_temp = inside_without_links(local, temp)
    if temp.is_symlink() or pinned_temp is None or pinned_temp.parent != pinned_parent:
        raise ValueError("plan escaped private root")
    temp.replace(path)
    if path.is_symlink() or inside_without_links(local, path) is None:
        raise ValueError("plan escaped private root")


def _legacy_file(legacy_root: Path, url: str) -> Path | None:
    folder = legacy_root / "raw"
    if not folder.is_dir():
        return None
    matches = sorted(folder.glob(key(url) + ".*"))
    if len(matches) > 1:
        raise ValueError("legacy raw is ambiguous; not overwriting")
    return matches[0] if matches else None


def _legacy_index(legacy_root: Path) -> dict[str, dict]:
    path = legacy_root / "index.csv"
    if not path.exists():
        return {}
    rows = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            url = (row.get("URL") or "").strip()
            if not url:
                continue
            previous = rows.get(url)
            if previous and previous.get("sha256") != row.get("sha256"):
                raise ValueError("legacy index has two sha256 values; not overwriting")
            rows[url] = row
    return rows


def _observed_at(row: dict | None, source: Path) -> str:
    text = ((row or {}).get("取得時刻") or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if text:
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            return parsed.isoformat(timespec="seconds")
    return datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat(
        timespec="seconds"
    )


def _content_type(path: Path) -> str:
    return {
        ".html": "text/html",
        ".htm": "text/html",
        ".pdf": "application/pdf",
        ".json": "application/json",
        ".xml": "application/xml",
    }.get(path.suffix.lower(), "application/octet-stream")


def _bind_legacy(
    *,
    material_root: Path,
    control: Path,
    run_id: str,
    item: dict,
    legacy_root: Path | None,
    index: dict[str, dict],
) -> None:
    receipt_path = control / "receipts" / f"{run_id}-{item['id']}.json"
    legacy = _legacy_file(legacy_root, item["url"]) if legacy_root else None
    legacy_bytes = legacy.read_bytes() if legacy else None
    legacy_sha = hashlib.sha256(legacy_bytes).hexdigest() if legacy_bytes is not None else None
    row = index.get(item["url"]) if legacy is not None else None
    if row and (row.get("sha256") or "").strip() not in {"", legacy_sha}:
        raise ValueError("legacy index sha differs from raw bytes; not overwriting")
    if receipt_path.exists():
        existing = json.loads(receipt_path.read_text(encoding="utf-8"))
        if existing.get("url") != item["url"] or existing.get("method", "GET") != "GET":
            raise ValueError("task receipt URL collision")
        readback(existing, material_root)
        if legacy_sha is not None and legacy_sha != existing["sha256"]:
            raise ValueError("legacy raw sha differs from saved receipt; not overwriting")
        return
    if legacy is None or row is None:
        return
    http = (row.get("HTTP") or "").strip()
    if not http.isdigit():
        return
    status = int(http)
    registration_id = f"{run_id}-{item['id']}-a1"
    task_dir = material_root / registration_id
    local = material_root.parent
    if task_dir.is_symlink() or inside_without_links(local, task_dir) is None:
        raise ValueError("registration escaped private root")
    records = list(task_dir.glob("*/record.json")) if task_dir.exists() else []
    if records:
        if len(records) != 1:
            raise ValueError("ambiguous legacy registration; not overwriting")
        record_path = records[0]
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("sha256") != legacy_sha or record.get("source_url") != item["url"]:
            raise ValueError("existing registration sha or url differs; not overwriting")
    else:
        record_path = register_local_material(
            input_path=legacy,
            source_url=item["url"],
            task_id=registration_id,
            title=item["title"],
            purpose="公式原レスポンスの未加工保存",
            storage_root=material_root,
            observed_at=_observed_at(row, legacy),
        )
        if task_dir.is_symlink() or inside_without_links(local, record_path) is None:
            raise ValueError("registration escaped private root")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record["sha256"] != legacy_sha:
            raise ValueError("registered sha differs from legacy raw; not overwriting")
    receipt = {
        "schema_version": "official-raw-receipt/v1",
        "url": item["url"],
        "method": "GET",
        "status": status,
        "headers": {"content-type": _content_type(legacy)},
        "observed_at": record["observed_at"],
        "sha256": record["sha256"],
        "bytes": record["bytes"],
        "record_path": str(record_path),
        "representation": "http-response-body-bytes",
        "attempt": 1,
        "content_verification": "unverified",
        "legacy_import": True,
    }
    readback(receipt, material_root)
    atomic_json(receipt_path, receipt, root=local)


def preserve_existing(
    plan: dict, *, material_root: Path, control: Path, legacy_root: Path | None
) -> None:
    if legacy_root is not None:
        legacy_root = legacy_root.resolve()
        if not legacy_root.is_dir():
            raise ValueError("legacy root is missing; not creating a second store")
        if legacy_root == material_root or legacy_root.is_relative_to(material_root):
            raise ValueError("legacy root must stay outside the material root")
    index = _legacy_index(legacy_root) if legacy_root else {}
    for item in plan["items"]:
        if item["kind"] == "robots":
            continue
        _bind_legacy(
            material_root=material_root,
            control=control,
            run_id=plan["run_id"],
            item=item,
            legacy_root=legacy_root,
            index=index,
        )


def acquire(
    urls: list[str],
    *,
    material_root: Path,
    run_id: str = RUN_ID,
    legacy_root: Path | None = None,
    limit: int = 25,
    workers: int = 2,
) -> dict:
    material_root, control = _roots(material_root)
    plan, held = _plan_for(urls, run_id)
    if not plan["items"]:
        return {
            "run_id": run_id,
            "held": held,
            "processed_items": 0,
            "successful_raw_responses": 0,
            "failed_items": len(held),
            "outcomes": [],
        }
    local = material_root.parent
    plan_path = control / "plans" / f"{run_id}.json"
    if plan_path.is_symlink() or inside_without_links(local, plan_path) is None:
        raise ValueError("plan escaped private root")
    _write_plan(plan_path, plan, local=local)
    preserve_existing(
        plan, material_root=material_root, control=control, legacy_root=legacy_root
    )
    result = collect_plan(
        plan_path, material_root=material_root, limit=limit, workers=workers
    )
    result["held"] = held
    if held:
        result["failed_items"] += len(held)
    return result


def _manifest(material_root: Path, run_id: str) -> tuple[Path, dict]:
    validate_task_id(run_id)
    material_root, control = _roots(material_root)
    local = material_root.parent
    path = control / "batches" / run_id / "manifest.json"
    if path.is_symlink() or inside_without_links(local, path) is None or not path.is_file():
        raise ValueError("batch manifest is missing")
    return material_root, json.loads(path.read_text(encoding="utf-8"))


def _original_path(receipt: dict) -> Path:
    record_path = Path(receipt["record_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    name = record.get("saved_filename")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("raw filename invalid")
    return record_path.parent / name


def _plan_items(local: Path, run_id: str) -> dict[str, dict]:
    validate_task_id(run_id)
    if local.name != ".local":
        raise ValueError("plan escaped private root")
    control = local / "full-acquisition"
    plan_path = control / "plans" / f"{run_id}.json"
    if inside_without_links(local, control) is None or inside_without_links(local, plan_path) is None:
        raise ValueError("plan escaped private root")
    if plan_path.is_symlink() or not plan_path.is_file():
        raise ValueError("frozen plan is missing")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    if plan.get("run_id") != run_id:
        raise ValueError("plan run_id mismatch")
    found = {}
    for item in plan["items"]:
        item_id = item.get("id")
        url = item.get("url")
        kind = item.get("kind")
        if (
            not isinstance(item_id, str)
            or not isinstance(url, str)
            or not isinstance(kind, str)
            or item_id in found
        ):
            raise ValueError("plan item id is invalid")
        validate_task_id(item_id)
        found[item_id] = {"url": url, "kind": kind}
    return found


def _text_destination(local: Path, run_id: str, outcome_id: str) -> Path:
    batch = local / "full-acquisition" / "batches" / run_id
    if batch.is_symlink() or inside_without_links(local, batch) is None:
        raise ValueError("text directory escaped batch")
    text_dir = batch / "text"
    if text_dir.is_symlink() or inside_without_links(local, text_dir) is None:
        raise ValueError("text directory escaped batch")
    dest = text_dir / f"{outcome_id}.txt"
    if dest.is_symlink() or inside_without_links(local, dest) is None:
        raise ValueError("text destination escaped batch")
    return dest


def _publish_text(local: Path, run_id: str, outcome_id: str, text: str) -> None:
    dest = _text_destination(local, run_id, outcome_id)
    text_dir = dest.parent
    expected = local / "full-acquisition" / "batches" / run_id / "text"
    if inside_without_links(local, text_dir) is None or inside_without_links(local, expected) is None:
        raise ValueError("text directory escaped batch")
    text_dir.mkdir(parents=True, exist_ok=True)
    pinned_text = inside_without_links(local, text_dir)
    pinned_expected = inside_without_links(local, expected)
    if (
        text_dir.is_symlink()
        or dest.is_symlink()
        or pinned_text is None
        or pinned_expected is None
        or pinned_text != pinned_expected
    ):
        raise ValueError("text destination escaped batch")
    temp = dest.with_suffix(".txt.tmp")
    pinned_temp = inside_without_links(local, temp)
    if temp.is_symlink() or pinned_temp is None or pinned_temp.parent != pinned_text:
        raise ValueError("text destination escaped batch")
    temp.write_text(text, encoding="utf-8")
    pinned_temp = inside_without_links(local, temp)
    if pinned_temp is None or pinned_temp.parent != pinned_text:
        raise ValueError("text destination escaped batch")
    temp.replace(dest)
    pinned_dest = inside_without_links(local, dest)
    if dest.is_symlink() or pinned_dest is None or pinned_dest.parent != pinned_text:
        raise ValueError("text destination escaped batch")


def _index_row(outcome: dict, *, state: str, kind: str, pages: str, text_rel: str) -> dict:
    receipt = outcome.get("receipt") or {}
    return {
        "URL": outcome.get("url", ""),
        "状態": state,
        "HTTP": receipt.get("status", ""),
        "バイト": receipt.get("bytes", ""),
        "sha256": receipt.get("sha256", ""),
        "種類": kind,
        "ページ数": pages,
        "テキスト": text_rel,
        "取得時刻": receipt.get("observed_at", ""),
    }


def _publish_index(local: Path, run_id: str, rows: list[dict]) -> None:
    batch = local / "full-acquisition" / "batches" / run_id
    if batch.is_symlink() or inside_without_links(local, batch) is None:
        raise ValueError("index escaped batch")
    dest = batch / "index.csv"
    temp = dest.with_suffix(".csv.tmp")
    pinned_batch = inside_without_links(local, batch)
    pinned_temp = inside_without_links(local, temp)
    if (
        dest.is_symlink()
        or temp.is_symlink()
        or pinned_batch is None
        or pinned_temp is None
        or pinned_temp.parent != pinned_batch
        or inside_without_links(local, dest) is None
    ):
        raise ValueError("index escaped batch")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=INDEX_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    pinned_temp = inside_without_links(local, temp)
    if temp.is_symlink() or pinned_temp is None or pinned_temp.parent != pinned_batch:
        raise ValueError("index escaped batch")
    temp.replace(dest)
    if dest.is_symlink() or inside_without_links(local, dest) is None:
        raise ValueError("index escaped batch")


def _bound_outcome(outcome: dict, plan_items: dict[str, dict]) -> str:
    outcome_id = outcome.get("id")
    expected = plan_items.get(outcome_id) if isinstance(outcome_id, str) else None
    if expected is None:
        raise ValueError("manifest outcome is not in the frozen plan")
    validate_task_id(outcome_id)
    receipt = outcome.get("receipt")
    if (
        outcome.get("url") != expected["url"]
        or outcome.get("kind") != expected["kind"]
        or (receipt is not None and receipt.get("url") != expected["url"])
    ):
        raise ValueError("manifest outcome does not match the frozen plan")
    return outcome_id


def extract_saved(material_root: Path, *, run_id: str = RUN_ID) -> dict:
    """保存済みバイトから全文を作る。通信しない。原本は書き換えない。"""
    validate_task_id(run_id)
    material_root, control = _roots(material_root)
    local = material_root.parent
    if control != local / "full-acquisition":
        raise ValueError("full-acquisition escaped private root")
    batch = control / "batches" / run_id
    if batch.is_symlink() or inside_without_links(local, batch) is None:
        raise ValueError("batch directory escaped private root")
    index_path = batch / "index.csv"
    index_tmp = index_path.with_suffix(".csv.tmp")
    if (
        index_path.is_symlink()
        or index_tmp.is_symlink()
        or inside_without_links(local, index_path) is None
        or inside_without_links(local, index_tmp) is None
    ):
        raise ValueError("index escaped batch")
    plan_items = _plan_items(local, run_id)
    _material_root, manifest = _manifest(material_root, run_id)
    material_root = _material_root
    for outcome in manifest["outcomes"]:
        _bound_outcome(outcome, plan_items)
    written = []
    failed = []
    unextracted = []
    index_rows = []
    for outcome in manifest["outcomes"]:
        outcome_id = _bound_outcome(outcome, plan_items)
        receipt = outcome.get("receipt")
        if outcome.get("kind") == "robots" or not receipt or receipt.get("status") != 200:
            if outcome.get("kind") != "robots":
                index_rows.append(
                    _index_row(
                        outcome,
                        state=str(outcome.get("status") or "未取得"),
                        kind="",
                        pages="",
                        text_rel="",
                    )
                )
            continue
        _text_destination(local, run_id, outcome_id)
        payload = readback(receipt, material_root)
        original = _original_path(receipt)
        if len(payload) != receipt["bytes"]:
            raise ValueError("extract saw a truncated original")
        kind = "pdf" if payload[:5] == b"%PDF-" or original.suffix == ".pdf" else "html"
        try:
            text = (
                pdf_text(original)
                if kind == "pdf"
                else html_text(payload, receipt.get("headers", {}).get("content-type", ""))
            )
        except ExtractStatus as error:
            bucket = failed if error.extract_status == "failed" else unextracted
            bucket.append(
                {
                    "id": outcome_id,
                    "extract_status": error.extract_status,
                    "truncated": False,
                }
            )
            index_rows.append(
                _index_row(
                    outcome,
                    state=error.extract_status,
                    kind=kind,
                    pages="",
                    text_rel="",
                )
            )
            continue
        _publish_text(local, run_id, outcome_id, text)
        state = "取得" if text.strip() else "文字なし（画像PDFなど）"
        pages = str(text.count("\f") + 1 if kind == "pdf" else 1)
        index_rows.append(
            _index_row(
                outcome,
                state=state,
                kind=kind,
                pages=pages,
                text_rel=f"text/{outcome_id}.txt",
            )
        )
        written.append(
            {
                "id": outcome_id,
                "chars": len(text),
                "sha256": receipt["sha256"],
                "truncated": False,
                "extract_status": "complete",
            }
        )
    _publish_index(local, run_id, index_rows)
    return {
        "run_id": run_id,
        "extracted": written,
        "failed": failed,
        "unextracted": unextracted,
        "truncated": False,
        "failed_items": len(failed) + len(unextracted),
    }


def verify_saved(material_root: Path, *, run_id: str = RUN_ID) -> dict:
    """receipt と原本バイトを照合する。通信しない。内容の真偽は unverified のまま。"""
    material_root, manifest = _manifest(material_root, run_id)
    plan_items = _plan_items(material_root.parent, run_id)
    checked = 0
    for outcome in manifest["outcomes"]:
        _bound_outcome(outcome, plan_items)
        receipt = outcome.get("receipt")
        if not receipt:
            continue
        payload = readback(receipt, material_root)
        if (
            hashlib.sha256(payload).hexdigest() != receipt["sha256"]
            or len(payload) != receipt["bytes"]
            or receipt.get("content_verification") != "unverified"
        ):
            raise ValueError("raw receipt/original mismatch")
        checked += 1
    return {
        "run_id": run_id,
        "checked": checked,
        "content_verification": "unverified",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "官公庁原本を既存collectorの完全バイト保存へ渡す。"
            "保存先は --material-root（.local/external-materials）。"
            "明示的な禁止、取得規則未確認、ツール障害は別の結果にし、未確認の間は本文へ通信しない。"
            "--out は旧rawの読み取り専用。既存URLとsha256は上書きしない。"
        )
    )
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="旧 raw の読み取り専用。未指定のとき保存先ディレクトリは作らない",
    )
    parser.add_argument("--run-id", default=RUN_ID)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--phase",
        choices=("fetch", "extract", "verify"),
        default="fetch",
        help="fetch は取得、extract はローカル抽出、verify は sha 照合",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="互換のため受け付ける。既存URLとsha256は上書きしない",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="3秒未満は拒否する。取得間隔は既存collectorのまま",
    )
    parser.add_argument("--data", type=Path, default=DATA)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.refresh:
        print("既存のURLとsha256は上書きしない", file=sys.stderr)
        return 2
    if args.sleep is not None and args.sleep < 3:
        print("取得間隔は既存collectorの3秒未満にできない", file=sys.stderr)
        return 2
    if not 1 <= args.workers <= 2:
        print("workers は 1 から 2 です", file=sys.stderr)
        return 2
    if args.phase == "extract":
        result = extract_saved(args.material_root, run_id=args.run_id)
    elif args.phase == "verify":
        result = verify_saved(args.material_root, run_id=args.run_id)
    else:
        result = acquire(
            source_urls(args.data),
            material_root=args.material_root,
            run_id=args.run_id,
            legacy_root=args.out,
            limit=args.limit,
            workers=args.workers,
        )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "outcomes"},
            ensure_ascii=False,
        )
    )
    return 1 if result.get("failed_items") or result.get("pending_items") else 0


if __name__ == "__main__":
    raise SystemExit(main())
