from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

try:
    from .official_raw import atomic_json, capture_url, readback, host_lock
    from .collect_official_raw import references, robot_policy
    from .register_external_material import validate_task_id
except ImportError:
    from official_raw import atomic_json, capture_url, readback, host_lock
    from collect_official_raw import references, robot_policy
    from register_external_material import validate_task_id


HOST = "www.sangiin.go.jp"
PREFIXES = (
    "/japanese/joho1/kousei/",
    "/japanese/touhyoulist/",
    "/japanese/giin/",
    "/japanese/joho1/kaigirok/",
    "/jpn/gianjoho/",
    "/jpn/kaigijoho/",
    "/jpn/gikai/",
    "/jpn/shiryo/chousa/",
    "/jpn/shiryo/s_gaiyo/",
)
ATTACHMENTS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".zip",
    ".txt",
    ".xml",
    ".json",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".rtf",
}
VIDEO = {".mp4", ".m3u8", ".mov", ".wmv"}
INDEX_NAMES = {
    "index.html",
    "index.htm",
    "gian.htm",
    "iinkai.htm",
    "vote_ind.htm",
    "syuisyo.htm",
    "seigan.htm",
    "koho.htm",
    "shitsugi_ind.html",
}


def classify(url: str) -> tuple[str, str]:
    p = urlsplit(url)
    if (
        p.scheme != "https"
        or p.hostname != HOST
        or p.username
        or p.password
        or p.port not in (None, 443)
    ):
        return "external_reference", "external"
    suffix = Path(p.path).suffix.lower()
    if suffix in VIDEO:
        return "video_reference", "video"
    if (
        suffix in {".png", ".gif", ".jpg", ".jpeg", ".webp", ".svg"}
        and p.path.startswith(PREFIXES)
        and not any(
            token in Path(p.path).name.lower()
            for token in ("logo", "icon", "favicon", "banner")
        )
    ):
        return "attachment", "attachment"
    if suffix in {
        ".css",
        ".js",
        ".ico",
        ".svg",
        ".png",
        ".gif",
        ".jpg",
        ".jpeg",
        ".webp",
    }:
        return "excluded_navigation_asset", "asset"
    if suffix in ATTACHMENTS:
        return "attachment", "attachment"
    if (
        not p.path.startswith(PREFIXES)
        or "/search/" in p.path
        or p.path.endswith(".cgi")
    ):
        return "outside_declared_scope", "reference"
    if "/touhyoulist/" in p.path:
        family = "votes"
    elif "/syuisyo/" in p.path:
        family = "questions_answers"
    elif "/seigan/" in p.path:
        family = "petitions"
    elif "/gian/" in p.path:
        family = "bills"
    elif "/ketsugi/" in p.path:
        family = "resolutions"
    elif "/giin/" in p.path:
        family = "members"
    elif "/koho/" in p.path:
        family = "bulletins"
    elif "/shitsugi/" in p.path:
        family = "questions_topics"
    else:
        family = "committee_reports"
    return "material", family


def successful_cache(root: Path) -> dict:
    result = {}
    paths = [(p, "outcomes") for p in (root / "batches").glob("*/manifest.json")]
    paths.extend((p, "nodes") for p in (root / "sangiin").glob("*/checkpoint.json"))
    for path, key in sorted(paths):
        rows = json.loads(path.read_text(encoding="utf-8")).get(key, [])
        rows = rows.values() if isinstance(rows, dict) else rows
        for o in rows:
            receipt = o.get("receipt")
            if (
                o.get("status") != "saved"
                or not receipt
                or receipt["status"] != 200
                or receipt.get("method", "GET") != "GET"
            ):
                continue
            url = receipt["url"]
            if urlsplit(url).hostname != HOST:
                continue
            if url not in result or receipt["observed_at"] > result[url]["observed_at"]:
                result[url] = receipt
    return result


def role(url: str) -> str:
    kind, _ = classify(url)
    if kind == "attachment":
        return "attachment"
    name = Path(urlsplit(url).path).name
    return (
        "index"
        if name in INDEX_NAMES or name.endswith(("_index.html", "_ind.html"))
        else "detail_candidate"
    )


def priority(url: str, seed_urls: set[str]) -> tuple:
    sessions = [int(n) for n in re.findall(r"/(\d{3})/", urlsplit(url).path)]
    return (
        0 if url in seed_urls else 1,
        1 if role(url) == "index" else 0,
        -max(sessions, default=0),
        url,
    )


