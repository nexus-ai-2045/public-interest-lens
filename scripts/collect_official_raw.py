from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

try:
    from .official_raw import atomic_json, capture_url, readback
    from .register_external_material import validate_task_id
except ImportError:
    from official_raw import atomic_json, capture_url, readback
    from register_external_material import validate_task_id


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        for key, value in attrs:
            if value and (
                (tag in {"a", "link"} and key == "href")
                or (tag in {"iframe", "frame", "source", "img"} and key == "src")
                or (tag == "object" and key == "data")
                or (tag == "form" and key == "action")
                or (
                    tag == "option"
                    and key == "value"
                    and (value.startswith(("/", "https://")) or ".htm" in value)
                )
            ):
                self.urls.append(value)


def references(payload: bytes, receipt: dict) -> dict:
    if "html" not in receipt["headers"].get("content-type", ""):
        return {"links": [], "decode_status": "not_html"}
    charset = re.search(
        r"charset=[\"']?([\w-]+)", receipt["headers"].get("content-type", ""), re.I
    )
    meta = re.search(rb"charset=[\"']?([\w-]+)", payload[:4096], re.I)
    encodings = [
        charset[1] if charset else meta[1].decode("ascii") if meta else "utf-8",
        "cp932",
    ]
    text = None
    for encoding in dict.fromkeys(encodings):
        try:
            text = payload.decode(encoding, errors="strict")
            break
        except (LookupError, UnicodeDecodeError):
            continue
    if text is None:
        return {"links": [], "decode_status": "unreadable"}
    parser = Links()
    parser.feed(text)
    links = sorted(
        {
            urldefrag(urljoin(receipt["url"], href))[0]
            for href in parser.urls
            if urlsplit(urljoin(receipt["url"], href)).scheme in {"http", "https"}
        }
    )
    return {"links": links, "decode_status": "decoded", "charset": encoding}


def robot_policy(outcome, material_root):
    receipt = outcome.get("receipt")
    robots = None
    robots_status = "unconfirmed"
    if receipt:
        text = readback(receipt, material_root).decode("utf-8", errors="replace")
        if (
            receipt["status"] == 200
            and "user-agent:" in text.lower()
            and "<html" not in text.lower()
        ):
            robots = RobotFileParser()
            robots.parse(text.splitlines())
            robots_status = "parsed"
        elif (
            receipt["status"] not in (200, 404, 410)
            and not 300 <= receipt["status"] < 400
        ):
            robots = RobotFileParser()
            robots.parse(["User-agent: *", "Disallow: /"])
            robots_status = "access_blocked"
    else:
        robots = RobotFileParser()
        robots.parse(["User-agent: *", "Disallow: /"])
        robots_status = "unavailable_stop"
    return robots, robots_status


