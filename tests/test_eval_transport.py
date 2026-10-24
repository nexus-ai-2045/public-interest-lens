import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "eval-transport" / "queue.json"
PRODUCTION = (
    ROOT / "data" / "derived" / "ai-field-v1" / "labels.csv",
    ROOT / "data" / "derived" / "bill-triage-v1" / "tiebreak.csv",
    ROOT / "data" / "derived" / "bill-triage-v2" / "tiebreak-lines.csv",
)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, "-m", "scripts.eval_loop", *args], cwd=ROOT, capture_output=True, text=True)


class EvalTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name) / "work"
        self.production = {path: path.read_bytes() for path in PRODUCTION}
        prepared = run("prepare", "--out", str(self.work), "--fixture", str(FIXTURE))
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        self.assertEqual(json.loads(prepared.stdout), {"tiebreak": 1, "field": 1, "lines": 1})
        packed = run("pack", "--work", str(self.work))
        self.assertEqual(packed.returncode, 0, packed.stderr)
        self.assertFalse(json.loads(packed.stdout)["launched"])
        self.manifest = json.loads((self.work / "transport" / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse((self.work / "transport" / "lanes").exists())

    def tearDown(self) -> None:
        for path, raw in self.production.items():
            self.assertEqual(path.read_bytes(), raw)
        self.tmp.cleanup()

    def entry(self, kind: str) -> dict:
        return next(item for item in self.manifest["batches"] if item["kind"] == kind)

    def write_lane(self, entry: dict, lane: str, labels: list[dict], **overrides: object) -> Path:
        body: dict[str, object] = {
            "schema": "eval-lane-v1",
            "provider": "fake",
            "session_id": f"fixture-session-{lane}",
            "lane": lane,
            "kind": entry["kind"],
            "batch": entry["batch"],
            "input_sha256": entry["input_sha256"],
            "inputs_sha256": entry["inputs_sha256"],
            "labels": labels,
        }
        body.update(overrides)
        self.lane_seq = getattr(self, "lane_seq", 0) + 1
        path = Path(self.tmp.name) / f"lane-{self.lane_seq}.json"
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        return path

    def test_pack_writes_hash_and_unlaunched_packet(self) -> None:
        entry = self.entry("field")
        snapshot = self.work / entry["snapshot"]
        self.assertEqual(entry["input_sha256"], hashlib.sha256(snapshot.read_bytes()).hexdigest())
        packet = json.loads((self.work / entry["packet_a"]).read_text(encoding="utf-8"))
        self.assertFalse(packet["launched"])
        self.assertEqual(packet["human_gate"], "parent_must_dispatch")
        self.assertEqual(packet["reply_mode"], "file-backed-result")
        self.assertNotIn("/Users/", json.dumps(packet))
        self.assertIn("Haiku、Sonnet、Opus、Workflow の名前を置き換えて実行したことにしない", packet["rules"])

    def test_cli_smoke_agrees_holds_and_applies_without_scoring_unknown(self) -> None:
        field = self.entry("field")
        lane_a = self.write_lane(field, "a", [
            {"id": "fixture-field-1", "field": "金融", "reason": "題名の対象"},
            {"id": "fixture-field-2", "field": "0", "reason": "未知"},
        ])
        lane_b = self.write_lane(field, "b", [
            {"id": "fixture-field-1", "field": "金融", "reason": "別の言い方"},
            {"id": "fixture-field-2", "field": "教育", "reason": "学校"},
        ])
        candidate = Path(self.tmp.name) / "field.json"
        verified = run("verify-lanes", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                       "--lane-a", str(lane_a), "--lane-b", str(lane_b), "--candidate", str(candidate))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        report = json.loads(verified.stdout)
        self.assertEqual(report["status"], "candidate")
        self.assertEqual(report["agreed"], 1)
        self.assertFalse(report["live_session_verified"])
        self.assertEqual(report["execution"], "fake")
        labels = json.loads(candidate.read_text(encoding="utf-8"))["labels"]
        self.assertEqual(labels, [{"id": "fixture-field-1", "field": "金融", "how": "一致", "reason": "系統A: 題名の対象／系統B: 別の言い方"}])
        held = json.loads((self.work / "transport" / "reports" / f"field-{field['batch']}.json").read_text(encoding="utf-8"))["held"]
        self.assertEqual(held, [{"id": "fixture-field-2", "hold": "候補外"}])
        dest = Path(self.tmp.name) / "labels.csv"
        applied = run("apply-candidates", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                      "--candidate", str(candidate), "--dest", str(dest))
        self.assertEqual(applied.returncode, 0, applied.stderr)
        with dest.open(encoding="utf-8") as handle:
            self.assertEqual(list(csv.DictReader(handle)), [
                {"id": "fixture-field-1", "分野": "金融", "決め方": "一致", "理由": "系統A: 題名の対象／系統B: 別の言い方"},
            ])

        lines = self.entry("lines")
        line_labels = [{"id": "fixture-line-1", "pick": "系統2", "reason": "中身を変えると読んだ"}]
        line_candidate = Path(self.tmp.name) / "lines.json"
        verified = run("verify-lanes", "--work", str(self.work), "--kind", "lines", "--batch", lines["batch"],
                       "--lane-a", str(self.write_lane(lines, "a", line_labels)),
                       "--lane-b", str(self.write_lane(lines, "b", line_labels)),
                       "--candidate", str(line_candidate))
        self.assertEqual(verified.returncode, 0, verified.stderr)
        line_dest = Path(self.tmp.name) / "lines.csv"
        applied = run("apply-candidates", "--work", str(self.work), "--kind", "lines", "--batch", lines["batch"],
                      "--candidate", str(line_candidate), "--inputs", str(self.work / "lines" / "inputs.json"),
                      "--dest", str(line_dest))
        self.assertEqual(applied.returncode, 0, applied.stderr)
        with line_dest.open(encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual((row["採用"], row["決め方"]), ("保留", "規則で保留"))

    def verify(self, name: str, lane_a: Path, lane_b: Path) -> subprocess.CompletedProcess[str]:
        field = self.entry("field")
        candidate = Path(self.tmp.name) / f"{name}.json"
        candidate.write_text("stale", encoding="utf-8")
        result = run("verify-lanes", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                     "--lane-a", str(lane_a), "--lane-b", str(lane_b), "--candidate", str(candidate))
        if result.returncode != 0:
            self.assertFalse(candidate.exists(), name)
        return result

    def test_stops_do_not_leave_a_candidate(self) -> None:
        field = self.entry("field")
        labels = [
            {"id": "fixture-field-1", "field": "金融", "reason": "題名"},
            {"id": "fixture-field-2", "field": "教育", "reason": "学校"},
        ]
        broken_b = self.write_lane(field, "b", labels, session_id="broken-b")
        broken_b.write_text("{", encoding="utf-8")
        cases = {
            "same-session": ("同じ session", self.write_lane(field, "a", labels, session_id="same"), self.write_lane(field, "b", labels, session_id="same")),
            "claude-name": ("Claude のモデル名", self.write_lane(field, "a", labels, provider="haiku"), self.write_lane(field, "b", labels)),
            "renamed-model": ("Claude のモデル名", self.write_lane(field, "a", labels, model="opus"), self.write_lane(field, "b", labels)),
            "short": ("件数が snapshot と違う", self.write_lane(field, "a", labels[:1]), self.write_lane(field, "b", labels)),
            "broken": ("JSON が読めない", self.write_lane(field, "a", labels), broken_b),
        }
        for name, (reason, lane_a, lane_b) in cases.items():
            result = self.verify(name, lane_a, lane_b)
            self.assertEqual(result.returncode, 2, name + result.stdout + result.stderr)
            self.assertIn(reason, result.stdout, name)
        no_evidence = self.verify("no-evidence", self.write_lane(field, "a", labels), self.write_lane(field, "b", [
            labels[0], {"id": "fixture-field-2", "field": "教育", "reason": ""},
        ]))
        self.assertEqual(no_evidence.returncode, 0, no_evidence.stderr)
        self.assertEqual(json.loads(no_evidence.stdout)["agreed"], 1)
        source = self.work / field["source"]
        source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        stale = self.verify("stale", self.write_lane(field, "a", labels), self.write_lane(field, "b", labels))
        self.assertEqual(stale.returncode, 2)
        self.assertIn("入力が pack の後に変わっている", stale.stdout)

    def test_disagreement_is_held_after_source_is_restored(self) -> None:
        field = self.entry("field")
        snapshot = (self.work / field["snapshot"]).read_bytes()
        (self.work / field["source"]).write_bytes(snapshot)
        lane_a = self.write_lane(field, "a", [
            {"id": "fixture-field-1", "field": "金融", "reason": "題名"},
            {"id": "fixture-field-2", "field": "教育", "reason": "学校"},
        ])
        lane_b = self.write_lane(field, "b", [
            {"id": "fixture-field-1", "field": "金融", "reason": "題名"},
            {"id": "fixture-field-2", "field": "医療・福祉", "reason": "別の産業"},
        ])
        candidate = Path(self.tmp.name) / "disagree.json"
        result = run("verify-lanes", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                     "--lane-a", str(lane_a), "--lane-b", str(lane_b), "--candidate", str(candidate))
        self.assertEqual(result.returncode, 0, result.stderr)
        labels = json.loads(candidate.read_text(encoding="utf-8"))["labels"]
        self.assertEqual([row["id"] for row in labels], ["fixture-field-1"])
        report = json.loads((self.work / "transport" / "reports" / f"field-{field['batch']}.json").read_text(encoding="utf-8"))
        self.assertEqual(report["held"], [{"id": "fixture-field-2", "hold": "不一致", "a": "教育", "b": "医療・福祉"}])

    def agree(self, kind: str) -> tuple[dict, Path]:
        entry = self.entry(kind)
        if kind == "lines":
            labels = [{"id": "fixture-line-1", "pick": "系統2", "reason": "中身を変えると読んだ"}]
        elif kind == "tiebreak":
            labels = [{"id": "fixture-tie-1", "kind": "定型改正", "field": "金融", "reason": "期限だけ"}]
        else:
            labels = [
                {"id": "fixture-field-1", "field": "金融", "reason": "題名"},
                {"id": "fixture-field-2", "field": "教育", "reason": "学校"},
            ]
        candidate = Path(self.tmp.name) / f"agree-{kind}.json"
        result = run("verify-lanes", "--work", str(self.work), "--kind", kind, "--batch", entry["batch"],
                     "--lane-a", str(self.write_lane(entry, "a", labels)),
                     "--lane-b", str(self.write_lane(entry, "b", labels)),
                     "--candidate", str(candidate))
        self.assertEqual(result.returncode, 0, result.stderr)
        return entry, candidate

    def test_verify_rejects_one_file_for_both_lanes(self) -> None:
        field = self.entry("field")
        labels = [
            {"id": "fixture-field-1", "field": "金融", "reason": "題名"},
            {"id": "fixture-field-2", "field": "教育", "reason": "学校"},
        ]
        lane = self.write_lane(field, "a", labels)
        candidate = Path(self.tmp.name) / "same-file.json"
        candidate.write_text("stale", encoding="utf-8")
        result = run("verify-lanes", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                     "--lane-a", str(lane), "--lane-b", str(lane), "--candidate", str(candidate))
        self.assertEqual(result.returncode, 2)
        self.assertIn("同じファイル", result.stdout)
        self.assertFalse(candidate.exists())

    def test_apply_stops_when_inputs_change_after_pack(self) -> None:
        lines, candidate = self.agree("lines")
        bound = json.loads(candidate.read_text(encoding="utf-8"))
        self.assertEqual(bound["kind"], "lines")
        self.assertEqual(bound["batch"], lines["batch"])
        self.assertEqual(bound["input_sha256"], lines["input_sha256"])
        self.assertEqual(bound["inputs_sha256"], lines["inputs_sha256"])
        inputs = self.work / "lines" / "inputs.json"
        data = json.loads(inputs.read_text(encoding="utf-8"))
        data["fixture-line-1"]["系統1の値"] += "・改変"
        inputs.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        self.assertNotEqual(hashlib.sha256(inputs.read_bytes()).hexdigest(), lines["inputs_sha256"])
        dest = Path(self.tmp.name) / "stale-lines.csv"
        dest.write_text("keep\n", encoding="utf-8")
        applied = run("apply-candidates", "--work", str(self.work), "--kind", "lines", "--batch", lines["batch"],
                      "--candidate", str(candidate), "--inputs", str(inputs), "--dest", str(dest))
        self.assertEqual(applied.returncode, 2, applied.stdout + applied.stderr)
        self.assertIn("lines/inputs.json が pack の後に変わっている", applied.stderr)
        self.assertEqual(dest.read_text(encoding="utf-8"), "keep\n")
        self.assertNotIn("改変", dest.read_text(encoding="utf-8"))

    def test_apply_rejects_old_swapped_and_other_batch_candidates(self) -> None:
        lines, line_candidate = self.agree("lines")
        field, field_candidate = self.agree("field")
        dest = Path(self.tmp.name) / "rejected.csv"
        dest.write_text("keep\n", encoding="utf-8")

        old = json.loads(line_candidate.read_text(encoding="utf-8"))
        old["input_sha256"] = "0" * 64
        old_path = Path(self.tmp.name) / "old-lines.json"
        old_path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        stale_candidate = run("apply-candidates", "--work", str(self.work), "--kind", "lines", "--batch", lines["batch"],
                              "--candidate", str(old_path), "--inputs", str(self.work / "lines" / "inputs.json"),
                              "--dest", str(dest))
        self.assertEqual(stale_candidate.returncode, 2, stale_candidate.stdout + stale_candidate.stderr)
        self.assertIn("候補の入力 hash が manifest と違う", stale_candidate.stderr)

        swapped = run("apply-candidates", "--work", str(self.work), "--kind", "lines", "--batch", lines["batch"],
                      "--candidate", str(field_candidate), "--inputs", str(self.work / "lines" / "inputs.json"),
                      "--dest", str(dest))
        self.assertEqual(swapped.returncode, 2, swapped.stdout + swapped.stderr)
        self.assertIn("候補の kind または batch が指定と違う", swapped.stderr)

        other_batch = run("apply-candidates", "--work", str(self.work), "--kind", "field", "--batch", lines["batch"],
                          "--candidate", str(field_candidate), "--dest", str(dest))
        self.assertEqual(other_batch.returncode, 2, other_batch.stdout + other_batch.stderr)
        self.assertIn("manifest にその batch が無い", other_batch.stderr)
        self.assertEqual(dest.read_text(encoding="utf-8"), "keep\n")
        self.assertEqual(field["kind"], "field")

    def test_apply_stops_when_non_line_source_or_snapshot_changes(self) -> None:
        field, field_candidate = self.agree("field")
        tie, tie_candidate = self.agree("tiebreak")
        dest = Path(self.tmp.name) / "field.csv"
        dest.write_text("keep\n", encoding="utf-8")
        source = self.work / field["source"]
        source.write_text(source.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        changed_source = run("apply-candidates", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                             "--candidate", str(field_candidate), "--dest", str(dest))
        self.assertEqual(changed_source.returncode, 2, changed_source.stdout + changed_source.stderr)
        self.assertIn("入力が pack の後に変わっている", changed_source.stderr)
        self.assertEqual(dest.read_text(encoding="utf-8"), "keep\n")

        source.write_bytes((self.work / field["snapshot"]).read_bytes())
        snapshot = self.work / tie["snapshot"]
        snapshot.write_text(snapshot.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        changed_snapshot = run("apply-candidates", "--work", str(self.work), "--kind", "tiebreak", "--batch", tie["batch"],
                               "--candidate", str(tie_candidate), "--dest", str(dest))
        self.assertEqual(changed_snapshot.returncode, 2, changed_snapshot.stdout + changed_snapshot.stderr)
        self.assertIn("snapshot が manifest の hash と違う", changed_snapshot.stderr)
        self.assertEqual(dest.read_text(encoding="utf-8"), "keep\n")

    def test_apply_rejects_a_single_decider(self) -> None:
        field = self.entry("field")
        candidate = Path(self.tmp.name) / "sonnet.json"
        candidate.write_text(json.dumps({"labels": [{"id": "fixture-field-1", "field": "金融", "how": "Sonnetが決定", "reason": "単独"}]}), encoding="utf-8")
        dest = Path(self.tmp.name) / "should-not.csv"
        result = run("apply-candidates", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                     "--candidate", str(candidate), "--dest", str(dest))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(dest.exists())

    def test_apply_rejects_a_result_wrapper_around_other_rows(self) -> None:
        field, candidate = self.agree("field")
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        payload["result"] = {"labels": [{"id": "fixture-field-2", "field": "0", "how": "一致", "reason": "未知"}]}
        candidate.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        dest = Path(self.tmp.name) / "wrapped.csv"
        dest.write_text("keep\n", encoding="utf-8")
        applied = run("apply-candidates", "--work", str(self.work), "--kind", "field", "--batch", field["batch"],
                      "--candidate", str(candidate), "--dest", str(dest))
        self.assertEqual(applied.returncode, 2, applied.stderr)
        self.assertIn("result", applied.stderr)
        self.assertEqual(dest.read_text(encoding="utf-8"), "keep\n")

    def test_apply_stops_when_a_later_batch_renames_the_same_line(self) -> None:
        lines, candidate = self.agree("lines")
        (self.work / "lines" / "l999.json").write_text(
            json.dumps([{"id": "fixture-line-1", "題名": "架空の試験法律案"}], ensure_ascii=False), encoding="utf-8")
        dest = Path(self.tmp.name) / "renamed.csv"
        dest.write_text("keep\n", encoding="utf-8")
        applied = run("apply-candidates", "--work", str(self.work), "--kind", "lines", "--batch", lines["batch"],
                      "--candidate", str(candidate), "--inputs", str(self.work / "lines" / "inputs.json"),
                      "--dest", str(dest))
        self.assertEqual(applied.returncode, 2, applied.stderr)
        self.assertIn("題名", applied.stderr)
        self.assertEqual(dest.read_text(encoding="utf-8"), "keep\n")

    def test_apply_keeps_l1_when_a_later_batch_repeats_the_same_title(self) -> None:
        lines, candidate = self.agree("lines")
        (self.work / "lines" / "l999.json").write_text(json.dumps(
            [{"id": "fixture-line-1", "題名": "架空の試験法律の一部を改正する法律案"}], ensure_ascii=False), encoding="utf-8")
        dest = Path(self.tmp.name) / "same-title.csv"
        applied = run("apply-candidates", "--work", str(self.work), "--kind", "lines", "--batch", lines["batch"],
                      "--candidate", str(candidate), "--inputs", str(self.work / "lines" / "inputs.json"),
                      "--dest", str(dest))
        self.assertEqual(applied.returncode, 0, applied.stderr)
        with dest.open(encoding="utf-8") as handle:
            row = next(csv.DictReader(handle))
        self.assertEqual((row["採用"], row["決め方"]), ("保留", "規則で保留"))

    def test_tiebreak_agreement_uses_the_existing_header(self) -> None:
        tie = self.entry("tiebreak")
        labels = [{"id": "fixture-tie-1", "kind": "定型改正", "field": "金融", "reason": "期限だけ"}]
        candidate = Path(self.tmp.name) / "tie.json"
        result = run("verify-lanes", "--work", str(self.work), "--kind", "tiebreak", "--batch", tie["batch"],
                     "--lane-a", str(self.write_lane(tie, "a", labels)),
                     "--lane-b", str(self.write_lane(tie, "b", labels)),
                     "--candidate", str(candidate))
        self.assertEqual(result.returncode, 0, result.stderr)
        dest = Path(self.tmp.name) / "tie.csv"
        applied = run("apply-candidates", "--work", str(self.work), "--kind", "tiebreak", "--batch", tie["batch"],
                      "--candidate", str(candidate), "--dest", str(dest))
        self.assertEqual(applied.returncode, 0, applied.stderr)
        self.assertEqual(dest.read_text(encoding="utf-8").splitlines()[0], "id,種類,分野,決め方,理由")


if __name__ == "__main__":
    unittest.main()
