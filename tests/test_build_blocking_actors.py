import csv
import tempfile
import unittest
from pathlib import Path

from scripts.build_blocking_actors import build


class BuildBlockingActorsTest(unittest.TestCase):
    def test_drops_name_columns_and_rows_without_url(self):
        with tempfile.TemporaryDirectory() as d:
            src = Path(d) / "src"
            (src / "2_shingikai").mkdir(parents=True)
            (src / "2_shingikai" / "x.csv").write_text(
                "会議名,発言者名,立場,出典URL\n"
                "検討会A,山田,反対（山田は導入に反対）,https://www.mhlw.go.jp/a.pdf\n"
                "検討会B,佐藤,慎重,\n",
                encoding="utf-8",
            )
            out = Path(d) / "out"
            manifest = build(src, out)
            with (out / "2_shingikai" / "x.csv").open(encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertNotIn("発言者名", rows[0])
            self.assertEqual(rows[0]["立場"], "反対（（氏名）は導入に反対）")
            self.assertEqual(manifest[0]["URLなしで除外"], "1")
            self.assertEqual(manifest[0]["落とした氏名列"], "発言者名")


if __name__ == "__main__":
    unittest.main()
