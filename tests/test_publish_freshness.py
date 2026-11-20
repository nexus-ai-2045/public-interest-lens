"""公開前の安全性（D2〜D7）が破れる経路。望む振る舞いを先に書いて、今のコードでは落とす。

原因（直す前の1行）:
- D2: ranking.json は mtime が入力より新しければ作り直されず、build_public_ranking.main は今の出典チェックを通さずに書くので、確かさを手で「高」にしても dist に入る。
- D3: KOKUZOKU_SKIP_GENERATE=1 は生成の入口が即 return するので、公開版のビルドでも出典チェックごと飛ばせる。
- D4: Path.write_text は開いた瞬間に ranking.json を空にするので、書き込みが途中で切れると切れた JSON が残る。
- D5: 同じ write_text が出典チェックの summary.json にも使われ、途中で切れると切れた JSON が残る。
- D6: 失敗案内は generate_artifacts.py を指すが、その入口は mtime が新しければ何もしないので、案内どおりに実行しても確かさは戻らない。
- D7: build_database.Db が共有の sqlite をロックなしで消して開き直すので、生成を2つ同時に走らせると disk I/O error になる。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import build_database, build_public_ranking, generate_artifacts, source_check


def _db_race_worker(path: str, queue) -> None:
    from scripts.build_database import Db

    try:
        db = Db(Path(path))
        db.con.execute("CREATE TABLE IF NOT EXISTS probe (id INTEGER)")
        for i in range(200):
            db.con.execute("INSERT INTO probe VALUES (?)", (i,))
        db.con.commit()
        queue.put("ok")
    except Exception as exc:
        queue.put(f"{type(exc).__name__}: {exc}")


class PublishFreshnessTests(unittest.TestCase):
    def test_newer_hand_edited_certainty_is_rebuilt(self) -> None:
        """入力より新しい ranking.json でも、手で確かさを「高」にしたファイルは出典チェックから作り直す。"""
        commands: list[list[str]] = []
        with tempfile.TemporaryDirectory() as directory:
            ranking = Path(directory) / "ranking.json"
            ranking.write_text(json.dumps({"laws": [{"id": "a", "certainty": "高"}]}), encoding="utf-8")
            future = ranking.stat().st_mtime + 10_000
            os.utime(ranking, (future, future))
            steps = [("inputs", ranking, [sys.executable, "scripts/source_check.py", "--generate-ranking"])]

            def fake_run(command, cwd=None, stdout=None):
                commands.append(list(command))
                if any("source_check.py" in part for part in command):
                    ranking.write_text(json.dumps({"laws": [{"id": "a", "certainty": "中"}]}), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(generate_artifacts, "STEPS", steps), \
                 mock.patch.object(generate_artifacts, "newest_input", return_value=0.0), \
                 mock.patch.object(generate_artifacts.subprocess, "run", fake_run):
                code = generate_artifacts.main([])
            self.assertEqual(code, 0)
            self.assertTrue(any("source_check.py" in part for command in commands for part in command))
            self.assertEqual(json.loads(ranking.read_text(encoding="utf-8"))["laws"][0]["certainty"], "中")

    def test_public_build_cannot_skip_generation(self) -> None:
        """KOKUZOKU_SKIP_GENERATE=1 でも、公開版のビルドは生成と出典チェックを飛ばさない。"""
        commands: list[list[str]] = []
        with tempfile.TemporaryDirectory() as directory:
            ranking = Path(directory) / "ranking.json"
            steps = [("inputs", ranking, [sys.executable, "scripts/source_check.py", "--generate-ranking"])]

            def fake_run(command, cwd=None, stdout=None):
                commands.append(list(command))
                ranking.write_text("{}\n", encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            env = os.environ.get("KOKUZOKU_SKIP_GENERATE")
            public = os.environ.get("VITE_PUBLIC_SITE")
            os.environ["KOKUZOKU_SKIP_GENERATE"] = "1"
            os.environ["VITE_PUBLIC_SITE"] = "true"
            try:
                with mock.patch.object(generate_artifacts, "STEPS", steps), \
                     mock.patch.object(generate_artifacts, "newest_input", return_value=0.0), \
                     mock.patch.object(generate_artifacts.subprocess, "run", fake_run):
                    try:
                        code = generate_artifacts.main(["--public-build"])
                    except SystemExit as exc:
                        code = exc.code
            finally:
                if env is None:
                    os.environ.pop("KOKUZOKU_SKIP_GENERATE", None)
                else:
                    os.environ["KOKUZOKU_SKIP_GENERATE"] = env
                if public is None:
                    os.environ.pop("VITE_PUBLIC_SITE", None)
                else:
                    os.environ["VITE_PUBLIC_SITE"] = public
        self.assertEqual(code, 0)
        self.assertTrue(any("source_check.py" in part for command in commands for part in command))

    def test_skip_generate_still_skips_outside_the_public_build(self) -> None:
        """架空入力の検査用のスキップは、公開版でないときは残る。"""
        commands: list[list[str]] = []
        env = os.environ.get("KOKUZOKU_SKIP_GENERATE")
        public = os.environ.get("VITE_PUBLIC_SITE")
        os.environ["KOKUZOKU_SKIP_GENERATE"] = "1"
        os.environ.pop("VITE_PUBLIC_SITE", None)
        try:
            with mock.patch.object(generate_artifacts.subprocess, "run", lambda *args, **kwargs: commands.append(args)):
                code = generate_artifacts.main([])
        finally:
            if env is None:
                os.environ.pop("KOKUZOKU_SKIP_GENERATE", None)
            else:
                os.environ["KOKUZOKU_SKIP_GENERATE"] = env
            if public is not None:
                os.environ["VITE_PUBLIC_SITE"] = public
        self.assertEqual(code, 0)
        self.assertEqual(commands, [])

    def test_public_build_script_calls_the_publish_check(self) -> None:
        """VITE_PUBLIC_SITE=true npm run build の build 本体から、公開ハッシュの確認を呼ぶ。"""
        package = json.loads((ROOT / "app" / "package.json").read_text(encoding="utf-8"))
        self.assertIn("generate_artifacts.py --public-build", package["scripts"]["build"])

    def test_stale_guidance_names_the_publish_hash(self) -> None:
        """失敗案内は、出典チェックの結果まで含んだ公開ハッシュが違う、と書く。"""
        body = {"approval": {"scope": "all-laws", "approvedAt": "2026-10-17"}, "laws": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranking.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            buf = StringIO()
            argv = ["source_check", "--dry-run", "--ranking", str(path)]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(source_check, "rebuild", return_value={"rankingStale": True, "mismatch": 0}), \
                 redirect_stderr(buf):
                code = source_check.main()
        self.assertEqual(code, 1)
        self.assertIn("公開ハッシュ", buf.getvalue())
        self.assertIn("python3 scripts/generate_artifacts.py", buf.getvalue())

    def test_following_the_stale_guidance_restores_the_hand_edit(self) -> None:
        """案内に書いたコマンドを実行すると、手で「高」にした確かさが戻る。"""
        body = {"approval": {"scope": "all-laws", "approvedAt": "2026-10-17"}, "laws": [{"id": "a", "certainty": "高"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranking.json"
            path.write_text(json.dumps(body), encoding="utf-8")
            buf = StringIO()
            argv = ["source_check", "--dry-run", "--ranking", str(path)]
            with mock.patch.object(sys, "argv", argv), \
                 mock.patch.object(source_check, "rebuild", return_value={"rankingStale": True, "mismatch": 0}), \
                 redirect_stderr(buf):
                source_check.main()
            text = buf.getvalue()
            self.assertIn("python3 scripts/generate_artifacts.py", text)
            future = path.stat().st_mtime + 10_000
            os.utime(path, (future, future))
            steps = [("inputs", path, [sys.executable, "scripts/source_check.py", "--generate-ranking"])]

            def fake_run(command, cwd=None, stdout=None):
                if any("source_check.py" in part for part in command):
                    path.write_text(json.dumps({"laws": [{"id": "a", "certainty": "中"}]}), encoding="utf-8")
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(generate_artifacts, "STEPS", steps), \
                 mock.patch.object(generate_artifacts, "newest_input", return_value=0.0), \
                 mock.patch.object(generate_artifacts.subprocess, "run", fake_run):
                # 案内のコマンドは python3 scripts/generate_artifacts.py。入口は main。
                code = generate_artifacts.main([])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["laws"][0]["certainty"], "中")

    def test_ranking_command_runs_the_current_source_check(self) -> None:
        """公開ランキングのコマンドは、今の出典チェックを通した1本の経路でだけ書く。"""
        checked: dict[str, bool] = {}
        payload = {
            "schema": "public-ranking/v3",
            "laws": [],
            "others": [],
            "counts": {"published": 0},
            "generatedFrom": {"inputs": {}},
        }
        summary = {"heldOut": [], "mismatch": 0, "items": 0, "match": 0, "notApplicable": 0}

        def fake_check(ranking, ctx):
            checked["called"] = True
            return [], summary

        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "ranking.json"
            argv = ["build_public_ranking", "--approve-all-laws", "--approved-at", "2026-10-17", "--output", str(out)]
            with mock.patch.object(build_public_ranking, "build", return_value=payload), \
                 mock.patch.object(source_check, "check", fake_check), \
                 mock.patch.object(source_check, "context", return_value={}), \
                 mock.patch.object(sys, "argv", argv):
                code = build_public_ranking.main()
        self.assertEqual(code, 0)
        self.assertTrue(checked.get("called"))

    def test_cut_ranking_write_keeps_the_previous_json(self) -> None:
        """ranking.json の書き出しが途中で切れても、前の完全な JSON が残る。"""
        previous = {"schema": "public-ranking/v3", "laws": [{"id": "kept", "certainty": "中"}]}
        payload = {
            "schema": "public-ranking/v3",
            "laws": [{"id": "new", "certainty": "低"}],
            "generatedFrom": {"inputs": {}},
        }
        summary = {"heldOut": [], "mismatch": 0, "items": 0, "match": 0, "notApplicable": 0}
        with tempfile.TemporaryDirectory() as directory:
            ranking = Path(directory) / "ranking.json"
            ranking.write_text(json.dumps(previous), encoding="utf-8")

            def crash(src, dst, *args, **kwargs):
                raise RuntimeError("interrupt")

            with mock.patch.object(build_public_ranking, "build", return_value=payload), \
                 mock.patch.object(source_check, "check", return_value=([], summary)), \
                 mock.patch.object(source_check, "context", return_value={}), \
                 mock.patch.object(source_check, "write_report"), \
                 mock.patch("os.replace", crash):
                try:
                    source_check.rebuild(True, "2026-10-17", ranking, write=True)
                except RuntimeError:
                    pass
            self.assertEqual(json.loads(ranking.read_text(encoding="utf-8")), previous)

    def test_cut_summary_write_keeps_the_previous_json(self) -> None:
        """出典チェックの summary.json の書き出しが途中で切れても、前の完全な JSON が残る。"""
        previous = '{"kept": true}\n'
        rows = [{"id": "a", "項目": "題名", "公開値": "x", "一次資料の値": "x", "結果": source_check.OK, "備考": ""}]
        summary = {"heldOut": [], "mismatch": 0, "items": 1, "match": 1, "notApplicable": 0, "rawFilesPresent": 0}
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory)
            target = report / "summary.json"
            target.write_text(previous, encoding="utf-8")

            def crash(src, dst, *args, **kwargs):
                raise RuntimeError("interrupt")

            with mock.patch("os.replace", crash):
                try:
                    source_check.write_report(rows, summary, report)
                except RuntimeError:
                    pass
            self.assertEqual(target.read_text(encoding="utf-8"), previous)

    def test_two_database_builds_do_not_raise_disk_io_error(self) -> None:
        """sqlite を同時に作り直しても disk I/O error にならない。"""
        import multiprocessing as mp

        ctx = mp.get_context("fork")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "db.sqlite")
            queue = ctx.Queue()
            procs = [ctx.Process(target=_db_race_worker, args=(path, queue)) for _ in range(2)]
            for proc in procs:
                proc.start()
            for proc in procs:
                proc.join(15)
            results = [queue.get(timeout=5) for _ in procs]
        self.assertEqual(sorted(results), ["ok", "ok"], results)

    def test_two_force_runs_do_not_overlap(self) -> None:
        """generate_artifacts.py --force を2つ同時に走らせても、生成の本体は重ならない。"""
        overlap = {"n": 0, "max": 0}
        gate = threading.Lock()

        def fake_run(command, cwd=None, stdout=None):
            with gate:
                overlap["n"] += 1
                overlap["max"] = max(overlap["max"], overlap["n"])
            try:
                threading.Event().wait(0.3)
            finally:
                with gate:
                    overlap["n"] -= 1
            return subprocess.CompletedProcess(command, 0)

        with tempfile.TemporaryDirectory() as directory:
            ranking = Path(directory) / "out.json"
            steps = [("inputs", ranking, [sys.executable, "scripts/source_check.py", "--generate-ranking"])]
            errors: list[BaseException] = []

            def run() -> None:
                try:
                    code = generate_artifacts.main(["--force"])
                    if code != 0:
                        errors.append(RuntimeError(f"exit {code}"))
                except BaseException as exc:
                    errors.append(exc)

            # パッチはスレッドの外に置く。スレッドごとに付け外しすると、片方が戻した瞬間にもう片方が本物の生成を走らせる。
            with mock.patch.object(generate_artifacts, "STEPS", steps), \
                 mock.patch.object(generate_artifacts, "newest_input", return_value=0.0), \
                 mock.patch.object(generate_artifacts.subprocess, "run", fake_run):
                threads = [threading.Thread(target=run) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(10)
                alive = [thread.name for thread in threads if thread.is_alive()]
        self.assertEqual(alive, [])
        self.assertEqual(errors, [])
        self.assertEqual(overlap["max"], 1)


if __name__ == "__main__":
    unittest.main()
