import json
import tempfile
import unittest
from pathlib import Path

from scripts.build_economy_snapshot import build_snapshot
from scripts.register_external_material import register_local_material


class EconomySnapshotTests(unittest.TestCase):
    def test_series_and_per_capita_are_derived_without_filling_gaps(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for identifier, values in {'NY.GDP.MKTP.KN': [100, None, 200], 'NY.GDP.MKTP.CN': [90, 100, 220], 'SP.POP.TOTL': [10, 10, 20]}.items():
                rows = [{'indicator': {'id': identifier}, 'countryiso3code': 'JPN', 'date': str(2020 + i), 'value': value} for i, value in enumerate(values)]
                (root / f'{identifier}.json').write_text(json.dumps([{'pages': 1, 'total': 3, 'lastupdated': '2026-10-01'}, rows]), encoding='utf-8')
            snapshot = build_snapshot(root)
            real = next(s for s in snapshot['series'] if s['id'] == 'real_gdp')
            capita = next(s for s in snapshot['series'] if s['id'] == 'real_gdp_per_capita')
            self.assertEqual([point['value'] for point in real['points']], [100, None, 200])
            self.assertEqual([point['value'] for point in capita['points']], [10, None, 10])
            self.assertNotIn(str(root), json.dumps(snapshot))
            self.assertNotIn('sourceObservedAt', real)

    def test_registered_sources_keep_observation_time_and_reject_tampering(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            direct = root / 'direct'
            direct.mkdir()
            records = []
            for index, (identifier, values) in enumerate({'NY.GDP.MKTP.KN': [100, None, 200], 'NY.GDP.MKTP.CN': [90, 100, 220], 'SP.POP.TOTL': [10, 10, 20]}.items()):
                rows = [{'indicator': {'id': identifier}, 'countryiso3code': 'JPN', 'date': str(2020 + i), 'value': value} for i, value in enumerate(values)]
                source = direct / f'{identifier}.json'
                source.write_text(json.dumps([{'pages': 1, 'total': 3, 'lastupdated': '2026-10-01'}, rows]), encoding='utf-8')
                with self.assertRaises(ValueError):
                    build_snapshot(direct, registered=True)
                observed = f'2026-10-0{index + 1}T00:00:00+00:00'
                records.append(register_local_material(input_path=source, source_url=f'https://api.worldbank.org/v2/country/JPN/indicator/{identifier}?format=json', task_id=f'economy-{identifier}', title=identifier, purpose='統計の再生成', storage_root=root / 'registered', observed_at=observed))
            snapshot = build_snapshot(root / 'registered', registered=True)
            self.assertEqual(snapshot['observedAt'], '2026-10-03T00:00:00+00:00')
            self.assertEqual(next(s for s in snapshot['series'] if s['id'] == 'real_gdp')['sourceObservedAt'], '2026-10-01T00:00:00+00:00')
            self.assertNotIn('sourceObservedAt', next(s for s in snapshot['series'] if s['id'] == 'real_gdp_per_capita'))
            record = json.loads(records[0].read_text(encoding='utf-8'))
            saved = records[0].parent / record['saved_filename']
            saved.write_bytes(saved.read_bytes().replace(b'100', b'101', 1))
            with self.assertRaisesRegex(ValueError, 'ハッシュ'):
                build_snapshot(root / 'registered', registered=True)

    def test_wrong_country_or_incomplete_page_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            payload = [{'pages': 2, 'total': 1}, [{'indicator': {'id': 'NY.GDP.MKTP.KN'}, 'countryiso3code': 'USA', 'date': '2020', 'value': 100}]]
            (root / 'NY.GDP.MKTP.KN.json').write_text(json.dumps(payload), encoding='utf-8')
            with self.assertRaises(ValueError):
                build_snapshot(root)


if __name__ == '__main__':
    unittest.main()