def collect(
    seed_path: Path, material_root: Path, run_id: str, max_requests: int
) -> dict:
    validate_task_id(run_id)
    if not 1 <= max_requests <= 100:
        raise ValueError("bounded request limit 1..100 required")
    local = material_root.parent.resolve()
    seed_path = seed_path.resolve(strict=True)
    if local.name != ".local" or not seed_path.is_relative_to(local):
        raise ValueError("seed and material must share private .local")
    root = local / "full-acquisition"
    output = root / "sangiin" / run_id
    if not output.resolve().is_relative_to(
        root.resolve()
    ) or not root.resolve().is_relative_to(local):
        raise ValueError("collection output escaped private root")
    seed = json.loads(seed_path.read_text(encoding="utf-8"))
    if any(urlsplit(o["url"]).hostname != HOST for o in seed["outcomes"]):
        raise ValueError("seed escaped official source host")
    if any(
        o.get("kind") != "robots"
        and classify(o["url"])[0] not in {"material", "attachment"}
        for o in seed["outcomes"]
    ):
        raise ValueError("seed escaped declared material scope")
    digest = hashlib.sha256(seed_path.read_bytes()).hexdigest()
    policy_rows = [
        o
        for o in seed["outcomes"]
        if o.get("kind") == "robots" and urlsplit(o["url"]).hostname == HOST
    ]
    if len(policy_rows) != 1:
        raise ValueError("one saved robots snapshot required")
    robots, policy_status = robot_policy(policy_rows[0], material_root)
    state_path = output / "checkpoint.json"
    started = time.monotonic()
    with host_lock(root, "sangiin-material-owner"):
        state = (
            json.loads(state_path.read_text(encoding="utf-8"))
            if state_path.exists()
            else {}
        )
        if state and state["seed_sha256"] != digest:
            raise ValueError("frozen seed changed")
        nodes = state.get("nodes", {})
        for url, node in nodes.items():
            if classify(url)[0] not in {"material", "attachment"}:
                raise ValueError("stored node escaped declared material scope")
            if node.get("receipt"):
                if node["receipt"]["url"] != url:
                    raise ValueError("stored node source URL mismatch")
                readback(node["receipt"], material_root)
            if node["status"] in {"failed", "robots_disallowed"} or (
                node["status"] == "http_failed"
                and node.get("receipt", {}).get("status") not in {404, 410}
            ):
                raise ValueError(
                    "blocked checkpoint preserved; investigate or use a new run"
                )
        edges = state.get("edges", [])
        frontier = state.get("frontier", [])
        if not state:
            frontier = [o["url"] for o in seed["outcomes"] if o.get("kind") != "robots"]
        if any(classify(url)[0] not in {"material", "attachment"} for url in frontier):
            raise ValueError("frontier escaped declared material scope")
        cache = successful_cache(root)
        seed_urls = {o["url"] for o in seed["outcomes"] if o.get("kind") != "robots"}
        for o in seed["outcomes"]:
            if o.get("receipt"):
                cache[o["url"]] = o["receipt"]
        edge_keys = {(e["parent"], e["url"]) for e in edges}
        requests = 0
        reused = 0
        while frontier:
            frontier.sort(key=lambda url: priority(url, seed_urls))
            url = frontier.pop(0)
            if url in nodes:
                continue
            if url not in cache and requests >= max_requests:
                frontier.insert(0, url)
                break
            kind, family = classify(url)
            if kind not in {"material", "attachment"}:
                raise ValueError("requested URL escaped declared material scope")
            if robots is not None and not robots.can_fetch("public-interest-lens", url):
                nodes[url] = {"status": "robots_disallowed", "family": family}
            else:
                receipt = None
                try:
                    if url in cache:
                        receipt = cache[url]
                        reused += 1
                    else:
                        requests += 1
                        receipt = capture_url(
                            url,
                            material_root=material_root,
                            control_root=root,
                            task_id=f"{run_id}-{hashlib.sha256(url.encode()).hexdigest()[:20]}",
                            title="参議院の公開資料原本",
                            allowed_hosts={HOST},
                        )
                    if receipt["url"] != url or receipt.get("method", "GET") != "GET":
                        raise ValueError(
                            "saved source or method differs from requested material"
                        )
                    payload = readback(receipt, material_root)
                    detail = (
                        references(payload, receipt)
                        if receipt["status"] == 200
                        else {"links": []}
                    )
                    nodes[url] = {
                        "status": (
                            "saved" if receipt["status"] == 200 else "http_failed"
                        ),
                        "family": family,
                        "kind": kind,
                        "role": "index" if url in seed_urls else role(url),
                        "receipt": receipt,
                    }
                    for child in detail["links"]:
                        child_kind, child_family = classify(child)
                        key = (url, child)
                        if key not in edge_keys:
                            edges.append(
                                {
                                    "parent": url,
                                    "url": child,
                                    "kind": child_kind,
                                    "family": child_family,
                                }
                            )
                            edge_keys.add(key)
                        if (
                            child_kind in {"material", "attachment"}
                            and child not in nodes
                            and child not in frontier
                        ):
                            frontier.append(child)
                except (OSError, ValueError, KeyError) as error:
                    nodes[url] = {
                        "status": "failed",
                        "family": family,
                        "error": str(error),
                    }
                    if receipt:
                        nodes[url]["receipt"] = receipt
            state = {
                "seed_sha256": digest,
                "nodes": nodes,
                "edges": edges,
                "frontier": frontier,
            }
            atomic_json(state_path, state)
            status = nodes[url]["status"]
            code = nodes[url].get("receipt", {}).get("status")
            if status != "saved" and not (
                status == "http_failed" and code in {404, 410}
            ):
                break
        states = Counter(n["status"] for n in nodes.values())
        result = {
            "schema_version": "sangiin-material-receipt/v1",
            "run_id": run_id,
            "seed_sha256": digest,
            "robots_status": policy_status,
            "known_urls": len(nodes) + len(frontier),
            "saved_urls": states["saved"],
            "failed_urls": len(nodes) - states["saved"],
            "pending_urls": len(frontier),
            "requests_this_run": requests,
            "reused_this_run": reused,
            "raw_bytes": sum(
                n["receipt"]["bytes"] for n in nodes.values() if n.get("receipt")
            ),
            "families": dict(
                Counter(n["family"] for n in nodes.values() if n["status"] == "saved")
            ),
            "roles_saved": dict(
                Counter(
                    n.get("role", "unclassified")
                    for n in nodes.values()
                    if n["status"] == "saved"
                )
            ),
            "reference_kinds": dict(Counter(e["kind"] for e in edges)),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "frontier_exhausted": not frontier,
            "source_complete": False,
            "body_readability_verified": False,
            "checkpoint": str(state_path),
        }
        atomic_json(output / "receipt.json", result)
        return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="参議院の定義済み資料群を原本保存し、未取得参照を有限列挙"
    )
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--max-requests", type=int, default=20)
    args = parser.parse_args()
    result = collect(args.seed, args.material_root, args.run_id, args.max_requests)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["failed_urls"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
