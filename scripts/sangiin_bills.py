"""参議院の明示された法案ページだけを取得し、未評価候補として保管する。"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.request
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlparse

from .register_external_material import register_local_material
from .fetch_diet_minutes import _verified_material

MAX_BYTES = 2 * 1024 * 1024
HOST = "www.sangiin.go.jp"
DEFAULT_STORAGE_ROOT = Path(__file__).resolve().parents[1] / ".local" / "external-materials"
PATH_PATTERN = re.compile(
    r"^/japanese/joho1/kousei/gian/(?P<session>\d{1,3})/meisai/m\d+(?P<number>\d{3})\.htm$"
)


class _Rows(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, str, list[tuple[str, str]]]]] = []
        self.row: list[tuple[str, str, list[tuple[str, str]]]] | None = None
        self.cell: dict | None = None
        self.anchor: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self.row = []
        elif tag in {"th", "td"} and self.row is not None:
            self.cell = {"tag": tag, "text": [], "links": []}
        elif tag == "a" and self.cell is not None:
            self.anchor = {"href": dict(attrs).get("href"), "text": []}

    def handle_data(self, data: str) -> None:
        if self.cell is not None:
            self.cell["text"].append(data)
        if self.anchor is not None:
            self.anchor["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self.anchor is not None and self.cell is not None:
            self.cell["links"].append((self.anchor["href"], "".join(self.anchor["text"])))
            self.anchor = None
        elif tag in {"th", "td"} and self.cell is not None and self.row is not None:
            text = " ".join("".join(self.cell["text"]).split())
            self.row.append((self.cell["tag"], text, self.cell["links"]))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def _bill_id_from_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    match = PATH_PATTERN.fullmatch(parsed.path)
    if (parsed.scheme != "https" or parsed.hostname != HOST or parsed.username
            or parsed.password or parsed.query or parsed.fragment or match is None):
        raise ValueError("only official Sangiin bill detail URLs are supported")
    return match.group("session"), str(int(match.group("number")))


def _default_fetch_bytes(url: str) -> bytes:
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, response, code, message, headers, new_url):
            raise ValueError("redirect rejected")

    request = urllib.request.Request(url, headers={"User-Agent": "public-interest-lens/0.1"})
    with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
        if response.geturl() != url:
            raise ValueError("response URL mismatch")
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("response is not HTML")
        payload = response.read(MAX_BYTES + 1)
    if len(payload) > MAX_BYTES:
        raise ValueError("response too large")
    return payload


def parse_bill_page(payload: bytes, url: str) -> dict:
    expected_session, expected_number = _bill_id_from_url(url)
    if len(payload) > MAX_BYTES:
        raise ValueError("response too large")
    parser = _Rows()
    parser.feed(payload.decode("utf-8", errors="strict"))
    cells: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    for row in parser.rows:
        for index in range(0, len(row) - 1):
            if row[index][0] == "th" and row[index + 1][0] == "td":
                cells.setdefault(row[index][1], (row[index + 1][1], row[index + 1][2]))
    try:
        title = cells["件名"][0].strip()
        session_text = cells["提出回次"][0]
        number_text = cells["提出番号"][0]
        submitted_text = cells["提出日"][0]
    except KeyError as error:
        raise ValueError("required bill field missing") from error
    if not title or session_text != f"{expected_session}回" or number_text != expected_number:
        raise ValueError("bill title or identifier mismatch")
    match = re.fullmatch(r"令和(\d{1,2})年(\d{1,2})月(\d{1,2})日", submitted_text)
    if match is None:
        raise ValueError("unsupported submission date")
    submitted = date(2018 + int(match.group(1)), int(match.group(2)), int(match.group(3)))
    result = {"billId": f"{expected_session}-{expected_number}", "title": title,
              "submittedAt": submitted.isoformat()}
    for href, text in cells.get("採決方法", ("", []))[1]:
        if "投票結果" not in text:
            continue
        vote_url = urljoin(url, href)
        parsed_vote = urlparse(vote_url)
        if (parsed_vote.scheme != "https" or parsed_vote.hostname != HOST
                or not parsed_vote.path.startswith("/japanese/joho1/kousei/vote/")
                or parsed_vote.query or parsed_vote.fragment):
            raise ValueError("individual vote link is outside official source")
        result["voteUrl"] = vote_url
        break
    return result


def _observed_at_from_record(record_path: Path) -> str:
    """登録済み record.json から観測時刻を読み取る。asOf とは別の取得時刻。"""
    record = json.loads(record_path.read_text(encoding="utf-8"))
    value = record.get("observed_at")
    if not isinstance(value, str) or not value:
        raise ValueError("registered observation time is missing")
    return value


def _register_page(path: Path, url: str, bill_id: str, digest: str,
                   *, storage_root: Path = DEFAULT_STORAGE_ROOT) -> Path:
    """原資料を規定の `.local/external-materials/<task-id>/` へ登録する。"""
    task_id = f"bill-{bill_id}"
    for record_path in sorted((storage_root / task_id).glob("*/record.json")):
        try:
            _verified_material(record_path, roots=(storage_root,), url=url,
                               digest=digest, expected_bytes=path.stat().st_size)
            return record_path
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return register_local_material(input_path=path, source_url=url, task_id=task_id,
                                   title="参議院議案審議情報", purpose="限定MVPの法案候補資料",
                                   storage_root=storage_root)


def fetch_bill_pages(urls: list[str], output_dir: Path, *, as_of: str,
                     fetch_bytes: Callable[[str], bytes] = _default_fetch_bytes,
                     sleep: Callable[[float], None] = time.sleep,
                     storage_root: Path = DEFAULT_STORAGE_ROOT) -> dict:
    """明示URLを最大3件だけ逐次取得し、得点化せずに保留する。"""
    if not 1 <= len(urls) <= 3 or len(set(urls)) != len(urls):
        raise ValueError("one to three unique bill URLs required")
    as_of_date = date.fromisoformat(as_of)
    try:
        recent_start = as_of_date.replace(year=as_of_date.year - 4)
    except ValueError:
        recent_start = as_of_date.replace(year=as_of_date.year - 4, day=28)
    for url in urls:
        _bill_id_from_url(url)
    held: list[dict] = []
    for index, url in enumerate(urls):
        session, number = _bill_id_from_url(url)
        record_path = None
        for existing in sorted((storage_root / f"bill-{session}-{number}").glob("*/record.json")):
            try:
                existing = existing.resolve(strict=True)
                record = json.loads(existing.read_text(encoding="utf-8"))
                if not isinstance(record, dict):
                    raise ValueError("registered material must be an object")
                record = _verified_material(existing, roots=(storage_root,), url=url,
                                            digest=record.get("sha256"), expected_bytes=record.get("bytes"))
                payload = (existing.parent / record["saved_filename"]).read_bytes()
                record_path = existing
                break
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ValueError("existing bill registration is invalid") from error
        if record_path is None:
            if index:
                sleep(1.0)
            for attempt in range(3):
                try:
                    payload = fetch_bytes(url)
                    break
                except OSError:
                    if attempt == 2:
                        raise
                    sleep(3.0)
        parsed = parse_bill_page(payload, url)
        submitted = date.fromisoformat(parsed["submittedAt"])
        if not recent_start <= submitted <= as_of_date:
            raise ValueError("bill outside recent four-year scope")
        digest = hashlib.sha256(payload).hexdigest()
        stage = output_dir / "source" / "bills" / f"{parsed['billId']}-{digest[:12]}.html"
        stage.parent.mkdir(parents=True, exist_ok=True)
        if stage.exists():
            if hashlib.sha256(stage.read_bytes()).hexdigest() != digest:
                raise ValueError("cached bill page changed")
        else:
            stage.write_bytes(payload)
        if record_path is None:
            record_path = _register_page(stage, url, parsed["billId"], digest,
                                         storage_root=storage_root)
        held.append({**parsed, "id": parsed["billId"], "reason": "impact_unverified",
                     "sourceUrl": url, "sha256": digest,
                     "observedAt": _observed_at_from_record(record_path)})
    return {
        "schemaVersion": "ranking-dataset/v1", "fictional": False, "asOf": as_of,
        "coverage": {"scope": "事前選定の参議院法案3件以内（網羅性未確認）",
                     "assessedPeople": 0, "targetPeople": None,
                     "sourceStatus": "pages_captured", "sourceRecords": len(held),
                     "assessedPolicies": 0, "candidatePolicies": len(held)},
        "people": [], "policies": [], "involvements": [], "evidence": [], "held": held,
    }
