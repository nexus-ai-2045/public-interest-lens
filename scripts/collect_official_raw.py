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
    from .path_guard import inside_without_links
    from .register_external_material import validate_task_id
except ImportError:
    from official_raw import atomic_json, capture_url, readback
    from path_guard import inside_without_links
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
        directives = [line.split("#", 1)[0].strip() for line in text.splitlines()]
        has_user_agent = any(
            line.partition(":")[0].strip().lower() == "user-agent"
            and bool(line.partition(":")[2].strip())
            for line in directives
        )
        if (
            receipt["status"] == 200
            and has_user_agent
            and "<html" not in text.lower()
        ):
            robots = RobotFileParser()
            robots.parse(text.splitlines())
            robots_status = "parsed"
        elif receipt["status"] in (404, 410):
            robots_status = "no_rules"
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


def _robots_allow(robots, robots_status, url):
    if robots_status == "no_rules":
        return True
    return (
        robots_status == "parsed"
        and robots is not None
        and robots.can_fetch("public-interest-lens", url)
    )


def stop_status(robots, robots_status, url):
    """本文取得を止めるときの結果名。未確認や障害を明示的な禁止と混ぜない。"""
    if _robots_allow(robots, robots_status, url):
        return None
    if robots_status == "parsed":
        return "robots_disallowed"
    if robots_status == "access_blocked":
        return "robots_access_blocked"
    if robots_status == "unavailable_stop":
        return "robots_tool_error"
    return "robots_unconfirmed"


def collect_plan(
    plan_path: Path, *, material_root: Path, limit: int = 25, workers: int = 2
) -> dict:
    if not 1 <= limit <= 100 or not 1 <= workers <= 2:
        raise ValueError("finite limit 1..100 and workers 1..2 required")
    plan_path = plan_path.resolve(strict=True)
    local = material_root.parent.resolve()
    if local.name != ".local" or not plan_path.is_relative_to(local):
        raise ValueError("plan must be in the same private .local as raw storage")
    control = local / "full-acquisition"
    if control.is_symlink() or inside_without_links(local, control) is None:
        raise ValueError("batch directory escaped private root")
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
    batch_dir = control / "batches" / plan["run_id"]
    if batch_dir.is_symlink() or inside_without_links(local, batch_dir) is None:
        raise ValueError("batch directory escaped private root")
    for item in items:
        item_path = batch_dir / "items" / f"{item['id']}.json"
        item_tmp = item_path.with_suffix(".json.tmp")
        if (
            item_path.is_symlink()
            or item_tmp.is_symlink()
            or inside_without_links(local, item_path) is None
            or inside_without_links(local, item_tmp) is None
        ):
            raise ValueError("item result escaped batch directory")
        for attempt in (1, 2, 3):
            task_dir = material_root / f"{plan['run_id']}-{item['id']}-a{attempt}"
            if task_dir.is_symlink() or inside_without_links(local, task_dir) is None:
                raise ValueError("registration escaped private root")
    checkpoint_path = batch_dir / "checkpoint.json"
    manifest_path = batch_dir / "manifest.json"
    for target in (
        checkpoint_path,
        checkpoint_path.with_suffix(".json.tmp"),
        manifest_path,
        manifest_path.with_suffix(".json.tmp"),
    ):
        if target.is_symlink() or inside_without_links(local, target) is None:
            raise ValueError("json destination escaped private root")
    digest = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    saved = (
        json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint_path.exists()
        else {}
    )
    if saved and saved.get("plan_sha256") != digest:
        raise ValueError("frozen plan changed; use a new batch identifier")
    outcomes = list(saved.get("outcomes", []))
    plan_by_id = {item["id"]: item for item in items}
    for old in outcomes:
        outcome_id = old.get("id")
        expected = plan_by_id.get(outcome_id) if isinstance(outcome_id, str) else None
        if expected is None:
            raise ValueError("checkpoint outcome is not in the frozen plan")
        validate_task_id(outcome_id)
        receipt = old.get("receipt")
        if (
            old.get("url") != expected["url"]
            or old.get("kind") != expected["kind"]
            or (receipt is not None and receipt.get("url") != expected["url"])
        ):
            raise ValueError("checkpoint outcome does not match the frozen plan")
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
            gate = stop_status(robots, robots_status, item["url"])
            if item.get("kind") != "robots" and gate:
                outcome = {
                    **item,
                    "status": gate,
                    "robots_status": robots_status,
                }
                receipt_path = (
                    control / "receipts" / f"{plan['run_id']}-{item['id']}.json"
                )
                if receipt_path.exists():
                    existing = json.loads(receipt_path.read_text(encoding="utf-8"))
                    if (
                        existing.get("url") != item["url"]
                        or existing.get("method", "GET") != "GET"
                    ):
                        raise ValueError("task receipt URL collision")
                    readback(existing, material_root)
                    outcome["receipt"] = existing
                group_outcomes.append(outcome)
                atomic_json(batch_dir / "items" / f"{item['id']}.json", outcome, root=local)
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
                if item.get("kind") == "robots" and robots_status == "no_rules":
                    item_status = "no_rules"
                elif receipt["status"] == 200:
                    item_status = "saved"
                else:
                    item_status = "http_failed"
                outcome = {
                    **item,
                    "status": item_status,
                    "receipt": receipt,
                    "references": detail,
                    "robots_status": robots_status,
                }
            except (OSError, ValueError, KeyError) as error:
                if "escaped" in str(error):
                    raise
                outcome = {
                    **item,
                    "status": "failed",
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
                if item.get("kind") == "robots":
                    robots, robots_status = robot_policy(outcome, material_root)
            group_outcomes.append(outcome)
            atomic_json(batch_dir / "items" / f"{item['id']}.json", outcome, root=local)
        return group_outcomes

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for group_result in pool.map(capture_group, groups.values()):
            outcomes.extend(group_result)
            atomic_json(checkpoint_path, {"plan_sha256": digest, "outcomes": outcomes}, root=local)
    successful = [o for o in outcomes if o["status"] == "saved"]
    completed = [o for o in outcomes if o["status"] in {"saved", "no_rules"}]
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
        "failed_items": len(outcomes) - len(completed),
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
        "stop_counts": {
            name: sum(outcome["status"] == name for outcome in outcomes)
            for name in (
                "robots_disallowed",
                "robots_unconfirmed",
                "robots_tool_error",
                "robots_access_blocked",
            )
        },
        "outcomes": outcomes,
    }
    atomic_json(manifest_path, result, root=local)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "固定した公式URL一覧を有限バッチで保存する。"
            "明示的な禁止、取得規則未確認、ツール障害、到達拒否は別の結果にし、"
            "未確認の間は本文へ通信しない"
        )
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
