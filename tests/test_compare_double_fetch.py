import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.compare_double_fetch import compare


def write(folder: Path, rows: list[dict]) -> None:
    folder.mkdir(parents=True)
    with (folder / 'x.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


class CompareDoubleFetchTest(unittest.TestCase):
    def test_keeps_only_rows_that_agree(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write(root / 'a', [
                {'回次': '190', '番号': '1', '件名': '甲法案', '状況': '成立', '出典URL': 'https://example.go.jp/1'},
                {'回次': '190', '番号': '2', '件名': '乙法案', '状況': '成立', '出典URL': 'https://example.go.jp/2'},
                {'回次': '190', '番号': '3', '件名': '丙法案', '状況': '撤回', '出典URL': 'https://example.go.jp/3'},
            ])
            write(root / 'b', [
                {'回次': '190', '番号': '1', '件名': '甲法案 ', '状況': '成立', '出典URL': 'https://example.go.jp/1'},
                {'回次': '190', '番号': '2', '件名': '乙法案', '状況': '未了', '出典URL': 'https://example.go.jp/2'},
            ])
            summary = compare(root / 'a', root / 'b', ['回次', '番号'], ['件名', '状況'], root / 'out')
            self.assertEqual(summary['一致'], 1)
            self.assertEqual(summary['保留'], 2)
            disputed = list(csv.DictReader((root / 'out' / 'disputed.csv').open(encoding='utf-8')))
            self.assertEqual({r['番号']: r['理由'][:4] for r in disputed}, {'2': '値が食い', '3': '系統Aの'})
            self.assertEqual(json.loads((root / 'out' / 'summary.json').read_text(encoding='utf-8'))['一致'], 1)


if __name__ == '__main__':
    unittest.main()
