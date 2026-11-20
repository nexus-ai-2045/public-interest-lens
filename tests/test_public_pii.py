"""公開版のビルドは、名簿の「議員名」（出してよい欄）に個人情報の形が入ったら失敗する。

原因：#211 が旧 members.json 向けの tests/test_public_members_safety.py を付け替えずに消したため、
公開ビルド（vercel deploy が実行する VITE_PUBLIC_SITE=true npm run build）は個人情報の形を見ない。
"""

from __future__ import annotations

import csv
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.check_public_pii import scan

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = Path("data/acquired/sangiin-votes/members.csv")
MARKER = "FAKEPII-MARKER fake@example.com 000-0000-0000"
# 検査を止めるための環境変数。検査はこれらを見ない（生成を飛ばす KOKUZOKU_SKIP_GENERATE は、名簿が公開データへ乗らないので立てない）。
SKIP_ENV = {
    "SKIP_PUBLIC_PII": "1",
    "CHECK_PUBLIC_PII": "0",
    "KOKUZOKU_SKIP_PUBLIC_PII": "1",
    "PUBLIC_PII_CHECK": "skip",
}
# 上書きすると実体が元のリポジトリと共有されたまま壊れる出力。先にリンクを外す。
DETACH = [
    "docs/評価台帳.md",
    "data/derived/exposure-v1/exposure-ranking.json",
    "data/derived/evaluation-ledger-v1/ledger.csv",
    "data/derived/source-check/summary.json",
    "data/derived/source-check/check.csv",
    "app/public/distribution/price-index.json",
    "app/public/distribution/ranking.json",
    "app/public/distribution/votes.json",
    "app/public/distribution/laws.json",
    "app/public/distribution/law-names.json",
    "app/public/distribution/law-outcomes.json",
    "app/public/distribution/provisional.json",
    "app/public/distribution/unenacted.json",
    "app/public/distribution/charts.json",
    "app/public/distribution/ledger-summary.json",
]


def _detach(path: Path) -> None:
    if path.is_file() or path.is_symlink():
        path.unlink()


def _poison_roster(path: Path) -> None:
    """議員名の欄だけに、印・作り物のメール・電話番号を足す。列名は変えない。"""
    text = path.read_text(encoding="utf-8")
    _detach(path)
    rows = list(csv.reader(io.StringIO(text)))
    index = rows[0].index("議員名")
    poisoned = [rows[0]]
    for row in rows[1:]:
        if len(row) <= index:
            poisoned.append(row)
            continue
        copied = list(row)
        copied[index] = f"{copied[index]} {MARKER}".strip()
        poisoned.append(copied)
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(poisoned)
    path.write_text(buffer.getvalue(), encoding="utf-8")


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _mirror(dst: Path) -> None:
    """ファイルはハードリンクで並べ、上書きされる出力と名簿だけ別の実体にする。"""
    subprocess.run(["cp", "-al", str(ROOT), str(dst)], check=True)
    for rel in (".git", "app/node_modules", "app/dist", "app/.local"):
        _remove_tree(dst / rel)
    (dst / "app" / "node_modules").symlink_to(ROOT / "app" / "node_modules")
    for rel in DETACH:
        _detach(dst / rel)
    _poison_roster(dst / MEMBERS)


class PublicBuildPiiTest(unittest.TestCase):
    def test_public_build_fails_when_roster_name_contains_pii_shapes(self):
        """出してよい「議員名」にメールと電話の形を入れると、公開版のビルドが失敗する。"""
        if not (ROOT / "app" / "node_modules").exists():
            self.fail("app/node_modules が無い。app で npm ci してからやり直す")
        with tempfile.TemporaryDirectory(prefix="public-pii-") as tmp:
            work = Path(tmp) / "repo"
            _mirror(work)
            env = os.environ.copy()
            env.update(SKIP_ENV)
            env["VITE_PUBLIC_SITE"] = "true"
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            proc = subprocess.run(
                ["npm", "run", "build"],
                cwd=work / "app",
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        output = proc.stdout + proc.stderr
        tail = output[-4000:]
        self.assertNotEqual(
            proc.returncode,
            0,
            f"公開版のビルドが成功した（終了 {proc.returncode}）。名簿の議員名に個人情報の形が入っても止まらない。\n{tail}",
        )
        self.assertIn("FAKEPII-MARKER", output, f"失敗の理由が、入れた議員名ではない。\n{tail}")
        self.assertIn("fake@example.com", output, tail)
        self.assertIn("000-0000-0000", output, tail)


class PublicPiiScanTest(unittest.TestCase):
    def test_checker_does_not_read_environment(self):
        text = (ROOT / "scripts" / "check_public_pii.py").read_text(encoding="utf-8")
        self.assertNotIn("environ", text)
        self.assertNotIn("getenv", text)

    def test_public_tree_has_no_pii_shapes(self):
        self.assertEqual(scan(ROOT / "app" / "public"), [])

    def test_allowed_name_is_still_checked_by_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "votes.json"
            path.write_text(json.dumps({
                "members": [{"name": "公開氏名 FAKEPII-MARKER fake@example.com 000-0000-0000"}],
            }, ensure_ascii=False), encoding="utf-8")
            found = "\n".join(scan(Path(tmp)))
        self.assertIn("メール", found)
        self.assertIn("電話番号", found)
        self.assertIn("FAKEPII-MARKER", found)
        self.assertIn("fake@example.com", found)
        self.assertIn("000-0000-0000", found)

    def test_home_paths_and_keys_and_private_life_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "notes.json").write_text(json.dumps({
                "memo": "作業場 /home/fake/box と /Users/fake/box と C:\\Users\\fake\\box",
                "secret": "-----BEGIN PRIVATE KEY-----\nMII-FAKE",
                "address": "私生活は出さない",
                "page": "https://example.go.jp/home/index.html",
            }, ensure_ascii=False), encoding="utf-8")
            found = "\n".join(scan(root))
        self.assertIn("実ホームパス", found)
        self.assertIn("/home/fake/box", found)
        self.assertIn("/Users/fake/box", found)
        self.assertIn("C:\\Users\\fake\\box", found)
        self.assertIn("鍵", found)
        self.assertIn("私生活の項目", found)
        self.assertNotIn("example.go.jp/home", found)


if __name__ == "__main__":
    unittest.main()
