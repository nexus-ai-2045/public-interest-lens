import contextlib
import copy
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import cloudflare_material_index as index


class IndexTests(unittest.TestCase):
    def receipt(self):
        digest = 'a' * 64
        key = f'materials/{digest}/original.pdf'
        record = dict(recordId='b'*64, hash=digest, key=key, bytes=4, mediaType='application/pdf', sourceUrl='https://www.soumu.go.jp/report.pdf', observedAt='2026-10-11T10:00:00+09:00', sourcePath='SECRET/path', recordPath='SECRET/record.json', status='uploaded_verified')
        return dict(schema='cloudflare-material-transfer/v1', accountId='c'*32, bucket='private-test', status='verified', objects=[dict(hash=digest, key=key, bytes=4, status='uploaded_verified')], records=[record])

    def test_allowlist_packet_removes_private_information(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        self.assertNotIn('SECRET', json.dumps(packet))
        self.assertEqual(packet['objects'], [['a'*64, f'materials/{"a"*64}/original.pdf', 4, 'application/pdf']])
        self.assertEqual(len(packet['occurrences']), 1)

    def test_duplicate_occurrences_are_preserved(self):
        receipt = self.receipt()
        second = copy.deepcopy(receipt['records'][0])
        second['recordId'] = 'd'*64
        receipt['records'].append(second)
        packet = index.build_packet(receipt, 'c'*32, 'private-test')
        self.assertEqual(len(packet['objects']), 1)
        self.assertEqual(len(packet['occurrences']), 2)

    def test_incomplete_receipt_is_not_indexable(self):
        receipt = self.receipt()
        receipt['status'] = 'in_progress'
        with self.assertRaises(index.IndexError):
            index.build_packet(receipt, 'c'*32, 'private-test')

    def test_invalid_provenance_and_integrity_are_refused(self):
        for field, value in [('sourceUrl', 'https://evil.example/x'), ('sourceUrl', 'https://www.soumu.go.jp/x?token=SECRET'), ('bytes', 9), ('status', 'pending'), ('key', 'other'), ('observedAt', '2026-10-11')]:
            with self.subTest(field=field):
                receipt = self.receipt()
                receipt['records'][0][field] = value
                with self.assertRaises(index.IndexError):
                    index.build_packet(receipt, 'c'*32, 'private-test')

    def test_generated_batch_executes_with_foreign_keys(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('PRAGMA foreign_keys=ON')
        for query in packet['batch']:
            db.execute(query['sql'], query.get('params', []))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM material_objects').fetchone()[0], 1)
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_dryrun_never_writes_or_loads_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            output = root / 'packet.json'
            with patch.object(index, 'WranglerReadClient', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
                result = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--output', str(output)])
            self.assertEqual(result, 0)
            self.assertFalse(output.exists())

    def test_compare_detects_same_count_different_values(self):
        self.assertEqual(index.rows_hash([{'x': 1}, {'x': 2}]), index.rows_hash([{'x': 2}, {'x': 1}]))
        self.assertNotEqual(index.rows_hash([{'x': 1}]), index.rows_hash([{'x': 2}]))

    def test_sqlite_integral_real_matches_d1_integer(self):
        self.assertEqual(index.rows_hash([{'x': 1.0}]), index.rows_hash([{'x': 1}]))
        self.assertNotEqual(index.rows_hash([{'x': '1'}]), index.rows_hash([{'x': 1}]))
        self.assertNotEqual(index.rows_hash([{'x': None}]), index.rows_hash([{'x': 0}]))

    def test_identical_existing_index_is_skipped(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        result = index.pending_packet(packet, dict(objects=packet['objects'], occurrences=packet['occurrences']))
        self.assertEqual(len(result['batch']), 2)
        self.assertEqual(result['skippedObjects'], 1)
        self.assertEqual(result['skippedOccurrences'], 1)

    def test_partial_index_only_inserts_missing_occurrences(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        result = index.pending_packet(packet, dict(objects=packet['objects'], occurrences=[]))
        self.assertEqual(len(result['batch']), 3)
        self.assertTrue(result['batch'][-1]['sql'].startswith('INSERT INTO material_occurrences'))

    def test_existing_conflict_cannot_overwrite(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        existing = dict(objects=copy.deepcopy(packet['objects']), occurrences=[])
        existing['objects'][0][2] = 99
        with self.assertRaises(index.IndexError):
            index.pending_packet(packet, existing)

    def test_readonly_wrapper_rejects_write_sql(self):
        with self.assertRaises(index.IndexError):
            index.WranglerReadClient('c'*32, 'private-index').query_batch(['DELETE FROM material_objects'])

    def test_wrangler_read_results_success_and_zero_writes_required(self):
        for meta in ({'changed_db': True}, {'rows_written': 1}):
            result = SimpleNamespace(returncode=0, stdout=json.dumps([dict(success=True, results=[], meta=meta)]).encode())
            with patch.object(index.shutil, 'which', return_value='wrangler.cmd'), patch.object(index.subprocess, 'run', return_value=result), self.assertRaises(index.IndexError):
                index.WranglerReadClient('c'*32, 'private-index').query_batch(['PRAGMA foreign_key_check'])

    def test_in_progress_write_refuses_artifact(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            value = self.receipt()
            value['status'] = 'in_progress'
            receipt.write_text(json.dumps(value))
            output = root / 'packet.json'
            with contextlib.redirect_stdout(io.StringIO()) as stdout:
                result = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--write', '--output', str(output)])
            self.assertEqual(result, 1)
            self.assertEqual(json.loads(stdout.getvalue())['status'], 'in_progress')
            self.assertFalse(output.exists())

    def test_catalog_report_write_saves_only_summary(self):
        result = dict(schema=index.INDEX_SCHEMA, status='catalog_verified', tables=1, rows=1, checks=[dict(table='sample', rows=1, hash='a'*64)])
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / '.local' / 'report.json'
            with patch.object(index, 'WranglerReadClient'), patch.object(index, 'compare_catalog', return_value=result), contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--verify-catalog', 'public.sqlite3', '--account-id', 'c'*32, '--database-name', 'private-index', '--write', '--output', str(path)])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(path.read_text()), result)


if __name__ == '__main__':
    unittest.main()
