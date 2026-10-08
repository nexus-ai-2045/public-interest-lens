from __future__ import annotations

import argparse
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    from .fetch_diet_minutes import collect_pages
    from .official_raw import atomic_json, host_lock
    from .register_external_material import validate_task_id
except ImportError:
    from fetch_diet_minutes import collect_pages
    from official_raw import atomic_json, host_lock
    from register_external_material import validate_task_id


def collect_corpus(
    plan_path: Path, *, material_root: Path, max_shards: int, pages_per_shard: int
) -> dict:
    if not 1 <= max_shards <= 50 or not 1 <= pages_per_shard <= 100:
        raise ValueError("finite shard and page budgets required")
    local = material_root.parent.resolve()
    plan_path = plan_path.resolve(strict=True)
    if local.name != ".local" or not plan_path.is_relative_to(local):
        raise ValueError("plan and raw material root must share private .local")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_task_id(plan["run_id"])
    if not isinstance(plan.get("shards"), list) or not plan["shards"]:
        raise ValueError("nonempty fixed shard inventory required")
    ids = [s["id"] for s in plan["shards"]]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate shard identifiers")
    for shard in plan["shards"]:
        validate_task_id(shard["id"])
    output = local / "diet" / plan["run_id"]
    if not output.resolve().is_relative_to(local):
        raise ValueError("corpus output escaped private root")
    for shard in plan["shards"]:
        if not (output / shard["id"]).resolve().is_relative_to(output.resolve()):
            raise ValueError("shard output escaped corpus root")
    digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    receipt_path = output / "corpus-receipt.json"
    previous = (
        json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt_path.exists()
        else {}
    )
    if previous and previous["plan_sha256"] != digest:
        raise ValueError("corpus plan changed; preserve and use a new run identifier")
    started = time.monotonic()
    results = []
    progressed = 0
    with host_lock(local / "full-acquisition", "ndl-corpus-owner"):
        for shard in plan["shards"]:
            manifest_path = output / shard["id"] / "manifest.json"
            old = (
                json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest_path.exists()
                else {}
            )
            if not old.get("complete") and progressed >= max_shards:
                continue
            result = collect_pages(
                endpoint=shard["endpoint"],
                session_from=shard["session_from"],
                session_to=shard["session_to"],
                output_dir=output / shard["id"],
                material_root=material_root,
                maximum_records=10 if shard["endpoint"] == "meeting" else 100,
                delay_seconds=3,
                max_pages=pages_per_shard,
                date_from=shard["date_from"],
                date_to=shard["date_to"],
                house=shard["house"],
                expected_records=shard.get("expected_index_records"),
            )
            if result["complete"] and shard.get("expected_issue_ids_sha256"):
                issue_ids = []
                for page in result["pages"]:
                    payload = (
                        output
                        / shard["id"]
                        / "pages"
                        / f"{page['start_record']:09d}.json"
                    ).read_bytes()
                    issue_ids.extend(
                        m["issueID"] for m in json.loads(payload)["meetingRecord"]
                    )
                actual = hashlib.sha256(
                    "\n".join(sorted(issue_ids)).encode("utf-8")
                ).hexdigest()
                if actual != shard["expected_issue_ids_sha256"]:
                    result = {
                        **result,
                        "status": "failed",
                        "complete": False,
                        "error_type": "FrozenInventoryIdentifiersMismatch",
                    }
                    atomic_json(manifest_path, result)
            results.append(
                {
                    "shard": shard,
                    "manifest_path": str(manifest_path),
                    "status": result["status"],
                    "complete": result["complete"],
                    "records_reported": result.get("records_reported"),
                    "records_saved": result["records_saved"],
                    "readable_body_count": result["readable_body_count"],
                    "raw_response_pages": result.get("raw_response_pages", 0),
                    "error_type": result.get("error_type"),
                }
            )
            if not old.get("complete"):
                progressed += 1
            receipt = {
                "schema_version": "diet-corpus-receipt/v1",
                "plan_sha256": digest,
                "run_id": plan["run_id"],
                "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "planned_shards": len(plan["shards"]),
                "inspected_shards": len(results),
                "complete_shards": sum(r["complete"] for r in results),
                "records_saved": sum(r["records_saved"] for r in results),
                "readable_body_count": sum(r["readable_body_count"] for r in results),
                "raw_response_pages": sum(r["raw_response_pages"] for r in results),
                "elapsed_seconds_this_run": round(time.monotonic() - started, 3),
                "corpus_complete": len(results) == len(plan["shards"])
                and all(r["complete"] for r in results),
                "scope_complete": False,
                "results": results,
            }
            atomic_json(receipt_path, receipt)
            if result["status"] == "failed":
                break
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="固定した会期・院の取得計画を有限実行")
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--max-shards", type=int, default=3)
    parser.add_argument("--pages-per-shard", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.rounds <= 10:
        parser.error("--rounds must be between 1 and 10")
    for _ in range(args.rounds):
        result = collect_corpus(
            args.plan,
            material_root=args.material_root,
            max_shards=args.max_shards,
            pages_per_shard=args.pages_per_shard,
        )
        if result["corpus_complete"] or any(
            r["status"] == "failed" for r in result["results"]
        ):
            break
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "results"}, ensure_ascii=False
        )
    )
    return 1 if any(r["status"] == "failed" for r in result["results"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
