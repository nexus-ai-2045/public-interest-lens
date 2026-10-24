"""scripts/fetch_r3_series.py の応答の解釈・計画・再開の確認（通信しない。フィクスチャと偽の取得関数を使う）。"""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import fetch_r3_series as f  # noqa: E402

WB_OK = json.dumps([
    {'page': 1, 'pages': 1, 'per_page': 2000, 'total': 5},
    [
        {'indicator': {'id': 'IS.AIR.PSGR'}, 'country': {'id': 'JP', 'value': 'Japan'}, 'countryiso3code': 'JPN', 'date': '2019', 'value': 123456789.0},
        {'indicator': {'id': 'IS.AIR.PSGR'}, 'country': {'id': 'JP', 'value': 'Japan'}, 'countryiso3code': 'JPN', 'date': '2020', 'value': None},
        {'indicator': {'id': 'IS.AIR.PSGR'}, 'country': {'id': 'US', 'value': 'United States'}, 'countryiso3code': 'USA', 'date': '2019', 'value': 926737000},
        {'indicator': {'id': 'IS.AIR.PSGR'}, 'country': {'id': 'EU', 'value': 'European Union'}, 'countryiso3code': 'EUU', 'date': '2019', 'value': 1.0},
        {'indicator': {'id': 'IS.AIR.PSGR'}, 'country': {'id': 'FR', 'value': 'France'}, 'countryiso3code': 'FRA', 'date': '2018', 'value': 0},
    ],
], ensure_ascii=False)
WB_ERR = json.dumps([{'message': [{'id': '120', 'key': 'Invalid value', 'value': 'The provided parameter value is not valid'}]}])
WB_PAGED = json.dumps([{'page': 1, 'pages': 2, 'per_page': 1, 'total': 2}, [
    {'countryiso3code': 'JPN', 'date': '2019', 'value': 1.5}]])
WB_PAGE2 = json.dumps([{'page': 2, 'pages': 2, 'per_page': 1, 'total': 2}, [
    {'countryiso3code': 'JPN', 'date': '2018', 'value': 1.25}]])

SDMX = ('STRUCTURE,STRUCTURE_ID,ACTION,REF_AREA,MEASURE,SEX,AGE,TENURE,FREQ,TIME_PERIOD,OBS_VALUE,UNIT_MEASURE,UNIT_MULT,OBS_STATUS\n'
        'DATAFLOW,OECD.ELS.SAE:DSD_TENURE@DF_TENURE_FREQ(1.0),I,JPN,TENURE_EMP,_T,_T,M_LT12,A,2013,10.5,PT_POP_SUB,0,A\n'
        'DATAFLOW,OECD.ELS.SAE:DSD_TENURE@DF_TENURE_FREQ(1.0),I,JPN,TENURE_EMP,_T,_T,M_LT12,A,2014,,PT_POP_SUB,0,M\n'
        'DATAFLOW,OECD.ELS.SAE:DSD_TENURE@DF_TENURE_FREQ(1.0),I,JPN,TENURE_EMP,_T,_T,M_LT12,A,2015,10.25,PT_POP_SUB,3,A\n'
        'DATAFLOW,OECD.ELS.SAE:DSD_TENURE@DF_TENURE_FREQ(1.0),I,FRA,TENURE_EMP,_T,_T,Y_GE10,A,2015,40.0,PT_POP_SUB,0,A\n')


