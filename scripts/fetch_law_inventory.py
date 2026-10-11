from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

try:
    from .official_raw import atomic_json, capture_url, host_lock, readback
    from .register_external_material import validate_task_id
except ImportError:
    from official_raw import atomic_json, capture_url, host_lock, readback
    from register_external_material import validate_task_id


def validate_page(data: dict, *, offset: int, reported: int | None, seen: set[str]):
    rows = data.get("laws")
    total, count, next_offset = (
        data.get("total_count"),
        data.get("count"),
        data.get("next_offset"),
    )
    if (
        not isinstance(rows, list)
        or type(total) is not int
        or type(count) is not int
        or total < 0
        or count != len(rows)
        or not 0 <= count <= 100
        or (reported is not None and total != reported)
        or offset + count > total
    ):
        raise ValueError("law inventory count drift or malformed page")
    ids = [
        row.get("law_info", {}).get("law_id") if isinstance(row, dict) else None
        for row in rows
    ]
    if (
        any(not isinstance(i, str) or not i for i in ids)
        or len(set(ids)) != len(ids)
        or seen.intersection(ids)
    ):
        raise ValueError("law inventory duplicate or missing identifier")
    complete = offset + count == total
    if (complete and next_offset is not None) or (
        not complete
        and (not rows or type(next_offset) is not int or next_offset != offset + count)
    ):
        raise ValueError("law inventory cursor invalid")
    return ids, total, next_offset, complete


def inventory_url(as_of: str, offset: int) -> str:
    return "https://laws.e-gov.go.jp/api/2/laws?" + urlencode(
        {
            "limit": 100,
            "offset": offset,
            "asof": as_of,
            "order": "law_info.law_id",
            "response_format": "json",
        }
    )


def collect_inventory(
    *, material_root: Path, as_of: str, run_id: str, max_pages: int, fetch=None
) -> dict:
    date.fromisoformat(as_of)
    validate_task_id(run_id)
    if not 1 <= max_pages <= 100:
        raise ValueError("law inventory finite page budget 1..100 required")
    local = material_root.parent.resolve()
    if local.name != ".local":
        raise ValueError("private .local storage required")
    control = local / "full-acquisition"
    output = control / "law-inventory" / run_id
    if not output.resolve().is_relative_to(local):
        raise ValueError("law output escaped private root")
    path = output / "checkpoint.json"
    saved = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    if saved and saved.get("as_of") != as_of:
        raise ValueError("law inventory time scope changed")
    pages = list(saved.get("pages", []))
    seen = set()
    offset = 0
    reported = None
    complete = False
    for old in pages:
        if complete or old["offset"] != offset:
            raise ValueError("law checkpoint page sequence invalid")
        if (
            old["receipt"]["url"] != inventory_url(as_of, offset)
            or old["receipt"]["status"] != 200
        ):
            raise ValueError("law checkpoint source or HTTP status mismatch")
        data = json.loads(readback(old["receipt"], material_root))
        ids, reported, next_offset, complete = validate_page(
            data, offset=offset, reported=reported, seen=seen
        )
        if old["ids"] != ids:
            raise ValueError("law checkpoint identifiers mismatch")
        seen.update(ids)
        offset = next_offset if next_offset is not None else len(seen)
    if saved and (
        saved.get("ids_saved") != len(seen)
        or saved.get("complete") != complete
        or saved.get("next_offset") != (None if complete else offset)
    ):
        raise ValueError("law checkpoint aggregate mismatch")
    started = time.monotonic()
    with host_lock(control, "egov-inventory-owner"):
        for _ in range(max_pages):
            if complete:
                break
            url = inventory_url(as_of, offset)
            receipt = (
                fetch(url)
                if fetch is not None
                else capture_url(
                    url,
                    material_root=material_root,
                    control_root=control,
                    task_id=f"{run_id}-laws-{offset:06d}",
                    title="公開法令ID一覧",
                    allowed_hosts={"laws.e-gov.go.jp"},
                )
            )
            if receipt["url"] != url or receipt["status"] != 200:
                raise ValueError("law inventory HTTP failure; raw receipt preserved")
            data = json.loads(readback(receipt, material_root))
            ids, reported, next_offset, complete = validate_page(
                data, offset=offset, reported=reported, seen=seen
            )
            pages.append({"offset": offset, "ids": ids, "receipt": receipt})
            seen.update(ids)
            offset = next_offset if next_offset is not None else len(seen)
            saved = {
                "schema_version": "law-inventory-checkpoint/v1",
                "run_id": run_id,
                "as_of": as_of,
                "reported_total": reported,
                "ids_saved": len(seen),
                "next_offset": None if complete else offset,
                "complete": complete,
                "pages": pages,
            }
            atomic_json(path, saved)
    result = {
        **saved,
        "schema_version": "law-inventory-receipt/v1",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds_this_run": round(time.monotonic() - started, 3),
        "raw_bytes": sum(p["receipt"]["bytes"] for p in pages),
        "law_texts_saved": 0,
        "history_texts_complete": False,
        "corpus_complete": False,
        "status": "id_inventory_exhausted" if complete else "capped",
    }
    atomic_json(output / "manifest.json", result)
    atomic_json(
        output / "law-ids.json",
        {
            "representation": "derived-id-inventory",
            "as_of": as_of,
            "law_ids": sorted(seen),
            "complete": complete,
        },
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="対象日時付きの法令ID一覧を有限取得")
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()
    result = collect_inventory(
        material_root=args.material_root,
        as_of=args.as_of,
        run_id=args.run_id,
        max_pages=args.max_pages,
    )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "pages"}, ensure_ascii=False
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
