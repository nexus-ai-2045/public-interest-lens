import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.collect_sangiin_materials import classify, collect, priority
from scripts.register_external_material import register_local_material


class SangiinTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.local = Path(t.name) / ".local"
        self.material = self.local / "external-materials"
        self.control = self.local / "full-acquisition"
        self.control.mkdir(parents=True)
        self.seq = 0

    def receipt(self, url, body, status=200):
        self.seq += 1
        source = self.control / f"input-{self.seq}.html"
        source.write_bytes(body)
        record = register_local_material(
            input_path=source,
            source_url=url,
            task_id=f"fixture-{self.seq}",
            title="試験原本",
            purpose="試験",
            storage_root=self.material,
            observed_at="2026-10-07T00:00:00+00:00",
        )
        return {
            "url": url,
            "status": status,
            "headers": {"content-type": "text/html"},
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "record_path": str(record),
            "observed_at": "2026-10-07T00:00:00+00:00",
        }

    def seed(self, html):
        root = "https://www.sangiin.go.jp/jpn/gikai/library.html"
        seed = {
            "outcomes": [
                {
                    "url": "https://www.sangiin.go.jp/robots.txt",
                    "kind": "robots",
                    "status": "http_failed",
                    "receipt": self.receipt(
                        "https://www.sangiin.go.jp/robots.txt", b"missing", 404
                    ),
                },
                {
                    "url": root,
                    "kind": "index",
                    "status": "saved",
                    "receipt": self.receipt(root, html),
                },
            ]
        }
        path = self.control / "seed.json"
        path.write_text(json.dumps(seed), encoding="utf-8")
        return path

    def test_scope_and_reference_separation(self):
        self.assertEqual(
            classify("https://www.sangiin.go.jp/japanese/touhyoulist/222/vote_ind.htm")[
                1
            ],
            "votes",
        )
        self.assertEqual(
            classify("https://www.sangiin.go.jp/elsewhere/report.xlsx")[0], "attachment"
        )
        self.assertEqual(
            classify("https://www.sangiin.go.jp/jpn/images/logo.png")[0],
            "excluded_navigation_asset",
        )
        self.assertEqual(
            classify("https://www.sangiin.go.jp/jpn/gikai/library/report/figure.png")[
                0
            ],
            "attachment",
        )
        self.assertEqual(
            classify("https://www.shugiin.go.jp/report.pdf")[0], "external_reference"
        )
        self.assertEqual(
            classify("https://www.sangiin.go.jp/jpn/gikai/movie.mp4")[0],
            "video_reference",
        )

    def test_seeds_precede_documents_then_recent_indexes(self):
        seed = "https://www.sangiin.go.jp/jpn/gikai/library.html"
        doc = "https://www.sangiin.go.jp/japanese/touhyoulist/221/result.htm"
        new = "https://www.sangiin.go.jp/japanese/touhyoulist/222/vote_ind.htm"
        old = "https://www.sangiin.go.jp/japanese/touhyoulist/142/vote_ind.htm"
        self.assertEqual(
            sorted([old, new, doc, seed], key=lambda u: priority(u, {seed})),
            [seed, doc, new, old],
        )

    def test_reuse_roots_cycle_dedup_and_finite_frontier(self):
        root = "https://www.sangiin.go.jp/jpn/gikai/library.html"
        child = "https://www.sangiin.go.jp/jpn/gianjoho/ketsugi/222/test.html"
        seed = self.seed(
            f'<a href="{child}">本文</a><a href="https://elsewhere.example/file.pdf">参照</a>'.encode()
        )
        response = self.receipt(
            child,
            f'<a href="{root}">戻る</a><a href="/jpn/gianjoho/ketsugi/222/next.html">次</a>'.encode(),
        )
        with patch(
            "scripts.collect_sangiin_materials.capture_url", return_value=response
        ) as fetch:
            result = collect(seed, self.material, "test-run", 1)
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["reused_this_run"], 1)
        self.assertEqual(result["saved_urls"], 2)
        self.assertEqual(result["pending_urls"], 1)
        self.assertFalse(result["source_complete"])
        self.assertEqual(result["reference_kinds"]["external_reference"], 1)

    def test_corrupt_saved_original_stops_resume_before_network(self):
        seed = self.seed(b"<p>saved</p>")
        result = collect(seed, self.material, "test-run", 1)
        state = json.loads(Path(result["checkpoint"]).read_text(encoding="utf-8"))
        node = next(iter(state["nodes"].values()))
        p = Path(node["receipt"]["record_path"])
        record = json.loads(p.read_text(encoding="utf-8"))
        (p.parent / record["saved_filename"]).write_bytes(b"changed")
        with patch("scripts.collect_sangiin_materials.capture_url") as fetch:
            with self.assertRaises(ValueError):
                collect(seed, self.material, "test-run", 1)
        fetch.assert_not_called()

    def test_robots_denial_stops_seed_and_network(self):
        seed = self.seed(b'<a href="/jpn/gikai/other.html">next</a>')
        data = json.loads(seed.read_text(encoding="utf-8"))
        data["outcomes"][0]["receipt"] = self.receipt(
            "https://www.sangiin.go.jp/robots.txt", b"User-agent: *\nDisallow: /", 200
        )
        seed.write_text(json.dumps(data), encoding="utf-8")
        with patch("scripts.collect_sangiin_materials.capture_url") as fetch:
            result = collect(seed, self.material, "test-run", 1)
        fetch.assert_not_called()
        self.assertEqual(result["failed_urls"], 1)

    def test_unconfirmed_robots_stops_before_network(self):
        for body, code in [
            (b"<html>Maintenance</html>", 200),
            (b"<html>User-agent: *\nDisallow: /</html>", 200),
            (b"Disallow: /", 200),
            (b"# User-agent: *\n# maintenance", 200),
            (b"", 200),
            (b"redirect", 302),
        ]:
            with self.subTest(body=body, code=code):
                seed = self.seed(b'<a href="/jpn/gikai/other.html">next</a>')
                data = json.loads(seed.read_text(encoding="utf-8"))
                data["outcomes"][0]["receipt"] = self.receipt(
                    "https://www.sangiin.go.jp/robots.txt", body, code
                )
                seed.write_text(json.dumps(data), encoding="utf-8")
                response = self.receipt(
                    "https://www.sangiin.go.jp/jpn/gikai/other.html", b"<p>material</p>"
                )
                with patch(
                    "scripts.collect_sangiin_materials.capture_url", return_value=response
                ) as fetch:
                    with self.assertRaisesRegex(ValueError, "robots policy unconfirmed"):
                        collect(seed, self.material, f"unknown-{self.seq}", 1)
                fetch.assert_not_called()

    def test_explicit_missing_robots_allows_collection(self):
        for code in [404, 410]:
            with self.subTest(code=code):
                child = f"https://www.sangiin.go.jp/jpn/gikai/other-{code}.html"
                seed = self.seed(f'<a href="{child}">next</a>'.encode())
                data = json.loads(seed.read_text(encoding="utf-8"))
                data["outcomes"][0]["receipt"] = self.receipt(
                    "https://www.sangiin.go.jp/robots.txt", b"missing", code
                )
                seed.write_text(json.dumps(data), encoding="utf-8")
                response = self.receipt(child, b"<p>material</p>")
                with patch(
                    "scripts.collect_sangiin_materials.capture_url", return_value=response
                ) as fetch:
                    result = collect(seed, self.material, f"missing-{code}", 1)
                self.assertEqual(result["robots_status"], "no_rules")
                self.assertEqual(result["failed_urls"], 0)
                self.assertEqual(result["saved_urls"], 2)
                fetch.assert_called_once()

    def test_parsed_allowing_robots_collects_material(self):
        child = "https://www.sangiin.go.jp/jpn/gikai/other.html"
        seed = self.seed(f'<a href="{child}">next</a>'.encode())
        data = json.loads(seed.read_text(encoding="utf-8"))
        data["outcomes"][0]["receipt"] = self.receipt(
            "https://www.sangiin.go.jp/robots.txt", b"User-agent: *\nDisallow:", 200
        )
        seed.write_text(json.dumps(data), encoding="utf-8")
        response = self.receipt(child, b"<p>material</p>")
        with patch(
            "scripts.collect_sangiin_materials.capture_url", return_value=response
        ) as fetch:
            result = collect(seed, self.material, "parsed-allow", 1)
        fetch.assert_called_once()
        self.assertEqual(result["robots_status"], "parsed")
        self.assertEqual(result["saved_urls"], 2)

    def test_http_limit_and_server_failure_block_resume(self):
        child = "https://www.sangiin.go.jp/jpn/gikai/data.html"
        for code in [403, 429, 503]:
            seed = self.seed(f'<a href="{child}">data</a>'.encode())
            receipt = self.receipt(child, b"blocked", code)
            with patch(
                "scripts.collect_sangiin_materials.capture_url", return_value=receipt
            ):
                first = collect(seed, self.material, f"test-{code}", 1)
            self.assertEqual(first["failed_urls"], 1)
            with patch("scripts.collect_sangiin_materials.capture_url") as fetch:
                with self.assertRaises(ValueError):
                    collect(seed, self.material, f"test-{code}", 1)
            fetch.assert_not_called()

    def test_outside_initial_seed_rejected_before_network(self):
        seed = self.seed(b"<p>index</p>")
        data = json.loads(seed.read_text(encoding="utf-8"))
        outside = "https://www.sangiin.go.jp/outside/search.cgi"
        data["outcomes"].append(
            {"url": outside, "kind": "document", "status": "pending"}
        )
        seed.write_text(json.dumps(data), encoding="utf-8")
        receipt = self.receipt(outside, b"<p>outside</p>")
        with patch(
            "scripts.collect_sangiin_materials.capture_url", return_value=receipt
        ) as fetch:
            with self.assertRaises(ValueError):
                collect(seed, self.material, "outside-seed", 1)
        fetch.assert_not_called()

    def test_outside_resume_frontier_rejected_before_network(self):
        seed = self.seed(b"<p>index</p>")
        first = collect(seed, self.material, "outside-frontier", 1)
        path = Path(first["checkpoint"])
        state = json.loads(path.read_text(encoding="utf-8"))
        outside = "https://www.sangiin.go.jp/outside/search.cgi"
        state["frontier"] = [outside]
        path.write_text(json.dumps(state), encoding="utf-8")
        receipt = self.receipt(outside, b"<p>outside</p>")
        with patch(
            "scripts.collect_sangiin_materials.capture_url", return_value=receipt
        ) as fetch:
            with self.assertRaises(ValueError):
                collect(seed, self.material, "outside-frontier", 1)
        fetch.assert_not_called()

    def test_official_attachment_outside_page_prefix_still_collects(self):
        url = "https://www.sangiin.go.jp/elsewhere/report.xlsx"
        seed = self.seed(f'<a href="{url}">attachment</a>'.encode())
        receipt = self.receipt(url, b"spreadsheet")
        with patch(
            "scripts.collect_sangiin_materials.capture_url", return_value=receipt
        ) as fetch:
            result = collect(seed, self.material, "attachment-run", 1)
        fetch.assert_called_once()
        self.assertEqual(result["saved_urls"], 2)
        self.assertEqual(result["families"]["attachment"], 1)

    def test_saved_material_reused_across_collection_runs(self):
        child = "https://www.sangiin.go.jp/jpn/gikai/data.html"
        seed = self.seed(f'<a href="{child}">data</a>'.encode())
        receipt = self.receipt(child, b"<p>material</p>")
        with patch(
            "scripts.collect_sangiin_materials.capture_url", return_value=receipt
        ):
            collect(seed, self.material, "first-run", 1)
        with patch("scripts.collect_sangiin_materials.capture_url") as fetch:
            result = collect(seed, self.material, "second-run", 1)
        fetch.assert_not_called()
        self.assertEqual(result["reused_this_run"], 2)
