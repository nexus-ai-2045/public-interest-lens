from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .path_guard import inside_without_links
    from .register_external_material import (
        register_local_material,
        validate_task_id,
        validate_source_url,
    )
except ImportError:
    from path_guard import inside_without_links
    from register_external_material import (
        register_local_material,
        validate_task_id,
        validate_source_url,
    )

PUBLIC_HEADERS = {
    "content-type",
    "content-length",
    "content-encoding",
    "etag",
    "last-modified",
    "date",
    "retry-after",
    "location",
}


def atomic_json(path: Path, value: dict, *, root: Path | None = None) -> None:
    parent = path.parent
    temp = path.with_suffix(path.suffix + ".tmp")

    def contained(target: Path) -> None:
        if target.is_symlink():
            raise ValueError("json destination escaped private root")
        if root is not None and inside_without_links(root, target) is None:
            raise ValueError("json destination escaped private root")

    contained(parent)
    parent.mkdir(parents=True, exist_ok=True)
    pinned_parent = inside_without_links(root, parent) if root is not None else None
    contained(parent)
    contained(path)
    contained(temp)
    if root is not None:
        pinned_temp = inside_without_links(root, temp)
        if pinned_parent is None or pinned_temp is None or pinned_temp.parent != pinned_parent:
            raise ValueError("json destination escaped private root")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    contained(temp)
    if root is not None:
        pinned_temp = inside_without_links(root, temp)
        if pinned_temp is None or pinned_temp.parent != pinned_parent:
            raise ValueError("json destination escaped private root")
    temp.replace(path)
    contained(path)


