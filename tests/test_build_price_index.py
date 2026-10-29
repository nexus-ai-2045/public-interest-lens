import json
import tempfile
import unittest
from pathlib import Path

from scripts import build_price_index as p

HEADER = '国,産業,指標,価格,年,値,単位,基準年,出典URL\n'
from _data_gate import requires_data  # noqa: E402


class PriceIndexTests(unittest.TestCase):
    def test_deflator_is_nominal_over_real(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'va.csv'
            path.write_text(HEADER + '\n'.join([
                'JPN,_T,B1G,V,2019,110,百万JPY,2020,u',
                'JPN,_T,B1G,LR,2019,100,百万JPY,2020,u',
                'JPN,_T,B1G,L,2019,100,百万JPY,2020,u',
                'JPN,J,B1G,V,2019,999,百万JPY,2020,u',
                'USA,_T,B1G,V,2019,999,百万USD,2020,u',
                'JPN,_T,B1G,V,2020,100,百万JPY,2020,u',
                'JPN,_T,B1G,LR,2020,100,百万JPY,2020,u',
                'JPN,_T,B1G,V,2021,105,百万JPY,2020,u',
                'JPN,_T,B1G,LR,2018,90,百万JPY,2020,u',
            ]) + '\n', encoding='utf-8')
            got = p.build(path)
        self.assertEqual(got['deflator'], {'2019': 110.0, '2020': 100.0})
        self.assertEqual(got['latestYear'], 2020)

    @requires_data("industry_va")
    def test_generated_file_is_current(self):
        # Git に置かない派生物なので、無ければ（単独実行・クリーンなチェックアウト）入力からここで作る。あれば入力と一致するかを見る
        built = json.loads(json.dumps(p.build(), ensure_ascii=False))
        if p.OUTPUT.exists():
            self.assertEqual(json.loads(p.OUTPUT.read_text(encoding='utf-8')), built)
        self.assertEqual(built['deflator']['2020'], 100.0)


if __name__ == '__main__':
    unittest.main()