class WbParse(unittest.TestCase):
    def parse(self, text):
        return f.parse_wb_json(text, 'IS.AIR.PSGR', '航空旅客数', '人', 'URL')

    def test_rows_skip_null_and_aggregates(self):
        rows, pages = self.parse(WB_OK)
        self.assertEqual(pages, 1)
        self.assertEqual([(r['国'], r['年'], r['値']) for r in rows], [('FRA', '2018', '0'), ('JPN', '2019', '123456789.0'), ('USA', '2019', '926737000')])
        self.assertTrue(all(r['指標'] == 'WB:IS.AIR.PSGR' for r in rows))
        self.assertEqual(set(rows[0]), set(f.OUT_COLUMNS))

    def test_zero_is_kept_and_null_is_never_filled(self):
        rows, _ = self.parse(WB_OK)
        self.assertIn(('FRA', '2018', '0'), [(r['国'], r['年'], r['値']) for r in rows])
        self.assertNotIn(('JPN', '2020'), [(r['国'], r['年']) for r in rows])

    def test_error_body_raises(self):
        with self.assertRaises(ValueError) as cm:
            self.parse(WB_ERR)
        self.assertIn('120', str(cm.exception))

    def test_not_json_and_wrong_shape_raise(self):
        for bad in ('<html>', '{}', '[]', '[1]'):
            with self.assertRaises(ValueError):
                self.parse(bad)

    def test_pages_reported(self):
        rows, pages = self.parse(WB_PAGED)
        self.assertEqual((pages, len(rows)), (2, 1))

    def test_empty_data_page(self):
        rows, pages = self.parse(json.dumps([{'page': 1, 'pages': 1, 'total': 0}, None]))
        self.assertEqual((rows, pages), ([], 1))

    def test_conflicting_duplicates_raise(self):
        dup = json.dumps([{'page': 1, 'pages': 1}, [{'countryiso3code': 'JPN', 'date': '2019', 'value': 1}, {'countryiso3code': 'JPN', 'date': '2019', 'value': 2}]])
        with self.assertRaises(ValueError):
            self.parse(dup)


class SdmxParse(unittest.TestCase):
    def test_rows_and_indicator_name(self):
        rows = f.parse_sdmx_csv(SDMX, 'OECD:TENURE_FREQ', 'URL')
        self.assertEqual([(r['国'], r['指標'], r['年'], r['値']) for r in rows], [
            ('JPN', 'OECD:TENURE_FREQ:TENURE_EMP._T._T.M_LT12', '2013', '10.5'),
            ('JPN', 'OECD:TENURE_FREQ:TENURE_EMP._T._T.M_LT12', '2015', '10.25'),
            ('FRA', 'OECD:TENURE_FREQ:TENURE_EMP._T._T.Y_GE10', '2015', '40.0'),
        ])

    def test_dataflow_format_keeps_metadata_out_of_the_name(self):
        # OECD が実際に返した形（先頭が DATAFLOW 列、ACTION・STRUCTURE_ID なし、属性は OBS_VALUE の後ろ）
        text = ('DATAFLOW,REF_AREA,MEASURE,UNIT_MEASURE,SEX,AGE,TENURE,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MULT\n'
                'OECD.ELS.SAE:DSD_TENURE@DF_TENURE_FREQ(1.0),JPN,TENURE_EMP,PT_POP_SUB,F,Y15T24,M_1T5,A,2013,20.502,A,0\n')
        rows = f.parse_sdmx_csv(text, 'OECD:TENURE_FREQ', 'URL')
        self.assertEqual([r['指標'] for r in rows], ['OECD:TENURE_FREQ:TENURE_EMP.PT_POP_SUB.F.Y15T24.M_1T5'])

    def test_empty_value_dropped_and_unit_mult_noted(self):
        rows = f.parse_sdmx_csv(SDMX, 'P', 'URL')
        self.assertNotIn('2014', [r['年'] for r in rows])
        self.assertEqual([r['単位'] for r in rows if r['年'] == '2015' and r['国'] == 'JPN'], ['PT_POP_SUB（UNIT_MULT=3）'])

    def test_country_filter_and_bom(self):
        rows = f.parse_sdmx_csv('﻿' + SDMX, 'P', 'URL', countries=['JPN'])
        self.assertEqual({r['国'] for r in rows}, {'JPN'})

    def test_missing_column_raises(self):
        with self.assertRaises(ValueError):
            f.parse_sdmx_csv('REF_AREA,OBS_VALUE\nJPN,1\n', 'P', 'URL')

    def test_conflict_raises(self):
        dup = SDMX + 'DATAFLOW,X,I,JPN,TENURE_EMP,_T,_T,M_LT12,A,2013,99,PT_POP_SUB,0,A\n'
        with self.assertRaises(ValueError):
            f.parse_sdmx_csv(dup, 'P', 'URL')

    def test_header_only_gives_no_rows(self):
        self.assertEqual(f.parse_sdmx_csv(SDMX.splitlines()[0] + '\n', 'P', 'URL'), [])