@contextmanager
def host_lock(control_root: Path, host: str):
    local = control_root.parent
    root = control_root / "hosts"
    lock_path = root / f"{host}.lock"
    state_path = root / f"{host}.json"

    def contained(path: Path) -> None:
        if path.is_symlink() or inside_without_links(local, path) is None:
            raise ValueError("host destination escaped private root")

    contained(root)
    contained(lock_path)
    contained(state_path)
    root.mkdir(parents=True, exist_ok=True)
    contained(root)
    contained(lock_path)
    contained(state_path)
    with lock_path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield state_path
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def readback(receipt: dict, material_root: Path) -> bytes:
    record_path = Path(receipt["record_path"]).resolve(strict=True)
    if not record_path.is_relative_to(material_root.resolve()):
        raise ValueError("raw receipt escaped material root")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    name = record.get("saved_filename")
    if not isinstance(name, str) or Path(name).name != name:
        raise ValueError("raw filename invalid")
    path = (record_path.parent / name).resolve(strict=True)
    if path.parent != record_path.parent:
        raise ValueError("raw original escaped record directory")
    payload = path.read_bytes()
    if (
        hashlib.sha256(payload).hexdigest() != receipt["sha256"]
        or len(payload) != receipt["bytes"]
        or record["sha256"] != receipt["sha256"]
        or record["bytes"] != receipt["bytes"]
        or record["source_url"] != receipt["url"]
        or record["observed_at"] != receipt["observed_at"]
    ):
        raise ValueError("raw receipt/original mismatch")
    return payload


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def capture_url(
    url: str,
    *,
    material_root: Path,
    control_root: Path,
    task_id: str,
    title: str,
    allowed_hosts: set[str],
    delay_seconds: float = 3.0,
    max_bytes: int = 20 * 1024 * 1024,
    method: str = "GET",
    opener=None,
    now=time.time,
    sleep=time.sleep,
) -> dict:
    validate_task_id(task_id)
    validate_source_url(url)
    if method not in {"GET", "HEAD"}:
        raise ValueError("only public GET or HEAD requests allowed")
    parsed = urlsplit(url)
    host = parsed.hostname
    if (
        parsed.scheme != "https"
        or host not in allowed_hosts
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ValueError("URL outside official HTTPS allowlist")
    if not 3 <= delay_seconds <= 60 or not 1 <= max_bytes <= 20 * 1024 * 1024:
        raise ValueError("invalid delay or response cap")
    if (
        control_root.parent.name != ".local"
        or material_root.name != "external-materials"
    ):
        raise ValueError("raw control and material storage must be private .local")
    if material_root.parent.resolve() != control_root.parent.resolve():
        raise ValueError("control and material roots must share one .local")
    local = material_root.parent.resolve()
    if (
        control_root.resolve().parent != local
        or material_root.resolve().parent != local
    ):
        raise ValueError("storage root link escaped private .local")
    control_root.mkdir(parents=True, exist_ok=True)
    receipt_path = control_root / "receipts" / f"{task_id}.json"
    if receipt_path.exists():
        old = json.loads(receipt_path.read_text(encoding="utf-8"))
        if old["url"] != url or old.get("method", "GET") != method:
            raise ValueError("task receipt URL collision")
        readback(old, material_root)
        return old
    if shutil.disk_usage(control_root).free < max_bytes + 5 * 1024**3:
        raise OSError("disk reserve below five GiB")
    opener = opener or urllib.request.build_opener(NoRedirect)
    with host_lock(control_root, host) as state_path:
        if receipt_path.exists():
            old = json.loads(receipt_path.read_text(encoding="utf-8"))
            if old["url"] != url or old.get("method", "GET") != method:
                raise ValueError("task receipt URL collision")
            readback(old, material_root)
            return old
        for attempt in range(1, 4):
            state = (
                json.loads(state_path.read_text(encoding="utf-8"))
                if state_path.exists()
                else {}
            )
            wait = max(0.0, state.get("next_allowed_epoch", 0) - now())
            if wait > 60:
                raise OSError(
                    "host Retry-After deferred; resume after host state deadline"
                )
            if wait:
                sleep(wait)
            request = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "public-interest-lens/0.1 (official archive)",
                    "Accept-Encoding": "identity",
                },
                method=method,
            )
            response = None
            network_error = None
            try:
                try:
                    response = opener.open(request, timeout=40)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    payload = response.read(max_bytes + 1)
                    status = response.code
                    headers = {
                        key.lower(): value
                        for key, value in response.headers.items()
                        if key.lower() in PUBLIC_HEADERS
                    }
                    if len(payload) > max_bytes:
                        raise ValueError(
                            "response exceeded cap; truncated body not an original"
                        )
            except (OSError, ValueError) as error:
                network_error = error
            finished = now()
            retry_at = finished + delay_seconds
            retry_invalid = False
            if network_error is None and headers.get("retry-after"):
                value = headers["retry-after"]
                try:
                    retry_at = max(retry_at, finished + max(0, int(value)))
                except ValueError:
                    try:
                        retry_at = max(
                            retry_at, parsedate_to_datetime(value).timestamp()
                        )
                    except (ValueError, TypeError, OverflowError):
                        retry_invalid = True
                        retry_at = max(retry_at, finished + 60)
            atomic_json(
                state_path,
                {
                    "host": host,
                    "response_finished_epoch": finished,
                    "next_allowed_epoch": retry_at,
                },
                root=local,
            )
            if network_error is not None:
                if isinstance(network_error, ValueError) or attempt == 3:
                    raise network_error
                continue
            observed = datetime.fromtimestamp(finished, timezone.utc).isoformat(
                timespec="seconds"
            )
            digest = hashlib.sha256(payload).hexdigest()
            content_type = headers.get("content-type", "").lower()
            suffix = (
                ".json"
                if "json" in content_type
                else (
                    ".xml"
                    if "xml" in content_type
                    else (
                        ".html"
                        if "html" in content_type
                        else ".pdf" if "pdf" in content_type else ".bin"
                    )
                )
            )
            stage = control_root / "staging" / f"{task_id}-a{attempt}{suffix}"
            stage_dir = stage.parent
            if stage_dir.is_symlink() or inside_without_links(local, stage_dir) is None:
                raise ValueError("staging escaped private root")
            stage_dir.mkdir(parents=True, exist_ok=True)
            pinned_stage_dir = inside_without_links(local, stage_dir)
            pinned_stage = inside_without_links(local, stage)
            if (
                stage.is_symlink()
                or pinned_stage_dir is None
                or pinned_stage is None
                or pinned_stage.parent != pinned_stage_dir
            ):
                raise ValueError("staging escaped private root")
            if stage.exists() and stage.read_bytes() != payload:
                raise ValueError("uncommitted raw collision; use a new run identifier")
            stage.write_bytes(payload)
            pinned_stage = inside_without_links(local, stage)
            if stage.is_symlink() or pinned_stage is None or pinned_stage.parent != pinned_stage_dir:
                raise ValueError("staging escaped private root")
            registration_id = f"{task_id}-a{attempt}"
            task_dir = material_root / registration_id
            if task_dir.is_symlink() or inside_without_links(local, task_dir) is None:
                raise ValueError("registration escaped private root")
            records = list(task_dir.glob("*/record.json")) if task_dir.exists() else []
            if records:
                if len(records) != 1:
                    raise ValueError("ambiguous interrupted registration")
                record = json.loads(records[0].read_text(encoding="utf-8"))
                candidate = {
                    "record_path": str(records[0]),
                    "sha256": digest,
                    "bytes": len(payload),
                    "url": url,
                    "observed_at": record["observed_at"],
                }
                readback(candidate, material_root)
                raise ValueError(
                    "uncommitted raw registration exists; preserve and recover receipt offline"
                )
            record_path = register_local_material(
                input_path=stage,
                source_url=url,
                task_id=registration_id,
                title=title,
                purpose="公式原レスポンスの未加工保存",
                storage_root=material_root,
                observed_at=observed,
            )
            receipt = {
                "schema_version": "official-raw-receipt/v1",
                "url": url,
                "method": method,
                "status": status,
                "headers": headers,
                "observed_at": observed,
                "sha256": digest,
                "bytes": len(payload),
                "record_path": str(record_path),
                "representation": (
                    "http-response-body-bytes"
                    if method == "GET"
                    else "http-head-metadata"
                ),
                "attempt": attempt,
                "retry_after_epoch": retry_at,
                "content_verification": "unverified",
            }
            if retry_invalid:
                receipt["retry_after_invalid"] = True
            readback(receipt, material_root)
            atomic_json(
                control_root / "attempts" / f"{task_id}-a{attempt}.json",
                receipt,
                root=local,
            )
            if status >= 500 and attempt < 3 and not retry_invalid:
                continue
            atomic_json(receipt_path, receipt, root=local)
            return receipt
    raise OSError("request attempt budget exhausted")
