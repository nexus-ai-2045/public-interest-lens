"""届出団体の公開ファイル（scripts/build_political_funds_groups.py）の人物の結び方。架空の名前だけを使う。"""
import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import build_political_funds_groups as bpf

PDF = "https://www.soumu.go.jp/main_content/000000001.pdf"
HEADER = ["氏名", "届出上の氏名", "院", "選挙区", "届出先", "団体名", "区分", "種別", "名簿", "資料URL", "material_id"]


def row(name, house, group, url=PDF):
    return [name, "", house, "架空1", "総務大臣", group, "", "資金管理団体", "架空の名簿", url, "m"]


class BuildPoliticalFundsGroupsTest(unittest.TestCase):
    def run_build(self, rows, persons):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (root / "groups.csv").open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(HEADER)
                w.writerows(rows)
            (root / "persons.csv").write_text("人物ID,氏名,読み,院,選挙区,別表記\n" + "".join(f"{i},{n},,{h},,\n" for i, n, h in persons), encoding="utf-8")
            with mock.patch.object(bpf, "GROUPS", root / "groups.csv"), mock.patch.object(bpf, "PERSONS", root / "persons.csv"):
                return bpf.build()

    def test_links_only_unique_people_and_counts_the_rest(self):
        persons = [("山田花", "山田花", "衆議院"), ("森川空（衆）", "森川空", "衆議院"), ("森川空（参）", "森川空", "参議院"), ("同名", "同名", "衆議院"), ("同名（別）", "同名", "衆議院")]
        out = self.run_build([row("山田 花", "衆", "花の会"), row("森川 空", "参", "空の会"), row("同名", "衆", "迷いの会"), row("無名 人", "衆", "名簿外の会")], persons)
        self.assertEqual(sorted(out["members"]), ["山田花", "森川空（参）"])
        self.assertEqual(out["counts"], {"rosterMembers": 4, "linkedMembers": 2, "unlinkedMembers": 2, "groups": 2})

    def test_same_group_in_two_rosters_is_one_group_with_two_sources(self):
        other = "https://www.soumu.go.jp/main_content/000000002.pdf"
        out = self.run_build([row("山田 花", "衆", "花の会"), row("山田 花", "衆", "花の会", other)], [("山田花", "山田花", "衆議院")])
        self.assertEqual(out["members"]["山田花"][0]["sources"], [PDF, other])

    def test_rejects_non_soumu_source(self):
        with self.assertRaises(ValueError):
            self.run_build([row("山田 花", "衆", "花の会", "https://example.com/a.pdf")], [("山田花", "山田花", "衆議院")])


if __name__ == "__main__":
    unittest.main()