class Coverage(unittest.TestCase):
    def test_coverage_and_text(self):
        rows, _ = f.parse_wb_json(WB_OK, 'IS.AIR.PSGR', 'x', 'y', 'U')
        cov = f.coverage(rows)['WB:IS.AIR.PSGR']
        self.assertEqual(cov['JPN'], (2019, 2019, 1))
        text = f.describe_coverage(cov)
        self.assertIn('3/13か国', text)
        self.assertIn('日本 2019〜2019年', text)
        self.assertEqual(f.describe_coverage({}), '値のある国なし')
        self.assertIn('日本の値なし', f.describe_coverage({'USA': (2000, 2001, 2)}))

    def test_non_year_periods_not_counted(self):
        self.assertEqual(f.coverage([{'国': 'JPN', '指標': 'a', '年': '2020-Q1', '値': '1'}]), {})


class Plan(unittest.TestCase):
    def test_default_plan_covers_everything(self):
        plan = f.plan_requests()
        self.assertEqual([p['id'] for p in plan], list(f.WB_SERIES) + list(f.OECD_SERIES))

    def test_only_filters(self):
        self.assertEqual({p['kind'] for p in f.plan_requests(['wb'])}, {'wb'})
        self.assertEqual([p['id'] for p in f.plan_requests(['is.air.psgr'])], ['IS.AIR.PSGR'])
        self.assertEqual([p['id'] for p in f.plan_requests(['oecd'])], ['TENURE-JPN'])

    def test_unknown_only_raises(self):
        with self.assertRaises(ValueError):
            f.plan_requests(['nope'])

    def test_urls(self):
        u = f.wb_url('IS.AIR.PSGR')
        self.assertTrue(u.startswith('https://api.worldbank.org/v2/country/JPN;USA;'))
        self.assertIn('/indicator/IS.AIR.PSGR?format=json&per_page=2000', u)
        self.assertTrue(f.wb_url('X', 2).endswith('&page=2'))
        self.assertNotIn('page=', f.wb_url('X').replace('per_page', ''))
        self.assertTrue(f.oecd_url('TENURE-JPN').startswith('https://sdmx.oecd.org/public/rest/data/OECD.ELS.SAE,DSD_TENURE@DF_TENURE_FREQ,1.0/JPN......?'))
        self.assertEqual(f.oecd_url('TENURE-JPN').split('/')[-1].split('?')[0].count('.'), 6)  # 7次元

    def test_rel_path_never_leaks_absolute(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            self.assertEqual(f.rel_path(Path(a) / 'x' / 'y.json', Path(a)), 'x/y.json')
            self.assertEqual(f.rel_path(Path(b) / 'y.json', Path(a)), 'y.json')


class FetchAndRun(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.raw, self.out = self.root / '.local' / 'raw', self.root / 'out'
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def opener(self, responses):
        def go(url, accept):
            self.calls.append(url)
            return responses.get(url.split('/indicator/')[-1].split('?')[0] if '/indicator/' in url else 'oecd', (404, None))
        return go

    def manifest(self):
        with (self.out / 'manifest.csv').open(encoding='utf-8') as fh:
            return list(csv.DictReader(fh))

    def test_fetch_records_sha_and_resumes_without_network(self):
        plan = f.plan_requests(['IS.AIR.PSGR'])
        op = self.opener({'IS.AIR.PSGR': (200, WB_OK.encode())})
        rows, status, failed = f.run(plan, self.raw, self.out, self.root, opener=op, sleep=lambda s: None)
        self.assertEqual((len(rows), failed), (3, []))
        m = self.manifest()
        self.assertEqual(m[0]['sha256'], hashlib.sha256(WB_OK.encode()).hexdigest())
        self.assertEqual((m[0]['http'], m[0]['path']), ('200', '.local/raw/wb/IS.AIR.PSGR.json'))
        self.assertEqual(status[0][2], '取得できた')
        # 原本は外部資料として登録する（AGENTS.md：.local/external-materials/<task-id>/、初期状態 unverified）
        record = json.loads((self.root / '.local' / 'external-materials' / f.TASK_ID / m[0]['material_id'] / 'record.json').read_text(encoding='utf-8'))
        self.assertEqual((record['sha256'], record['content_verification']), (m[0]['sha256'], 'unverified'))
        n = len(self.calls)
        f.run(plan, self.raw, self.out, self.root, opener=op, sleep=lambda s: None)  # 再開：通信しない
        self.assertEqual(len(self.calls), n)
        self.assertEqual(len(self.manifest()), 1)  # 取得済みの原本は manifest に重複して書かない
        (self.out / 'manifest.csv').unlink()  # manifest が無い出力先で原本を使うときは、取得元とハッシュを cache として残す
        f.run(plan, self.raw, self.out, self.root, opener=op, sleep=lambda s: None)
        self.assertEqual(len(self.calls), n)
        self.assertEqual((self.manifest()[0]['http'], self.manifest()[0]['sha256']), ('cache', hashlib.sha256(WB_OK.encode()).hexdigest()))
        self.assertEqual(self.manifest()[0]['material_id'], m[0]['material_id'])  # 控えから作り直しても、同じ登録を指す

    def test_prior_manifest_keeps_the_first_fetch_time(self):
        # manifest を作り直しても、前の manifest に同じ URL・置き場所・中身の行があれば HTTP と取得時刻を引き継ぐ
        plan = f.plan_requests(['IS.AIR.PSGR'])
        op = self.opener({'IS.AIR.PSGR': (200, WB_OK.encode())})
        f.run(plan, self.raw, self.out, self.root, opener=op, sleep=lambda s: None)
        first = self.manifest()[0]
        prior = self.out / 'manifest.prev.csv'
        (self.out / 'manifest.csv').replace(prior)
        f.run(plan, self.raw, self.out, self.root, opener=op, sleep=lambda s: None, prior=f.prior_fetches(prior))
        again = self.manifest()[0]
        self.assertEqual((again['http'], again['fetched_at']), (first['http'], first['fetched_at']))
        self.assertTrue(again['fetched_at'])

    def test_interval_is_waited_before_each_request(self):
        waits = []
        f.run(f.plan_requests(['IS.AIR.PSGR']), self.raw, self.out, self.root, opener=self.opener({'IS.AIR.PSGR': (200, WB_OK.encode())}), sleep=waits.append)
        self.assertEqual(waits, [f.INTERVAL_SECONDS])

    def test_http_failure_is_recorded_and_not_cached(self):
        plan = f.plan_requests(['IS.RRS.PASG.KM'])
        rows, status, failed = f.run(plan, self.raw, self.out, self.root, opener=self.opener({'IS.RRS.PASG.KM': (403, None)}), sleep=lambda s: None)
        self.assertEqual((rows, failed), ([], ['IS.RRS.PASG.KM']))
        self.assertEqual(self.manifest()[0]['http'], '403')
        self.assertFalse((self.raw / 'wb' / 'IS.RRS.PASG.KM.json').exists())
        self.assertEqual(status[0][2], '取得できず')
        self.assertIn('403', status[0][3])

    def test_error_body_saved_aside_and_retried_next_time(self):
        plan = f.plan_requests(['SL.GDP.PCAP.EM.KD'])
        rows, status, failed = f.run(plan, self.raw, self.out, self.root, opener=self.opener({'SL.GDP.PCAP.EM.KD': (200, WB_ERR.encode())}), sleep=lambda s: None)
        self.assertEqual(failed, ['SL.GDP.PCAP.EM.KD'])
        self.assertFalse((self.raw / 'wb' / 'SL.GDP.PCAP.EM.KD.json').exists())
        self.assertTrue((self.raw / 'wb' / 'SL.GDP.PCAP.EM.KD.json.invalid').exists())

    def test_broken_oecd_body_is_set_aside_and_retried(self):
        # HTTP 200 の HTML は控えに残さないので、同じコマンドで取り直せる
        plan = f.plan_requests(['oecd'])
        _, _, failed = f.run(plan, self.raw, self.out, self.root, opener=lambda u, a: (200, b'<html>busy</html>'), sleep=lambda s: None)
        self.assertEqual(failed, ['TENURE-JPN'])
        self.assertFalse((self.raw / plan[0]['raw']).exists())
        rows, _, failed = f.run(plan, self.raw, self.out, self.root, opener=lambda u, a: (200, SDMX.encode()), sleep=lambda s: None)
        self.assertEqual((len(rows), failed), (3, []))

    def test_broken_cached_raw_is_set_aside_and_fetched_again(self):
        # 前の版が残した壊れた控えは、通信せずに使うのではなく退避して取り直す（世界銀行・OECD とも）
        for only, good in ((['oecd'], SDMX), (['IS.AIR.PSGR'], WB_OK)):
            plan = f.plan_requests(only)
            dest = self.raw / plan[0]['raw']
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b'<html>busy</html>')
            rows, _, failed = f.run(plan, self.raw, self.out, self.root, opener=lambda u, a: (200, good.encode()), sleep=lambda s: None)
            self.assertEqual(failed, [], only)
            self.assertTrue(rows, only)
            self.assertTrue(dest.with_name(dest.name + '.invalid').exists(), only)

    def test_pagination_fetches_page_two(self):
        def op(url, accept):
            self.calls.append(url)
            return 200, (WB_PAGE2 if url.endswith('&page=2') else WB_PAGED).encode()
        rows, _, failed = f.run(f.plan_requests(['IS.AIR.PSGR']), self.raw, self.out, self.root, opener=op, sleep=lambda s: None)
        self.assertEqual((failed, sorted(r['年'] for r in rows)), ([], ['2018', '2019']))
        self.assertEqual(len(self.calls), 2)

    def test_oecd_series_and_status_text(self):
        op = lambda url, accept: (200, SDMX.encode())
        rows, status, failed = f.run(f.plan_requests(['oecd']), self.raw, self.out, self.root, opener=op, sleep=lambda s: None)
        self.assertEqual((len(rows), failed), (3, []))
        self.assertIn('2系列', status[0][3])

    def test_rebuild_uses_saved_raw_only(self):
        plan = f.plan_requests(['IS.AIR.PSGR'])
        f.run(plan, self.raw, self.out, self.root, opener=self.opener({'IS.AIR.PSGR': (200, WB_OK.encode())}), sleep=lambda s: None)
        n = len(self.calls)
        rows, _, failed = f.run(plan, self.raw, self.out, self.root, rebuild=True, opener=lambda u, a: self.fail('通信した'), sleep=lambda s: None)
        self.assertEqual((len(rows), failed, len(self.calls)), (3, [], n))
        rows, _, failed = f.run(f.plan_requests(['IS.SHP.GOOD.TU']), self.raw, self.out, self.root, rebuild=True)
        self.assertEqual((rows, failed), ([], ['IS.SHP.GOOD.TU']))

    def test_write_outputs_columns(self):
        rows, status, _ = f.run(f.plan_requests(['IS.AIR.PSGR']), self.raw, self.out, self.root, opener=self.opener({'IS.AIR.PSGR': (200, WB_OK.encode())}), sleep=lambda s: None)
        f.write_outputs(self.out, rows, status)
        with (self.out / 'r3-series.csv').open(encoding='utf-8') as fh:
            self.assertEqual(next(csv.reader(fh)), ['国', '指標', '年', '値', '単位', '基準年', '出典URL', '観測状態'])
        with (self.out / 'status.csv').open(encoding='utf-8') as fh:
            self.assertEqual(next(csv.reader(fh)), f.STATUS_COLUMNS)

    def test_partial_run_keeps_other_series(self):
        # --only や一時的な取得失敗で、選ばなかった・取れなかった系列の前回の行を消さない
        both = f.plan_requests(['IS.AIR.PSGR', 'oecd'])
        op = lambda u, a: (200, (SDMX if 'sdmx' in u else WB_OK).encode())
        rows, status, failed = f.run(both, self.raw, self.out, self.root, opener=op, sleep=lambda s: None)
        f.write_outputs(self.out, *f.merge_outputs(self.out, both, rows, status, failed))
        before = (self.out / 'r3-series.csv').read_bytes()
        only = f.plan_requests(['IS.AIR.PSGR'])
        rows, status, failed = f.run(only, self.raw, self.out, self.root, rebuild=True)
        f.write_outputs(self.out, *f.merge_outputs(self.out, only, rows, status, failed))
        self.assertEqual((self.out / 'r3-series.csv').read_bytes(), before)
        oecd = f.plan_requests(['oecd'])
        (self.raw / oecd[0]['raw']).unlink()
        rows, status, failed = f.run(oecd, self.raw, self.out, self.root, rebuild=True)
        self.assertEqual(failed, ['TENURE-JPN'])
        rows, status = f.merge_outputs(self.out, oecd, rows, status, failed)
        self.assertEqual(len([r for r in rows if r['指標'].startswith('OECD:')]), 3)
        self.assertIn('前回の行を残した', {r[0]: r for r in status}['TENURE-JPN'][3])
        self.assertEqual([r[0] for r in status], ['IS.AIR.PSGR', 'TENURE-JPN'])

    def test_empty_response_keeps_previous_rows(self):
        # 値の無い応答（世界銀行の [metadata, null]）は取れなかった系列として扱い、前回の行を残す
        plan = f.plan_requests(['IS.AIR.PSGR'])
        rows, status, failed = f.run(plan, self.raw, self.out, self.root, opener=lambda u, a: (200, WB_OK.encode()), sleep=lambda s: None)
        f.write_outputs(self.out, *f.merge_outputs(self.out, plan, rows, status, failed))
        (self.raw / plan[0]['raw']).write_text(json.dumps([{'page': 1, 'pages': 1}, None]), encoding='utf-8')
        rows, status, failed = f.run(plan, self.raw, self.out, self.root, rebuild=True)
        self.assertEqual(failed, ['IS.AIR.PSGR'])
        self.assertEqual(status[0][2], '取得できず')
        rows, _ = f.merge_outputs(self.out, plan, rows, status, failed)
        self.assertEqual(len(rows), 3)

    def test_empty_response_is_not_saved(self):
        # 値の無い応答は控えに残さないので、上流が直れば同じコマンドで取り直せる
        plan = f.plan_requests(['IS.AIR.PSGR'])
        empty = json.dumps([{'page': 1, 'pages': 1}, None])
        _, _, failed = f.run(plan, self.raw, self.out, self.root, opener=lambda u, a: (200, empty.encode()), sleep=lambda s: None)
        self.assertEqual(failed, ['IS.AIR.PSGR'])
        self.assertFalse((self.raw / plan[0]['raw']).exists())
        rows, _, failed = f.run(plan, self.raw, self.out, self.root, opener=lambda u, a: (200, WB_OK.encode()), sleep=lambda s: None)
        self.assertEqual((len(rows), failed), (3, []))

    def test_observation_status_is_kept(self):
        self.assertEqual([r['観測状態'] for r in f.parse_sdmx_csv(SDMX, 'P', 'URL')], ['A', 'A', 'A'])
        text = json.dumps([{'page': 1, 'pages': 1}, [{'countryiso3code': 'JPN', 'date': '2019', 'value': 1, 'obs_status': 'E'}]])
        self.assertEqual(f.parse_wb_json(text, 'X', 'x', 'y', 'URL')[0][0]['観測状態'], 'E')

    def test_dry_run_does_not_write_or_connect(self):
        before = set(self.root.rglob('*'))
        rc = f.main(['--dry-run', '--raw', str(self.raw), '--out', str(self.out)])
        self.assertEqual(rc, 0)
        self.assertEqual(set(self.root.rglob('*')), before)

    def test_main_bad_only_exits_2(self):
        self.assertEqual(f.main(['--only', 'zzz', '--dry-run']), 2)


if __name__ == '__main__':
    unittest.main()
