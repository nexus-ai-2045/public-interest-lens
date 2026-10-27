"""外部資料をタスク単位の非公開ローカル保管庫へ登録する。"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

try:
    from .path_guard import inside_without_links
except ImportError:
    from path_guard import inside_without_links


SCHEMA_VERSION = "external-material/v1"
TASK_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def validate_source_url(source_url: str) -> str:
    """公開HTTP(S)資料を指すURLとして最低限安全か検査する。"""
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("source_url は公開 HTTP(S) URL である必要があります")

    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ValueError("ローカルホストURLは登録できません")

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return source_url

    if not address.is_global:
        raise ValueError("非公開・予約済みIPアドレスは登録できません")
    return source_url


def validate_task_id(task_id: str) -> str:
    if not TASK_ID_PATTERN.fullmatch(task_id):
        raise ValueError(
            "task_id は英数字で始まる80文字以内の英数字・ピリオド・ハイフン・"
            "アンダースコアにしてください"
        )
    return task_id


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_observed_at(observed_at: str | None) -> tuple[str, str]:
    if observed_at is None:
        parsed = datetime.now().astimezone()
    else:
        try:
            parsed = datetime.fromisoformat(observed_at)
        except ValueError as error:
            raise ValueError(
                "observed_at はタイムゾーン付きISO 8601日時にしてください"
            ) from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError(
                "observed_at はタイムゾーン付きISO 8601日時にしてください"
            )
    return parsed.isoformat(timespec="seconds"), parsed.date().isoformat()


def register_local_material(
    *,
    input_path: Path,
    source_url: str,
    task_id: str,
    title: str,
    purpose: str,
    storage_root: Path,
    observed_at: str | None = None,
    dry_run: bool = False,
    source_in_id: bool = False,
    observed_at_basis: str | None = None,
) -> Path:
    """ダウンロード済み資料と事実来歴manifestを同じ保管単位へ保存する。
    source_in_id：取得元 URL も material_id に含める（同じ本文を別の URL から取ったとき、来歴を分ける）。"""
    source = input_path.resolve(strict=True)
    if not source.is_file():
        raise ValueError("input_path は通常ファイルである必要があります")

    validated_url = validate_source_url(source_url)
    validated_task_id = validate_task_id(task_id)
    timestamp, observed_date = normalize_observed_at(observed_at)
    digest = sha256_file(source)
    key = hashlib.sha256(f"{digest}\n{validated_url}".encode("utf-8")).hexdigest() if source_in_id else digest
    material_id = f"{observed_date}-{key[:12]}"
    task_dir = storage_root / validated_task_id
    destination_dir = task_dir / material_id
    record_path = destination_dir / "record.json"
    if (
        task_dir.is_symlink()
        or destination_dir.is_symlink()
        or inside_without_links(storage_root, task_dir) is None
        or inside_without_links(storage_root, destination_dir) is None
    ):
        raise ValueError("registration escaped storage root")
    if dry_run:
        return record_path

    destination_dir.mkdir(parents=True, exist_ok=False)
    if task_dir.is_symlink() or destination_dir.is_symlink():
        raise ValueError("registration escaped storage root")

    suffix = source.suffix.lower()
    saved_filename = f"original{suffix}" if suffix else "original.bin"
    saved_path = destination_dir / saved_filename
    if saved_path.is_symlink() or inside_without_links(storage_root, saved_path) is None:
        raise ValueError("registration escaped storage root")
    shutil.copy2(source, saved_path)
    if saved_path.is_symlink() or inside_without_links(storage_root, record_path) is None:
        raise ValueError("registration escaped storage root")

    record = {
        "schema_version": SCHEMA_VERSION,
        "recorded_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "recorded_by": "codex",
        "task_id": validated_task_id,
        "material_id": material_id,
        "title": title,
        "purpose": purpose,
        "source_url": validated_url,
        "source_actor": "unknown",
        "source_event_time": "unknown",
        "observed_at": timestamp,
        **({"observed_at_basis": observed_at_basis} if observed_at_basis else {}),
        "saved_filename": saved_filename,
        "media_type": mimetypes.guess_type(source.name)[0]
        or "application/octet-stream",
        "bytes": saved_path.stat().st_size,
        "sha256": digest,
        "content_verification": "unverified",
        "verification_note": (
            "この記録は資料を取得・保存した事実を示す。資料内容の正確性や主張の"
            "真偽を確認済み事実へ昇格しない。"
        ),
    }
    record_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return record_path


def register_once(
    *,
    input_path: Path,
    source_url: str,
    task_id: str,
    title: str,
    purpose: str,
    storage_root: Path,
    observed_at: str | None = None,
) -> str:
    """取得処理から呼ぶ登録。同じ日に同じ URL から同じ中身を登録済みなら登録し直さず、その material_id を返す。
    material_id には URL も含める（同じ404本文を別の URL が返しても、それぞれの出典を残す）。
    observed_at は取得した時刻。分からないとき（控えから登録し直すとき）は登録時刻を使わず、
    控えのファイルの更新時刻を入れて observed_at_basis にそう書く。"""
    if observed_at:
        basis = "fetched_at"
    else:
        mtime = datetime.fromtimestamp(input_path.stat().st_mtime).astimezone()
        observed_at, basis = mtime.isoformat(timespec="seconds"), "file_mtime（取得時刻の記録が無く、控えの更新時刻）"
    kwargs = dict(input_path=input_path, source_url=source_url, task_id=task_id, title=title,
                  purpose=purpose, storage_root=storage_root, observed_at=observed_at, source_in_id=True,
                  observed_at_basis=basis)
    record_path = register_local_material(**kwargs, dry_run=True)
    if not record_path.exists():
        register_local_material(**kwargs)
    else:
        if inside_without_links(storage_root, record_path) is None:
            raise ValueError("registered record escaped storage root")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        digest = sha256_file(input_path)
        size = input_path.stat().st_size
        name = record.get("saved_filename")
        observed = record.get("observed_at")
        if (record.get("schema_version") != SCHEMA_VERSION
                or record.get("source_url") != source_url
                or record.get("task_id") != task_id
                or record.get("material_id") != record_path.parent.name
                or record.get("sha256") != digest
                or type(record.get("bytes")) is not int or record["bytes"] != size
                or not isinstance(name, str) or not name.startswith("original.") or Path(name).name != name
                or not isinstance(observed, str)
                or normalize_observed_at(observed)[1] != record_path.parent.name[:10]):
            raise ValueError("existing registration metadata does not match input")
        saved = record_path.parent / name
        if inside_without_links(storage_root, saved) is None or (saved.exists() and not saved.is_file()):
            raise ValueError("registered original escaped storage root")
        if not saved.exists() or saved.stat().st_size != size or sha256_file(saved) != digest:
            # 観測記録は書き換えず、同じURL・hashの再取得copyから原本だけ復旧する。
            handle, stage_name = tempfile.mkstemp(prefix=".restore-", dir=record_path.parent)
            os.close(handle)
            stage = Path(stage_name)
            try:
                shutil.copy2(input_path, stage)
                if stage.stat().st_size != size or sha256_file(stage) != digest:
                    raise ValueError("restoration copy does not match registration")
                if inside_without_links(storage_root, saved) is None:
                    raise ValueError("registered original escaped storage root")
                if saved.exists():
                    handle, backup_name = tempfile.mkstemp(prefix="corrupt-", dir=record_path.parent)
                    os.close(handle)
                    os.replace(saved, backup_name)  # 破損したbyteも捨てない。
                os.replace(stage, saved)
            finally:
                stage.unlink(missing_ok=True)
    return record_path.parent.name


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="外部資料をタスク単位の非公開ローカル保管庫へ登録します"
    )
    parser.add_argument("--input-file", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--purpose", required=True)
    parser.add_argument(
        "--storage-root",
        type=Path,
        default=Path(".local/external-materials"),
    )
    parser.add_argument("--observed-at")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="検証と保存予定の表示だけを行い、ファイルを書き込みません",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record_path = register_local_material(
        input_path=args.input_file,
        source_url=args.source_url,
        task_id=args.task_id,
        title=args.title,
        purpose=args.purpose,
        storage_root=args.storage_root,
        observed_at=args.observed_at,
        dry_run=args.dry_run,
    )
    print(
        json.dumps(
            {
                "action": "register_external_material",
                "target": str(record_path),
                "dry_run": args.dry_run,
                "changed": not args.dry_run,
                "verified": record_path.exists() if not args.dry_run else True,
                "report_path": str(record_path) if not args.dry_run else None,
                "next_action": (
                    "run_without_dry_run"
                    if args.dry_run
                    else "review_record_and_material"
                ),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
