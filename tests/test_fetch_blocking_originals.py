import csv
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from scripts.official_raw import capture_url, readback
from scripts.fetch_blocking_originals import (
    _item_id,
    _roots,
    acquire,
    build_parser,
    extract_saved,
    html_text,
    key,
    main,
    verify_saved,
)


@contextmanager
def network_blocked():
    def bomb(*_args, **_kwargs):
        raise AssertionError("network blocked")

    with patch("socket.create_connection", side_effect=bomb), patch(
        "socket.socket.connect", side_effect=bomb
    ):
        yield


DOCUMENT = "https://kokkai.ndl.go.jp/api/meeting?sessionFrom=1&sessionTo=1"
ROBOTS = "https://kokkai.ndl.go.jp/robots.txt"
ALLOW = b"User-agent: *\nAllow: /\n"
DISALLOW = b"User-agent: *\nDisallow: /\n"


class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.code = status
        self.headers = headers or {"Content-Type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit):
        return self.payload[:limit]


class Opener:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = 0
        self.urls = []

    def open(self, request, timeout):
        self.calls += 1
        self.urls.append(request.full_url)
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


class FetchEntryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.local = Path(temp.name) / ".local"
        self.material = self.local / "external-materials"
        self.clock = [1800000000.0]
        self.opener = None

    def sleep(self, seconds):
        self.clock[0] += seconds

    def fetch(self, url, **kwargs):
        return capture_url(
            url,
            opener=self.opener,
            now=lambda: self.clock[0],
            sleep=self.sleep,
            **kwargs,
        )

    def run_acquire(self, responses, urls=None, **kwargs):
        self.opener = Opener(responses)
        urls = urls if urls is not None else [DOCUMENT]
        with patch("scripts.collect_official_raw.capture_url", side_effect=self.fetch):
            return acquire(urls, material_root=self.material, **kwargs)

    def document(self, result):
        return next(item for item in result["outcomes"] if item["kind"] == "document")

    def test_help_refuses_cloud_default_refresh_and_short_interval(self):
        help_text = build_parser().format_help()
        self.assertNotIn("/mnt/project-files", help_text)
        self.assertIn("--material-root", help_text)
        self.assertIn("未確認", help_text)
        self.assertIn("禁止", help_text)
        with self.assertRaises(SystemExit):
            build_parser().parse_args([])
        self.assertEqual(main(["--material-root", str(self.material), "--refresh"]), 2)
        self.assertEqual(
            main(["--material-root", str(self.material), "--sleep", "1"]), 2
        )
        self.assertEqual(
            main(["--material-root", str(self.material), "--workers", "4"]), 2
        )
        self.assertFalse(self.material.exists())

    def test_complete_save_resume_and_same_url_reuse(self):
        payload = b"<html><p>" + b"A" * 300 + b"</p></html>"
        self.opener = Opener([Response(ALLOW), Response(payload), Response(b"replacement")])
        with patch("scripts.collect_official_raw.capture_url", side_effect=self.fetch):
            first = acquire([DOCUMENT], material_root=self.material, limit=1)
            self.assertEqual(self.opener.calls, 1)
            self.assertEqual(self.opener.urls, [ROBOTS])
            self.assertFalse(
                list((self.local / "full-acquisition").rglob("*.txt"))
            )
            second = acquire([DOCUMENT], material_root=self.material, limit=1)
            saved = self.document(second)
            self.assertEqual(self.opener.calls, 2)
            self.assertEqual(saved["status"], "saved")
            self.assertEqual(readback(saved["receipt"], self.material), payload)
            self.assertGreater(saved["receipt"]["bytes"], 120)
            self.assertFalse(list((self.local / "full-acquisition").rglob("*.txt")))
            extracted = extract_saved(self.material)
            full = html_text(payload)
            self.assertIn("A" * 300, full)
            self.assertGreater(len(full), 120)
            self.assertFalse(extracted["truncated"])
            self.assertEqual(extracted["extracted"][0]["chars"], len(full))
            text_path = (
                self.local
                / "full-acquisition"
                / "batches"
                / "blocking-originals"
                / "text"
                / f"{saved['id']}.txt"
            )
            self.assertEqual(text_path.read_text(encoding="utf-8"), full)
            receipt_path = (
                self.local
                / "full-acquisition"
                / "receipts"
                / f"blocking-originals-{saved['id']}.json"
            )
            before = receipt_path.read_bytes()
            checked = verify_saved(self.material)
            self.assertEqual(checked["content_verification"], "unverified")
            self.assertEqual(receipt_path.read_bytes(), before)
            third = acquire([DOCUMENT], material_root=self.material, limit=5)
        self.assertEqual(self.opener.calls, 2)
        self.assertEqual(readback(self.document(third)["receipt"], self.material), payload)
        self.assertEqual(self.document(third)["receipt"]["sha256"], saved["receipt"]["sha256"])

    def test_sha_mismatch_stops_without_overwrite_or_refetch(self):
        payload = b"<html><p>kept</p></html>"
        saved = self.document(self.run_acquire([Response(ALLOW), Response(payload)]))
        record = json.loads(Path(saved["receipt"]["record_path"]).read_text(encoding="utf-8"))
        original = Path(saved["receipt"]["record_path"]).parent / record["saved_filename"]
        original.write_bytes(b"broken")
        receipt_before = (
            self.local / "full-acquisition" / "receipts" / f"blocking-originals-{saved['id']}.json"
        ).read_bytes()
        calls = self.opener.calls
        with patch("scripts.collect_official_raw.capture_url", side_effect=self.fetch):
            with self.assertRaises(ValueError):
                acquire([DOCUMENT], material_root=self.material)
        self.assertEqual(self.opener.calls, calls)
        self.assertEqual(original.read_bytes(), b"broken")
        self.assertEqual(
            (
                self.local / "full-acquisition" / "receipts" / f"blocking-originals-{saved['id']}.json"
            ).read_bytes(),
            receipt_before,
        )
        with self.assertRaises(ValueError):
            verify_saved(self.material)
        self.assertEqual(original.read_bytes(), b"broken")

    def test_legacy_raw_is_reused_and_a_different_sha_is_not_written(self):
        payload = b"<html><p>" + b"B" * 180 + b"</p></html>"
        legacy = self.local / "private-m2" / "blocking-originals"
        raw = legacy / "raw" / f"{key(DOCUMENT)}.html"
        raw.parent.mkdir(parents=True)
        raw.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        (legacy / "index.csv").write_text(
            "URL,状態,HTTP,バイト,sha256,種類,ページ数,テキスト,取得時刻\n"
            f"{DOCUMENT},取得,200,{len(payload)},{digest},html,1,text/x.txt,2026-10-22T00:00:00Z\n",
            encoding="utf-8",
        )
        result = self.run_acquire(
            [Response(ALLOW), Response(b"<html><p>network</p></html>")],
            legacy_root=legacy,
        )
        saved = self.document(result)
        self.assertEqual(self.opener.urls, [ROBOTS])
        self.assertEqual(readback(saved["receipt"], self.material), payload)
        self.assertEqual(raw.read_bytes(), payload)
        self.assertTrue(saved["receipt"]["legacy_import"])
        changed = b"<html><p>changed</p></html>"
        raw.write_bytes(changed)
        changed_sha = hashlib.sha256(changed).hexdigest()
        (legacy / "index.csv").write_text(
            "URL,状態,HTTP,バイト,sha256,種類,ページ数,テキスト,取得時刻\n"
            f"{DOCUMENT},取得,200,{len(changed)},{changed_sha},html,1,text/x.txt,2026-10-22T00:00:00Z\n",
            encoding="utf-8",
        )
        with patch("scripts.collect_official_raw.capture_url", side_effect=self.fetch):
            with self.assertRaises(ValueError):
                acquire([DOCUMENT], material_root=self.material, legacy_root=legacy)
        self.assertEqual(self.opener.urls, [ROBOTS])
        self.assertEqual(readback(saved["receipt"], self.material), payload)

    def test_explicit_disallow_stops_before_the_document(self):
        result = self.run_acquire([Response(DISALLOW), Response(b"<html><p>no</p></html>")])
        body = self.document(result)
        self.assertEqual(body["status"], "robots_disallowed")
        self.assertEqual(body["robots_status"], "parsed")
        self.assertEqual(self.opener.urls, [ROBOTS])
        self.assertNotIn("receipt", body)

    def test_redirect_and_html_robots_stay_unconfirmed(self):
        for name, response in (
            ("redirect", Response(b"", 302, {"Location": "https://evil.example/secret", "Content-Type": "text/html"})),
            ("html", Response(b"<html>User-agent: *\nDisallow: /</html>", 200)),
        ):
            with self.subTest(name=name):
                result = self.run_acquire(
                    [response, Response(b"<html><p>body</p></html>")],
                    run_id=f"rule-{name}",
                )
                body = self.document(result)
                self.assertEqual(body["status"], "robots_unconfirmed")
                self.assertEqual(body["robots_status"], "unconfirmed")
                self.assertNotEqual(body["status"], "robots_disallowed")
                self.assertEqual(self.opener.urls, [ROBOTS])
                self.assertFalse(any(urlsplit(url).hostname == "evil.example" for url in self.opener.urls))

    def test_http_404_and_429_keep_full_bodies_and_block_rules(self):
        missing = b"missing-404-" + b"Z" * 200
        limited = b"limited-429-" + b"Q" * 200
        absent = self.run_acquire(
            [Response(b"none", 404), Response(missing, 404)],
            run_id="http-404",
        )
        saved = self.document(absent)
        self.assertEqual(saved["status"], "http_failed")
        self.assertEqual(saved["receipt"]["status"], 404)
        self.assertEqual(readback(saved["receipt"], self.material), missing)
        busy = self.run_acquire(
            [Response(ALLOW), Response(limited, 429, {"Retry-After": "1", "Content-Type": "text/plain"})],
            run_id="http-429",
        )
        saved = self.document(busy)
        self.assertEqual(saved["status"], "http_failed")
        self.assertEqual(saved["receipt"]["status"], 429)
        self.assertEqual(readback(saved["receipt"], self.material), limited)
        blocked = self.run_acquire(
            [Response(b"busy", 429), Response(b"<html><p>later</p></html>")],
            run_id="robots-429",
        )
        body = self.document(blocked)
        self.assertEqual(body["status"], "robots_access_blocked")
        self.assertEqual(body["robots_status"], "access_blocked")
        self.assertEqual(self.opener.urls, [ROBOTS])

    def test_http_url_is_held_without_network(self):
        self.opener = Opener([])
        with patch("scripts.collect_official_raw.capture_url", side_effect=self.fetch):
            result = acquire(
                ["http://www.city.example.jp/ordinance"],
                material_root=self.material,
            )
        self.assertEqual(self.opener.calls, 0)
        self.assertEqual(result["held"][0]["reason"], "outside_https_allowlist")
        self.assertNotEqual(result["held"][0].get("status"), "robots_disallowed")
        self.assertFalse((self.local / "full-acquisition" / "plans").exists())

    def original_of(self, receipt):
        record = json.loads(Path(receipt["record_path"]).read_text(encoding="utf-8"))
        return Path(receipt["record_path"]).parent / record["saved_filename"]

    def batch_dir(self, run_id="blocking-originals"):
        return self.local / "full-acquisition" / "batches" / run_id

    def save_document(self, payload, headers=None):
        saved = self.document(
            self.run_acquire(
                [Response(ALLOW), Response(payload, 200, headers or {"Content-Type": "text/html"})]
            )
        )
        original = self.original_of(saved["receipt"])
        receipt_file = (
            self.local
            / "full-acquisition"
            / "receipts"
            / f"blocking-originals-{saved['id']}.json"
        )
        return saved, original, original.read_bytes(), receipt_file.read_bytes(), receipt_file

    def test_resume_under_blocked_network_reuses_bytes(self):
        payload = b"<html><p>kept</p></html>"
        self.opener = Opener(
            [Response(ALLOW), Response(payload), Response(b"replacement")]
        )
        with patch("scripts.collect_official_raw.capture_url", side_effect=self.fetch):
            acquire([DOCUMENT], material_root=self.material, limit=1)
            second = acquire([DOCUMENT], material_root=self.material, limit=1)
            sha = self.document(second)["receipt"]["sha256"]
            calls = self.opener.calls
            with network_blocked():
                third = acquire([DOCUMENT], material_root=self.material, limit=5)
        self.assertEqual(self.opener.calls, calls)
        again = self.document(third)
        self.assertEqual(again["receipt"]["sha256"], sha)
        self.assertEqual(readback(again["receipt"], self.material), payload)

    def test_manifest_id_outside_plan_does_not_escape(self):
        payload = b"<html><p>kept</p></html>"
        saved, original, before, receipt_before, receipt_file = self.save_document(payload)
        manifest_path = self.batch_dir() / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for outcome in manifest["outcomes"]:
            if outcome.get("kind") == "document":
                outcome["id"] = "../../../../../escaped-text/from-checkpoint"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        escaped = self.local.parent / "escaped-text" / "from-checkpoint.txt"
        with network_blocked():
            with self.assertRaisesRegex(
                ValueError, "manifest outcome is not in the frozen plan"
            ):
                extract_saved(self.material)
        self.assertFalse(escaped.exists())
        self.assertFalse((self.batch_dir() / "text").exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)
        self.assertEqual(saved["receipt"]["content_verification"], "unverified")

    def test_manifest_id_not_in_plan_is_not_written(self):
        saved, original, before, receipt_before, receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        manifest_path = self.batch_dir() / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for outcome in manifest["outcomes"]:
            if outcome.get("kind") == "document":
                outcome["id"] = "not-in-plan"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        alien = self.batch_dir() / "text" / "not-in-plan.txt"
        with network_blocked():
            with self.assertRaisesRegex(
                ValueError, "manifest outcome is not in the frozen plan"
            ):
                extract_saved(self.material)
        self.assertFalse(alien.exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)

    def test_symlinked_text_dir_does_not_receive_extract(self):
        saved, original, before, _receipt_before, _receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        outside = self.local.parent / "outside-text"
        outside.mkdir()
        text_dir = self.batch_dir() / "text"
        text_dir.symlink_to(outside, target_is_directory=True)
        with network_blocked():
            with self.assertRaisesRegex(ValueError, "text directory escaped batch"):
                extract_saved(self.material)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertEqual(original.read_bytes(), before)
        self.assertFalse((outside / f"{saved['id']}.txt").exists())

    def test_symlinked_text_file_is_not_replaced(self):
        saved, original, before, _receipt_before, _receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        text_dir = self.batch_dir() / "text"
        text_dir.mkdir()
        outside = self.local.parent / "outside-file.txt"
        outside.write_text("old", encoding="utf-8")
        dest = text_dir / f"{saved['id']}.txt"
        dest.symlink_to(outside)
        with network_blocked():
            with self.assertRaisesRegex(ValueError, "text destination escaped batch"):
                extract_saved(self.material)
        self.assertEqual(outside.read_text(encoding="utf-8"), "old")
        self.assertTrue(dest.is_symlink())
        self.assertEqual(original.read_bytes(), before)

    def outside_tree(self, root: Path):
        if not root.exists():
            return []
        rows = []
        for path in root.rglob("*"):
            rel = path.relative_to(root).as_posix()
            if path.is_symlink():
                rows.append(("link", rel))
            elif path.is_file():
                rows.append(("file", rel, path.read_bytes()))
            elif path.is_dir():
                rows.append(("dir", rel))
        return sorted(rows)

    def test_symlinked_full_acquisition_does_not_receive_extract(self):
        _saved, original, before, receipt_before, receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        moved = self.local.parent / "moved-acquisition"
        control = self.local / "full-acquisition"
        control.rename(moved)
        control.symlink_to(moved, target_is_directory=True)
        before_tree = self.outside_tree(moved)
        with network_blocked():
            with self.assertRaisesRegex(ValueError, "full-acquisition escaped private root"):
                extract_saved(self.material)
        self.assertEqual(self.outside_tree(moved), before_tree)
        self.assertTrue(control.is_symlink())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)

    def test_symlinked_full_acquisition_blocks_acquire_before_write(self):
        self.local.mkdir()
        outside = self.local.parent / "outside-acquire"
        outside.mkdir()
        control = self.local / "full-acquisition"
        control.symlink_to(outside, target_is_directory=True)
        with network_blocked():
            with self.assertRaisesRegex(ValueError, "full-acquisition escaped private root"):
                acquire([DOCUMENT], material_root=self.material)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertFalse(self.material.exists())
        self.assertTrue(control.is_symlink())

    def test_symlinked_batch_does_not_receive_extract(self):
        _saved, original, before, receipt_before, receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        batch = self.batch_dir()
        moved = self.local.parent / "moved-batch"
        batch.rename(moved)
        batch.symlink_to(moved, target_is_directory=True)
        before_tree = self.outside_tree(moved)
        with network_blocked():
            with self.assertRaisesRegex(ValueError, "batch directory escaped private root"):
                extract_saved(self.material)
        self.assertEqual(self.outside_tree(moved), before_tree)
        self.assertTrue(batch.is_symlink())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)

    def test_symlinked_tmp_is_not_replaced(self):
        saved, original, before, receipt_before, receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        text_dir = self.batch_dir() / "text"
        text_dir.mkdir()
        outside = self.local.parent / "outside-tmp.txt"
        outside.write_text("old", encoding="utf-8")
        temp = text_dir / f"{saved['id']}.txt.tmp"
        temp.symlink_to(outside)
        with network_blocked():
            with self.assertRaisesRegex(ValueError, "text destination escaped batch"):
                extract_saved(self.material)
        self.assertEqual(outside.read_text(encoding="utf-8"), "old")
        self.assertTrue(temp.is_symlink())
        self.assertFalse((text_dir / f"{saved['id']}.txt").exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)

    def test_invalid_material_root_creates_nothing(self):
        fresh = self.local.parent / "fresh-root"
        fresh.mkdir()
        bad = fresh / "nope" / "store"
        with network_blocked():
            with self.assertRaisesRegex(
                ValueError, "material root must be private .local/external-materials"
            ):
                _roots(bad)
        self.assertFalse(bad.exists())
        self.assertFalse(bad.parent.exists())
        wrong = fresh / ".local" / "wrong-name"
        with network_blocked():
            with self.assertRaisesRegex(
                ValueError, "material root must be private .local/external-materials"
            ):
                _roots(wrong)
        self.assertFalse(wrong.exists())
        self.assertFalse(wrong.parent.exists())
        outside = fresh / "outside"
        outside.mkdir()
        linked = fresh / "linked"
        linked.mkdir()
        local = linked / ".local"
        local.symlink_to(outside)
        material = local / "external-materials"
        with network_blocked():
            with self.assertRaisesRegex(
                ValueError, "material root must be private .local/external-materials"
            ):
                _roots(material)
        self.assertFalse((outside / "external-materials").exists())

    def pdftotext_path(self, script):
        bin_dir = self.local.parent / "bin"
        bin_dir.mkdir()
        tool = bin_dir / "pdftotext"
        tool.write_text(script, encoding="utf-8")
        tool.chmod(0o755)
        return str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    def test_pdf_nonzero_exit_is_failed_not_complete(self):
        saved, original, before, receipt_before, receipt_file = self.save_document(
            b"%PDF-1.4\nfixture\n", {"Content-Type": "application/pdf"}
        )
        path_env = self.pdftotext_path("#!/bin/sh\nprintf 'partial\\n'\nexit 1\n")
        with patch.dict(os.environ, {"PATH": path_env}):
            with network_blocked():
                result = extract_saved(self.material)
        self.assertEqual(result["extracted"], [])
        self.assertEqual(result["unextracted"], [])
        self.assertEqual(result["failed"][0]["extract_status"], "failed")
        self.assertEqual(result["failed"][0]["id"], saved["id"])
        self.assertFalse(result["failed"][0]["truncated"])
        self.assertFalse(result["truncated"])
        self.assertNotIn("partial", json.dumps(result))
        self.assertFalse((self.batch_dir() / "text").exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)

    def test_pdf_missing_tool_is_unextracted(self):
        _saved, original, before, receipt_before, receipt_file = self.save_document(
            b"%PDF-1.4\nfixture\n", {"Content-Type": "application/pdf"}
        )
        with patch("scripts.fetch_blocking_originals.shutil.which", return_value=None):
            with network_blocked():
                result = extract_saved(self.material)
        self.assertEqual(result["extracted"], [])
        self.assertEqual(result["failed"], [])
        self.assertEqual(result["unextracted"][0]["extract_status"], "unextracted")
        self.assertFalse(result["truncated"])
        self.assertFalse((self.batch_dir() / "text").exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)

    def test_pdf_zero_exit_is_complete_and_empty_stdout_stays_complete(self):
        for script, expected in (
            ("#!/bin/sh\nprintf 'full text\\n'\nexit 0\n", "full text\n"),
            ("#!/bin/sh\nexit 0\n", ""),
        ):
            with self.subTest(expected=expected):
                fresh = tempfile.TemporaryDirectory()
                self.addCleanup(fresh.cleanup)
                self.local = Path(fresh.name) / ".local"
                self.material = self.local / "external-materials"
                saved, original, before, _receipt_before, _receipt_file = self.save_document(
                    b"%PDF-1.4\nfixture\n", {"Content-Type": "application/pdf"}
                )
                path_env = self.pdftotext_path(script)
                with patch.dict(os.environ, {"PATH": path_env}):
                    with network_blocked():
                        result = extract_saved(self.material)
                self.assertEqual(result["failed"], [])
                self.assertEqual(result["unextracted"], [])
                self.assertFalse(result["truncated"])
                item = result["extracted"][0]
                self.assertEqual(item["extract_status"], "complete")
                self.assertEqual(item["id"], saved["id"])
                self.assertFalse(item["truncated"])
                self.assertEqual(item["chars"], len(expected))
                text_path = self.batch_dir() / "text" / f"{saved['id']}.txt"
                self.assertEqual(text_path.read_text(encoding="utf-8"), expected)
                self.assertEqual(text_path.resolve().parent, text_path.parent.resolve())
                self.assertEqual(original.read_bytes(), before)

    def test_pdf_timeout_is_item_failure(self):
        saved, original, before, receipt_before, receipt_file = self.save_document(
            b"%PDF-1.4\nfixture\n", {"Content-Type": "application/pdf"}
        )

        def timed_out(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=["pdftotext"], timeout=300)

        with patch("scripts.fetch_blocking_originals.shutil.which", return_value="pdftotext"):
            with patch("scripts.fetch_blocking_originals.subprocess.run", side_effect=timed_out):
                with network_blocked():
                    result = extract_saved(self.material)
        self.assertEqual(result["extracted"], [])
        self.assertEqual(result["unextracted"], [])
        self.assertEqual(result["failed"][0]["id"], saved["id"])
        self.assertEqual(result["failed"][0]["extract_status"], "failed")
        self.assertFalse((self.batch_dir() / "text" / f"{saved['id']}.txt").exists())
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(receipt_file.read_bytes(), receipt_before)

    def test_absent_robots_does_not_fail_a_saved_document(self):
        payload = b"<html><p>" + b"D" * 40 + b"</p></html>"
        for status in (404, 410):
            with self.subTest(status=status):
                run = f"robots-absent-{status}"
                result = self.run_acquire(
                    [Response(b"none", status), Response(payload)],
                    run_id=run,
                )
                robots = next(item for item in result["outcomes"] if item["kind"] == "robots")
                self.assertEqual((robots["status"], robots["robots_status"]), ("no_rules", "no_rules"))
                self.assertEqual(self.document(result)["status"], "saved")
                self.assertEqual(result["failed_items"], 0)
                with patch(
                    "scripts.fetch_blocking_originals.source_urls", return_value=[DOCUMENT]
                ):
                    code = main(
                        ["--material-root", str(self.material), "--run-id", run, "--limit", "5"]
                    )
                self.assertEqual(code, 0)

    def test_document_http_failure_still_exits_failure(self):
        result = self.run_acquire(
            [Response(ALLOW), Response(b"missing", 404)],
            run_id="doc-404",
        )
        self.assertEqual(self.document(result)["status"], "http_failed")
        self.assertGreaterEqual(result["failed_items"], 1)
        with patch("scripts.fetch_blocking_originals.source_urls", return_value=[DOCUMENT]):
            code = main(
                ["--material-root", str(self.material), "--run-id", "doc-404", "--limit", "5"]
            )
        self.assertEqual(code, 1)

    def test_verify_rejects_manifest_outcome_that_leaves_the_plan(self):
        saved, original, before, receipt_before, receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        manifest_path = self.batch_dir() / "manifest.json"
        for field in ("url", "receipt"):
            with self.subTest(field=field):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for outcome in manifest["outcomes"]:
                    if outcome.get("kind") != "document":
                        continue
                    if field == "url":
                        outcome["url"] = ROBOTS
                    else:
                        outcome["receipt"]["url"] = ROBOTS
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with network_blocked():
                    with self.assertRaisesRegex(
                        ValueError, "manifest outcome does not match the frozen plan"
                    ):
                        verify_saved(self.material)
                self.assertEqual(original.read_bytes(), before)
                self.assertEqual(receipt_file.read_bytes(), receipt_before)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for outcome in manifest["outcomes"]:
                if outcome.get("id") == saved["id"]:
                    outcome["url"] = DOCUMENT
                    outcome["receipt"]["url"] = DOCUMENT
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_manifest_url_or_receipt_swap_is_not_extracted(self):
        saved, original, before, receipt_before, receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        manifest_path = self.batch_dir() / "manifest.json"
        for field in ("url", "receipt"):
            with self.subTest(field=field):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for outcome in manifest["outcomes"]:
                    if outcome.get("kind") != "document":
                        continue
                    if field == "url":
                        outcome["url"] = ROBOTS
                    else:
                        outcome["receipt"]["url"] = ROBOTS
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                with network_blocked():
                    with self.assertRaisesRegex(
                        ValueError, "manifest outcome does not match the frozen plan"
                    ):
                        extract_saved(self.material)
                self.assertFalse((self.batch_dir() / "text" / f"{saved['id']}.txt").exists())
                self.assertEqual(original.read_bytes(), before)
                self.assertEqual(receipt_file.read_bytes(), receipt_before)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for outcome in manifest["outcomes"]:
                if outcome.get("id") == saved["id"]:
                    outcome["url"] = DOCUMENT
                    outcome["receipt"]["url"] = DOCUMENT
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_extract_writes_index_that_points_at_the_text(self):
        payload = b"<html><p>kept</p></html>"
        saved, _original, _before, _receipt_before, _receipt_file = self.save_document(payload)
        with network_blocked():
            extract_saved(self.material)
        index_path = self.batch_dir() / "index.csv"
        with index_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        row = next(item for item in rows if item["URL"] == DOCUMENT)
        text_path = self.batch_dir() / row["テキスト"]
        self.assertEqual(row["状態"], "取得")
        self.assertEqual(row["sha256"], saved["receipt"]["sha256"])
        self.assertEqual(text_path.read_text(encoding="utf-8"), html_text(payload))
        self.assertFalse(index_path.is_symlink())

    def test_symlinked_index_is_not_replaced(self):
        _saved, original, before, _receipt_before, _receipt_file = self.save_document(
            b"<html><p>kept</p></html>"
        )
        outside = self.local.parent / "outside-index.csv"
        outside.write_text("old", encoding="utf-8")
        index_path = self.batch_dir() / "index.csv"
        index_path.symlink_to(outside)
        with network_blocked():
            with self.assertRaisesRegex(ValueError, "index escaped batch"):
                extract_saved(self.material)
        self.assertEqual(outside.read_text(encoding="utf-8"), "old")
        self.assertTrue(index_path.is_symlink())
        self.assertEqual(original.read_bytes(), before)

    def test_symlinked_plan_tmp_is_not_overwritten(self):
        outside = self.local.parent / "outside-plan.json"
        outside.write_text("old", encoding="utf-8")
        plans = self.local / "full-acquisition" / "plans"
        plans.mkdir(parents=True)
        temp = plans / "blocking-originals.json.tmp"
        temp.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "plan escaped private root"):
            self.run_acquire([Response(ALLOW), Response(b"<html><p>no</p></html>")])
        self.assertEqual(outside.read_text(encoding="utf-8"), "old")
        self.assertTrue(temp.is_symlink())
        self.assertFalse((plans / "blocking-originals.json").exists())

    def test_symlinked_registration_dir_is_not_written(self):
        payload = b"<html><p>" + b"C" * 40 + b"</p></html>"
        legacy = self.local / "private-m2" / "blocking-originals"
        raw = legacy / "raw" / f"{key(DOCUMENT)}.html"
        raw.parent.mkdir(parents=True)
        raw.write_bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        (legacy / "index.csv").write_text(
            "URL,状態,HTTP,バイト,sha256,種類,ページ数,テキスト,取得時刻\n"
            f"{DOCUMENT},取得,200,{len(payload)},{digest},html,1,text/x.txt,2026-10-22T00:00:00Z\n",
            encoding="utf-8",
        )
        registration = self.material / f"blocking-originals-{_item_id('d', DOCUMENT)}-a1"
        self.material.mkdir(parents=True)
        outside = self.local.parent / "outside-registration"
        outside.mkdir()
        registration.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "registration escaped private root"):
            self.run_acquire(
                [Response(ALLOW), Response(b"<html><p>network</p></html>")],
                legacy_root=legacy,
            )
        self.assertEqual(list(outside.iterdir()), [])
        self.assertTrue(registration.is_symlink())

    def test_network_registration_symlink_is_refused_before_fetch(self):
        item_id = _item_id("d", DOCUMENT)
        registration = self.material / f"blocking-originals-{item_id}-a1"
        self.material.mkdir(parents=True)
        outside = self.local.parent / "outside-registration"
        outside.mkdir()
        marker = outside / "kept.txt"
        marker.write_text("old", encoding="utf-8")
        registration.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "registration escaped private root"):
            self.run_acquire([Response(ALLOW), Response(b"<html><p>network</p></html>")])
        self.assertEqual(marker.read_text(encoding="utf-8"), "old")
        self.assertEqual(list(outside.iterdir()), [marker])
        self.assertTrue(registration.is_symlink())
        self.assertEqual(self.opener.calls, 0)

    def test_legacy_raw_without_confirmed_http_is_not_frozen(self):
        payload = b"<html><p>legacy</p></html>"
        network = b"<html><p>network</p></html>"
        legacy = self.local / "private-m2" / "blocking-originals"
        raw = legacy / "raw" / f"{key(DOCUMENT)}.html"
        raw.parent.mkdir(parents=True)
        raw.write_bytes(payload)
        result = self.run_acquire(
            [Response(ALLOW), Response(network)],
            legacy_root=legacy,
        )
        saved = self.document(result)
        self.assertEqual(self.opener.urls, [ROBOTS, DOCUMENT])
        self.assertNotIn("legacy_import", saved["receipt"])
        self.assertEqual(readback(saved["receipt"], self.material), network)
        self.assertEqual(raw.read_bytes(), payload)

    def test_pending_fetch_does_not_exit_success(self):
        payload = b"<html><p>later</p></html>"
        self.opener = Opener([Response(ALLOW), Response(payload)])
        with patch("scripts.fetch_blocking_originals.source_urls", return_value=[DOCUMENT]):
            with patch("scripts.collect_official_raw.capture_url", side_effect=self.fetch):
                partial = main(["--material-root", str(self.material), "--limit", "1"])
                done = main(["--material-root", str(self.material), "--limit", "5"])
        self.assertEqual(partial, 1)
        self.assertEqual(done, 0)
        self.assertEqual(self.opener.urls, [ROBOTS, DOCUMENT])


if __name__ == "__main__":
    unittest.main()
