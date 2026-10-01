"""参議院本会議の明示された押しボタン投票ページを有限取得する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .fetch_diet_minutes import _verified_material
from .register_external_material import register_local_material

MAX_BYTES = 2 * 1024 * 1024
CANONICAL = {
    "221-53": "https://www.sangiin.go.jp/japanese/touhyoulist/221/221-0710-v001.htm",
    "221-41": "https://www.sangiin.go.jp/japanese/touhyoulist/221/221-0713-v004.htm",
    "221-26": "https://www.sangiin.go.jp/japanese/touhyoulist/221/221-0612-v009.htm",
}
URL_TO_BILL = {url: bill for bill, url in CANONICAL.items()}
DATE_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
TOTAL_RE = re.compile(r"投票総数\s*(\d+).*?賛成票\s*(\d+).*?反対票\s*(\d+)", re.S)


def _text(parts: list[str]) -> str:
    return " ".join("".join(parts).split())


class _VoteHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, set[str]]] = []
        self.capture: dict | None = None
        self.current_party = ""
        self.current_party_counts = ""
        self.factions: list[dict] = []
        self.header = ""
        self.title = ""
        self.total_text = ""
        self.rows: list[dict] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = set((dict(attrs).get("class") or "").split())
        self.stack.append((tag, classes))
        if tag == "li" and "giin" in classes:
            self.capture = {"line": self.getpos()[0], "parts": [], "name": [],
                            "yes": [], "no": [], "novote": []}
        elif tag in {"h2", "h3", "h4", "dt", "dd"}:
            if (tag == "h2" and "kaiji_nichiji" in classes
                    or tag == "h3" and "tohyosousu" in classes
                    or tag == "h4" and "party" in classes
                    or tag == "dt" and "party" in classes
                    or tag == "dd" and any("ankenmei" in c for _, c in self.stack)):
                self.capture = {"tag": tag, "parts": []}

    def handle_data(self, data: str) -> None:
        if self.capture is None:
            return
        self.capture["parts"].append(data)
        if "line" not in self.capture:
            return
        classes = set().union(*(c for _, c in self.stack)) if self.stack else set()
        for key, marker in (("name", "names"), ("yes", "pros"),
                            ("no", "cons"), ("novote", "novote")):
            if marker in classes:
                self.capture[key].append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.capture is not None:
            if tag == "li" and "line" in self.capture:
                item = self.capture
                self.rows.append({"party": self.current_party,
                                  "party_counts": self.current_party_counts,
                                  "name": _text(item["name"]),
                                  "yes": _text(item["yes"]), "no": _text(item["no"]),
                                  "novote": _text(item["novote"]),
                                  "rowText": _text(item["parts"]), "line": item["line"]})
                self.capture = None
            elif self.capture.get("tag") == tag:
                value = _text(self.capture["parts"])
                if tag == "h2":
                    self.header = value
                elif tag == "h3":
                    self.total_text = value
                elif tag == "h4":
                    self.current_party = value
                    self.current_party_counts = ""
                elif tag == "dt":
                    self.current_party_counts = value
                    self.factions.append({"partyText": self.current_party,
                                          "publishedCountText": value})
                elif tag == "dd":
                    self.title = value
                self.capture = None
        if self.stack:
            self.stack.pop()


def parse_vote_page(payload: bytes, *, bill_id: str, title: str, url: str) -> dict:
    """引用行を保持し、個別票の公表総数との整合を別状態で返す。"""
    if URL_TO_BILL.get(url) != bill_id or not payload or len(payload) > MAX_BYTES:
        raise ValueError("vote URL, bill identifier or response size mismatch")
    parser = _VoteHTML()
    parser.feed(payload.decode("utf-8", errors="strict"))
    if "第221回国会" not in parser.header or not title or title not in parser.title:
        raise ValueError("vote session or bill title mismatch")
    match = DATE_RE.search(parser.header)
    counts = TOTAL_RE.search(parser.total_text)
    if match is None or counts is None:
        raise ValueError("vote date or totals missing")
    event = date(*map(int, match.groups())).isoformat()
    slug = url.rsplit("/", 1)[-1]
    if event != f"2026-{slug[4:6]}-{slug[6:8]}":
        raise ValueError("vote date does not match official URL")
    total, yes, no = map(int, counts.groups())
    if total == 0 or yes + no != total:
        raise ValueError("published vote totals inconsistent")
    structured: list[dict] = []
    invalid = False
    diagnostics: list[dict] = []
    names = [_text([row["name"]]).replace(" ", "") for row in parser.rows]
    for row in parser.rows:
        marks = [row["yes"] == "賛成", row["no"] == "反対", row["novote"].replace(" ", "") == "投票なし"]
        unknown_mark = (row["yes"] not in {"", "賛成"} or row["no"] not in {"", "反対"}
                        or row["novote"].replace(" ", "") not in {"", "投票なし"})
        name_key = _text([row["name"]]).replace(" ", "")
        if (not name_key or not row["party"] or sum(marks) != 1 or unknown_mark
                or names.count(name_key) != 1):
            invalid = True
            diagnostics.append({**row, "reason": "missing_ambiguous_or_duplicate_member"})
            continue
        structured.append({"partyText": row["party"],
                           "partyPublishedCountText": row["party_counts"],
                           "nameText": row["name"],
                           "voteText": ("賛成" if marks[0] else "反対" if marks[1]
                                        else "投票なし" if marks[2] else "不明"),
                           "rowText": row["rowText"], "sourceLine": row["line"]})
    yes_rows = sum(row["voteText"] == "賛成" for row in structured)
    no_rows = sum(row["voteText"] == "反対" for row in structured)
    vote_matched = yes_rows == yes and no_rows == no
    faction_checks = []
    for faction in parser.factions:
        party_rows = [row for row in structured if row["partyText"] == faction["partyText"]]
        member_count = re.search(r"[（(]\s*(\d+)\s*名\s*[）)]", faction["partyText"])
        faction_votes = re.search(r"賛成票\s*(\d+)\s*反対票\s*(\d+)", faction["publishedCountText"])
        matched = (member_count is not None and faction_votes is not None
                   and len(party_rows) == int(member_count[1])
                   and sum(r["voteText"] == "賛成" for r in party_rows) == int(faction_votes[1])
                   and sum(r["voteText"] == "反対" for r in party_rows) == int(faction_votes[2]))
        faction_checks.append({**faction, "rowsConfirmed": matched})
    faction_names = [f["partyText"] for f in parser.factions]
    complete = (bool(structured) and not invalid and vote_matched and bool(faction_checks)
                and len(faction_names) == len(set(faction_names))
                and all(f["rowsConfirmed"] for f in faction_checks)
                and all(r["partyText"] in faction_names for r in structured))
    available = complete
    return {"billId": bill_id, "title": title, "eventDate": event,
            "session": 221, "agendaText": parser.title, "publishedTotals":
            {"total": total, "yes": yes, "no": no},
            "rowCounts": {"yes": yes_rows, "no": no_rows,
                          "noVote": sum(row["voteText"] == "投票なし" for row in structured)},
            "factions": parser.factions,
            "voteCountMatched": vote_matched, "allPublishedRowsConfirmed": complete,
            "factionChecks": faction_checks, "diagnosticRows": diagnostics,
            "available": available, "rows": structured,
            "unavailableReason": None if available else "member_rows_missing_or_inconsistent"}


def _default_fetch(url: str) -> bytes:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, message, headers, new_url):
            raise ValueError("redirect rejected")

    request = urllib.request.Request(url, headers={"User-Agent": "public-interest-lens/0.1"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("response status or URL mismatch")
            if "text/html" not in response.headers.get("Content-Type", "").lower():
                raise ValueError("response is not HTML")
            payload = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as error:
        raise ValueError("HTTP response rejected") from error
    if not payload or len(payload) > MAX_BYTES:
        raise ValueError("response empty or too large")
    return payload


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _local_root(path: Path) -> Path:
    path = path.resolve()
    roots = [parent for parent in (path, *path.parents) if parent.name == ".local"]
    if len(roots) != 1:
        raise ValueError("path must be inside one repository .local")
    return roots[0]


def _registered(record_path: Path, material_root: Path, url: str) -> tuple[dict, bytes]:
    resolved = record_path.resolve(strict=True)
    if not resolved.is_relative_to(material_root.resolve()):
        raise ValueError("registered material path escapes storage root")
    if resolved.stat().st_size > MAX_BYTES:
        raise ValueError("registered metadata too large")
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    digest = raw.get("sha256")
    size = raw.get("bytes")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or type(size) is not int or not 0 < size <= MAX_BYTES:
        raise ValueError("registered material metadata missing")
    record = _verified_material(record_path, roots=(material_root,), url=url,
                                digest=digest, expected_bytes=size)
    if record.get("content_verification") != "unverified":
        raise ValueError("unexpected content verification state")
    payload = (resolved.parent / record["saved_filename"]).read_bytes()
    return record, payload


def read_registered_votes(record_path: Path, *, material_root: Path, bill_id: str,
                          title: str, url: str, as_of: str | None = None) -> dict:
    """明示した非公開登録原本をコピー・通信・書込みなしで再検証します。"""
    _local_root(material_root)
    if URL_TO_BILL.get(url) != bill_id:
        raise ValueError("canonical vote URL and bill identifier required")
    record, payload = _registered(record_path, material_root, url)
    parsed = parse_vote_page(payload, bill_id=bill_id, title=title, url=url)
    if as_of is not None:
        cutoff = date.fromisoformat(as_of)
        try:
            start = cutoff.replace(year=cutoff.year - 4)
        except ValueError:
            start = cutoff.replace(year=cutoff.year - 4, day=28)
        if not start <= date.fromisoformat(parsed["eventDate"]) <= cutoff:
            raise ValueError("vote outside recent four-year scope")
    return {**parsed, "sourceUrl": url, "sha256": record["sha256"],
            "observedAt": record["observed_at"], "recordPath": str(record_path.resolve()),
            "contentVerification": "unverified", "confirmedActionEvidence": 0}


def collect_votes(urls: list[str], *, source_root: Path, output_dir: Path,
                  material_root: Path, run_id: str, fetch_bytes: Callable[[str], bytes] = _default_fetch,
                  sleep: Callable[[float], None] = time.sleep,
                  clock: Callable[[], datetime] = lambda: datetime.now().astimezone()) -> dict:
    """登録済み原本を先に再検証し、未完了のURLだけ逐次取得する。"""
    if not 1 <= len(urls) <= 3 or len(set(urls)) != len(urls) or any(url not in URL_TO_BILL for url in urls):
        raise ValueError("one to three distinct canonical official vote URLs required")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}", run_id):
        raise ValueError("invalid run identifier")
    source_file = source_root.resolve(strict=True) / "current.json"
    local = _local_root(source_file)
    if _local_root(output_dir) != local or _local_root(material_root) != local:
        raise ValueError("source, output and material paths must share the same .local")
    if output_dir.resolve() == material_root.resolve() or output_dir.resolve().is_relative_to(material_root.resolve()) or material_root.resolve().is_relative_to(output_dir.resolve()):
        raise ValueError("output and material roots must be separate")
    source = json.loads(source_file.read_text(encoding="utf-8"))
    cutoff = date.fromisoformat(source.get("asOf", ""))
    try:
        recent_start = cutoff.replace(year=cutoff.year - 4)
    except ValueError:
        recent_start = cutoff.replace(year=cutoff.year - 4, day=28)
    held = source.get("held")
    if not isinstance(held, list):
        raise ValueError("bill source must contain held list")
    by_id = {item.get("billId"): item for item in held if isinstance(item, dict)}
    if len(by_id) != len(held):
        raise ValueError("duplicate or invalid bill identifier")
    results: list[dict] = []
    last_request_finished: float | None = None
    for url in urls:
        bill_id = URL_TO_BILL[url]
        bill = by_id.get(bill_id)
        if not isinstance(bill, dict) or not isinstance(bill.get("title"), str) or not bill["title"]:
            raise ValueError("selected bill missing from source")
        old = urlparse(bill.get("voteUrl", ""))
        if (old.scheme != "https" or old.hostname != "www.sangiin.go.jp"
                or old.port is not None or old.username or old.password or old.query or old.fragment
                or old.path != urlparse(url).path.replace("/touhyoulist/", "/joho1/kousei/vote/")):
            raise ValueError("bill vote alias mismatch")
        task_id = f"diet-vote-{bill_id}-{run_id}"
        checkpoint = output_dir / f"{bill_id}.json"
        records = sorted((material_root / task_id).glob("*/record.json"))
        if (material_root / task_id).exists() and any((material_root / task_id).iterdir()) and not records:
            raise ValueError("partial registered attempt preserved; use a new run identifier")
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            record_path = Path(saved.get("recordPath", ""))
            if record_path not in records or saved.get("sourceUrl") != url:
                raise ValueError("completed checkpoint differs from selected source")
            record, payload = _registered(record_path, material_root, url)
            if saved.get("sha256") != record["sha256"] or saved.get("observedAt") != record["observed_at"]:
                raise ValueError("completed checkpoint differs from registered original")
        elif records:
            matching = []
            for record_path in records:
                try:
                    record, payload = _registered(record_path, material_root, url)
                    matching.append((record_path, record, payload))
                except (OSError, ValueError, KeyError, TypeError):
                    continue
            if len(matching) != 1:
                raise ValueError("ambiguous registered source; preserve partial state")
            record_path, record, payload = matching[0]
        else:
            for attempt in range(3):
                if last_request_finished is not None:
                    sleep(max(0.0, 3.0 - (time.monotonic() - last_request_finished)))
                try:
                    payload = fetch_bytes(url)
                    last_request_finished = time.monotonic()
                    break
                except OSError:
                    last_request_finished = time.monotonic()
                    if attempt == 2:
                        raise
            if not payload or len(payload) > MAX_BYTES:
                raise ValueError("response empty or too large")
            observed = clock()
            if observed.tzinfo is None or observed.utcoffset() is None:
                raise ValueError("observation clock must include timezone")
            stage = output_dir / "staging" / f"{bill_id}-{hashlib.sha256(payload).hexdigest()[:12]}.html"
            stage.parent.mkdir(parents=True, exist_ok=True)
            if stage.exists() and stage.read_bytes() != payload:
                raise ValueError("staging collision")
            stage.write_bytes(payload)
            record_path = register_local_material(input_path=stage, source_url=url,
                task_id=task_id, title="参議院本会議投票結果", purpose="有限の個別投票資料取得",
                storage_root=material_root, observed_at=observed.isoformat(timespec="seconds"))
            record, payload = _registered(record_path, material_root, url)
        parsed = parse_vote_page(payload, bill_id=bill_id, title=bill["title"], url=url)
        if not recent_start <= date.fromisoformat(parsed["eventDate"]) <= cutoff:
            raise ValueError("vote outside recent four-year scope")
        saved = {**parsed, "sourceUrl": url, "sourceAlias": bill["voteUrl"],
                 "sha256": record["sha256"], "observedAt": record["observed_at"],
                 "recordPath": str(record_path), "contentVerification": "unverified"}
        if checkpoint.exists():
            if json.loads(checkpoint.read_text(encoding="utf-8")) != saved:
                raise ValueError("completed checkpoint content mismatch")
        else:
            _atomic_json(checkpoint, saved)
        results.append(saved)
    summary = {"schemaVersion": "sangiin-votes/v1", "runId": run_id,
               "sourceRecords": len(results), "structuredAvailable": sum(item["available"] for item in results),
               "confirmedActionEvidence": 0,
               "targets": [{"billId": item["billId"], "status": "available" if item["available"] else "unavailable",
                            "sha256": item["sha256"], "observedAt": item["observedAt"]} for item in results]}
    _atomic_json(output_dir / "manifest.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="明示した参議院投票ページ最大3件を非公開原本へ登録")
    parser.add_argument("--url", action="append", required=True)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--record-path", type=Path)
    parser.add_argument("--bill-id")
    parser.add_argument("--title")
    parser.add_argument("--as-of")
    args = parser.parse_args()
    if args.record_path:
        if len(args.url) != 1 or not args.bill_id or not args.title or args.source_root or args.output_dir or args.run_id:
            parser.error("offline reuse requires one URL, bill-id and title; collection options prohibited")
        result = read_registered_votes(args.record_path, material_root=args.material_root,
                    bill_id=args.bill_id, title=args.title, url=args.url[0], as_of=args.as_of)
        print(json.dumps({"available": result["available"],
                          "voteCountMatched": result["voteCountMatched"],
                          "allPublishedRowsConfirmed": result["allPublishedRowsConfirmed"],
                          "rowCounts": result["rowCounts"], "confirmedActionEvidence": 0}, ensure_ascii=False))
        return 0
    if not args.source_root or not args.output_dir or not args.run_id:
        parser.error("collection requires source-root, output-dir and run-id")
    result = collect_votes(args.url, source_root=args.source_root, output_dir=args.output_dir,
                           material_root=args.material_root, run_id=args.run_id)
    print(json.dumps({"sourceRecords": result["sourceRecords"],
                      "structuredAvailable": result["structuredAvailable"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
