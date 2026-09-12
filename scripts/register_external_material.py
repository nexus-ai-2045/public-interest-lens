"""外部資料をタスク単位の非公開ローカル保管庫へ登録する。"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import mimetypes
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


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
) -> Path:
    """ダウンロード済み資料と事実来歴manifestを同じ保管単位へ保存する。"""
    source = input_path.resolve(strict=True)
    if not source.is_file():
        raise ValueError("input_path は通常ファイルである必要があります")

    validated_url = validate_source_url(source_url)
    validated_task_id = validate_task_id(task_id)
    timestamp, observed_date = normalize_observed_at(observed_at)
    digest = sha256_file(source)
    material_id = f"{observed_date}-{digest[:12]}"
    destination_dir = storage_root / validated_task_id / material_id
    record_path = destination_dir / "record.json"
    if dry_run:
        return record_path

    destination_dir.mkdir(parents=True, exist_ok=False)

    suffix = source.suffix.lower()
    saved_filename = f"original{suffix}" if suffix else "original.bin"
    saved_path = destination_dir / saved_filename
    shutil.copy2(source, saved_path)

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
