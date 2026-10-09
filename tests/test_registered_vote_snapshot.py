"""旧表の全行を期間付き非公開評価入力へ投影する検査。"""

import tempfile
import unittest
from pathlib import Path

from scripts.fetch_sangiin_votes import CANONICAL
from scripts.register_external_material import register_local_material
from scripts.registered_vote_snapshot import build_snapshot


def legacy_fixture():
    title = "架空の情報処理法案"
    return (
        "<html><meta charset='utf-8'>第200回国会 2019年 11月 29日"
        f"<table><tr><th>案件名：</th><td>日程第４　{title}（内閣提出）</td></tr></table>"
        "<p>投票総数 2　賛成票 1　反対票 1</p>"
        "<table><caption class='party'>架空会派(3名)<br>賛成票 1　反対票 1</caption>"
        "<tr><td class='pro'><img src='../images/sansei.jpg' alt='票'></td>"
        "<td class='con'>　</td><td class='nam'>架空一郎</td>"
        "<td class='pro'>　</td><td class='con'><img src='../images/hantai.jpg' alt='票'></td>"
        "<td class='nam'>架空二郎</td>"
        "<td class='pro'>　</td><td class='con'>　</td>"
        "<td class='nam'><img src='../images/spacer.gif' alt='投票なし'>架空三郎</td></tr>"
        "</table></html>"
    ).encode("utf-8"), title


class RegisteredVoteSnapshotTests(unittest.TestCase):
    def test_eight_year_window_keeps_all_rows_and_four_year_window_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            material_root = root / ".local" / "external-materials"
            source = root / "vote.html"
            payload, title = legacy_fixture()
            source.write_bytes(payload)
            record = register_local_material(
                input_path=source,
                source_url=CANONICAL["200-8"],
                task_id="old-vote-test",
                title="人工投票表",
                purpose="期間と全行",
                storage_root=material_root,
                observed_at="2026-10-03T00:00:00+09:00",
            )
            params = {
                "record_path": record,
                "material_root": material_root,
                "bill_id": "200-8",
                "title": title,
                "url": CANONICAL["200-8"],
                "as_of": "2026-10-03",
                "period": 8,
            }
            snapshot = build_snapshot(**params)
            self.assertEqual(len(snapshot["materialRefs"]), 3)
            self.assertEqual(
                [row["position"] for row in snapshot["readableEvidence"]["votes"]],
                ["for", "against", "not_voted"],
            )
            self.assertEqual(snapshot["evidenceEvaluation"]["options"]["period"], 8)
            with self.assertRaises(ValueError):
                build_snapshot(**{**params, "period": 4})


if __name__ == "__main__":
    unittest.main()