def collect_plan(
    plan_path: Path, *, material_root: Path, limit: int = 25, workers: int = 2
) -> dict:
    if not 1 <= limit <= 100 or not 1 <= workers <= 2:
        raise ValueError("finite limit 1..100 and workers 1..2 required")
    plan_path = plan_path.resolve(strict=True)
    local = material_root.parent.resolve()
    if local.name != ".local" or not plan_path.is_relative_to(local):
        raise ValueError("plan must be in the same private .local as raw storage")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    items = plan["items"]
    validate_task_id(plan["run_id"])
    for item in items:
        validate_task_id(item["id"])
        validate_task_id(f"{plan['run_id']}-{item['id']}-a3")
    ids = [item["id"] for item in items]
    urls = [item["url"] for item in items]
    if len(ids) != len(set(ids)) or len(urls) != len(set(urls)):
        raise ValueError("plan identifiers and URLs must be unique")
    control = local / "full-acquisition"
    batch_dir = control / "batches" / plan["run_id"]
    if not control.resolve().is_relative_to(
        local
    ) or not batch_dir.resolve().is_relative_to(control.resolve()):
        raise ValueError("batch directory escaped private root")
    for item in items:
        if (
            not (batch_dir / "items" / f"{item['id']}.json")
            .resolve()
            .is_relative_to(batch_dir.resolve())
        ):
            raise ValueError("item result escaped batch directory")
    digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    checkpoint_path = batch_dir / "checkpoint.json"
    saved = (
        json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint_path.exists()
        else {}
    )
    if saved and saved.get("plan_sha256") != digest:
        raise ValueError("frozen plan changed; use a new batch identifier")
    outcomes = list(saved.get("outcomes", []))
    for old in outcomes:
        if old.get("receipt"):
            readback(old["receipt"], material_root)
    done = {o["id"] for o in outcomes}
    remaining = sorted(
        [item for item in items if item["id"] not in done],
        key=lambda item: item.get("kind") != "robots",
    )[:limit]
    hosts = set(plan["allowed_hosts"])
    groups = {}
    for item in remaining:
        groups.setdefault(urlsplit(item["url"]).hostname, []).append(item)
    started = time.monotonic()
    observed_start = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def capture_group(group):
        group_outcomes = []
        robots = None
        robots_status = "unconfirmed"
        for old in outcomes:
            if (
                old.get("kind") == "robots"
                and urlsplit(old["url"]).hostname == urlsplit(group[0]["url"]).hostname
            ):
                robots, robots_status = robot_policy(old, material_root)
        for item in group:
            if item.get("kind") != "robots" and (
                robots_status != "parsed"
                or robots is None
                or not robots.can_fetch("public-interest-lens", item["url"])
            ):
                outcome = {
                    **item,
                    "status": "robots_disallowed",
                    "robots_status": robots_status,
                }
                group_outcomes.append(outcome)
                atomic_json(batch_dir / "items" / f"{item['id']}.json", outcome)
                continue
            try:
                receipt = capture_url(
                    item["url"],
                    material_root=material_root,
                    control_root=control,
                    task_id=f"{plan['run_id']}-{item['id']}",
                    title=item["title"],
                    allowed_hosts=hosts,
                )
                payload = readback(receipt, material_root)
                detail = (
                    references(payload, receipt) if receipt["status"] == 200 else {}
                )
                if item.get("kind") == "robots":
                    robots, robots_status = robot_policy(
                        {"receipt": receipt}, material_root
                    )
                outcome = {
                    **item,
                    "status": "saved" if receipt["status"] == 200 else "http_failed",
                    "receipt": receipt,
                    "references": detail,
                    "robots_status": robots_status,
                }
            except (OSError, ValueError, KeyError) as error:
                outcome = {
                    **item,
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                if item.get("kind") == "robots":
                    robots, robots_status = robot_policy(outcome, material_root)
            group_outcomes.append(outcome)
            atomic_json(batch_dir / "items" / f"{item['id']}.json", outcome)
        return group_outcomes

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for group_result in pool.map(capture_group, groups.values()):
            outcomes.extend(group_result)
            atomic_json(checkpoint_path, {"plan_sha256": digest, "outcomes": outcomes})
    successful = [o for o in outcomes if o["status"] == "saved"]
    receipts = [o["receipt"] for o in outcomes if o.get("receipt")]
    result = {
        "schema_version": "official-raw-batch/v1",
        "run_id": plan["run_id"],
        "plan_sha256": digest,
        "observed_start": observed_start,
        "observed_end": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_seconds_this_run": round(time.monotonic() - started, 3),
        "inventory_items": len(items),
        "processed_items": len(outcomes),
        "successful_raw_responses": len(successful),
        "raw_saved_including_http_failures": len(receipts),
        "raw_bytes": sum(r["bytes"] for r in receipts),
        "failed_items": len(outcomes) - len(successful),
        "pending_items": len(items) - len(outcomes),
        "index_pages_saved": sum(o.get("kind") == "index" for o in successful),
        "document_candidates_saved": sum(
            o.get("kind") == "document" for o in successful
        ),
        "unfetched_references": len(
            {
                url
                for o in successful
                for url in o.get("references", {}).get("links", [])
            }
            - {o["url"] for o in successful}
        ),
        "corpus_complete": False,
        "outcomes": outcomes,
    }
    atomic_json(batch_dir / "manifest.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="固定した公式URL一覧を有限バッチで保存"
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    result = collect_plan(
        args.plan,
        material_root=args.material_root,
        limit=args.limit,
        workers=args.workers,
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "outcomes"},
            ensure_ascii=False,
        )
    )
    return 1 if result["failed_items"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
