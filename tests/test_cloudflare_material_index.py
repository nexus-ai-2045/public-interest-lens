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

    def test_sql_export_quotes_text_and_preserves_integer_type_and_order(self):
        receipt = self.receipt()
        receipt['records'][0]['sourceUrl'] = "https://www.soumu.go.jp/report.pdf?name=O'Reilly"
        packet = index.build_packet(receipt, 'c'*32, 'private-test')
        sql = index.sql_text(packet)
        self.assertIn("O''Reilly", sql)
        self.assertNotIn('SECRET', sql)
        self.assertLess(sql.index('INSERT INTO material_objects'), sql.index('INSERT INTO material_occurrences'))
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.execute('PRAGMA foreign_keys=ON')
        db.executescript(sql)
        self.assertEqual([list(row) for row in db.execute('SELECT * FROM material_objects')], packet['objects'])
        self.assertEqual([list(row) for row in db.execute('SELECT * FROM material_occurrences')], packet['occurrences'])
        self.assertEqual(db.execute('SELECT typeof(bytes) FROM material_objects').fetchone()[0], 'integer')
        self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(), [])
        pending = index.pending_packet(packet, dict(objects=packet['objects'], occurrences=packet['occurrences']))
        db.executescript(index.sql_text(pending))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM material_occurrences').fetchone()[0], 1)

    def test_remote_index_read_projects_only_exact_columns(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        client = FakeReadClient(packet)
        existing, present = index.read_index(client)
        self.assertEqual(existing, dict(objects=packet['objects'], occurrences=packet['occurrences']))
        self.assertEqual(present, dict(objects=True, occurrences=True))
        self.assertEqual(index.verify_index(packet, client)['status'], 'index_verified')

    def test_missing_or_extra_remote_rows_cannot_verify(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        for mode in ('missing', 'extra', 'foreign_key'):
            with self.subTest(mode=mode), self.assertRaises(index.IndexError):
                index.verify_index(packet, FakeReadClient(packet, mode))

    def test_no_write_sql_output_is_not_created(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            sql_path = root / 'index.sql'
            with patch.object(index, 'WranglerReadClient', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--sql-output', str(sql_path)])
            self.assertEqual(code, 0)
            self.assertFalse(sql_path.exists())

    def test_write_sql_and_packet_uses_checked_existing_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            sql_path = root / 'index.sql'
            packet_path = root / 'packet.json'
            expected = index.build_packet(self.receipt(), 'c'*32, 'private-test')
            with patch.object(index, 'WranglerReadClient', return_value=FakeReadClient(expected)), contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--database-name', 'private-index', '--read-existing', '--sql-output', str(sql_path), '--output', str(packet_path), '--write'])
            self.assertEqual(code, 0)
            self.assertNotIn('INSERT INTO', sql_path.read_text())
            self.assertEqual(json.loads(packet_path.read_text())['skippedObjects'], 1)

    def test_verify_index_cli_writes_summary_not_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            output = root / 'verified.json'
            expected = index.build_packet(self.receipt(), 'c'*32, 'private-test')
            with patch.object(index, 'WranglerReadClient', return_value=FakeReadClient(expected)), contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--database-name', 'private-index', '--verify-index', '--output', str(output), '--write'])
            self.assertEqual(code, 0)
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'index_verified')
            self.assertNotIn('https:', json.dumps(result))
            self.assertNotIn('SECRET', json.dumps(result))

    def test_sql_export_rejects_unapproved_statements_and_literals(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        for value in (None, True, 4.0, 'bad\x00string'):
            with self.subTest(value=value):
                changed = copy.deepcopy(packet)
                changed['batch'][2]['params'][2] = value
                with self.assertRaises(index.IndexError):
                    index.sql_text(changed)
        packet['batch'].append(dict(sql='DROP TABLE material_objects'))
        with self.assertRaises(index.IndexError):
            index.sql_text(packet)

    def test_remote_unknown_columns_and_absent_tables_are_refused(self):
        packet = index.build_packet(self.receipt(), 'c'*32, 'private-test')
        for mode in ('unknown_column', 'absent'):
            with self.subTest(mode=mode), self.assertRaises(index.IndexError):
                index.verify_index(packet, FakeReadClient(packet, mode))

    def test_output_cannot_overwrite_complete_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            original = json.dumps(self.receipt())
            receipt.write_text(original)
            with contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--output', str(receipt), '--write'])
            self.assertEqual(code, 1)
            self.assertEqual(receipt.read_text(), original)

    def test_write_sql_requires_existing_index_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            output = root / 'index.sql'
            with contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--sql-output', str(output), '--write'])
            self.assertEqual(code, 1)
            self.assertFalse(output.exists())

    def test_remote_failure_is_redacted_and_leaves_no_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            output = root / 'index.sql'
            with patch.object(index, 'WranglerReadClient', side_effect=ValueError('SECRET HTTP body')), contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--database-name', 'private-index', '--read-existing', '--sql-output', str(output), '--write'])
            self.assertEqual(code, 1)
            self.assertNotIn('SECRET', stdout.getvalue())
            self.assertFalse(output.exists())

    def test_pending_output_cannot_destroy_input_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            output = root / 'packet.json'
            receipt = root / 'packet.json.pending'
            original = json.dumps(self.receipt()).encode()
            receipt.write_bytes(original)
            with contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--output', str(output), '--write'])
            self.assertEqual(code, 1)
            self.assertEqual(receipt.read_bytes(), original)
            self.assertFalse(output.exists())

    def test_pending_paths_cannot_overlap_other_outputs_or_existing_index(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            existing = root / 'existing.json.pending'
            original_existing = json.dumps(dict(objects=[], occurrences=[])).encode()
            existing.write_bytes(original_existing)
            output = root / 'packet.json'
            sql = root / 'packet.json.pending'
            output.write_bytes(b'old packet')
            sql.write_bytes(b'old SQL')
            with contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--output', str(output), '--sql-output', str(sql), '--existing-index', str(existing), '--write'])
            self.assertEqual(code, 1)
            self.assertEqual(output.read_bytes(), b'old packet')
            self.assertEqual(sql.read_bytes(), b'old SQL')
            with contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--output', str(root / 'existing.json'), '--existing-index', str(existing), '--write'])
            self.assertEqual(code, 1)
            self.assertEqual(existing.read_bytes(), original_existing)

    def test_pending_symlink_alias_preserves_receipt_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            root.mkdir()
            receipt = root / 'receipt.json'
            original = json.dumps(self.receipt()).encode()
            receipt.write_bytes(original)
            output = root / 'packet.json'
            try:
                output.with_suffix('.json.pending').symlink_to(receipt)
            except OSError as error:
                self.skipTest(type(error).__name__)
            with contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--output', str(output), '--write'])
            self.assertEqual(code, 1)
            self.assertEqual(receipt.read_bytes(), original)

    def test_safe_public_manifest_is_exact_allowlist_and_no_write_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            private = root / '.local'
            private.mkdir()
            receipt = private / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            output = root / 'data' / 'cloudflare' / 'materials.json'
            args = ['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--public-manifest-output', str(output)]
            with patch.object(index, 'ROOT', root, create=True), contextlib.redirect_stdout(io.StringIO()):
                code = index.main(args)
                self.assertEqual(code, 0)
                self.assertFalse(output.exists())
                code = index.main(args + ['--write'])
            self.assertEqual(code, 0)
            value = json.loads(output.read_text())
            self.assertEqual(set(value), {'schema', 'bucket', 'storageVerification', 'contentVerification', 'objectCount', 'occurrenceCount', 'totalBytes', 'objects', 'occurrences'})
            self.assertEqual(value['schema'], 'cloudflare-material-catalog/v1')
            self.assertEqual(value['storageVerification'], 'full_get_sha256')
            self.assertEqual(value['contentVerification'], 'unverified')
            self.assertEqual((value['objectCount'], value['occurrenceCount'], value['totalBytes']), (1, 1, 4))
            self.assertEqual(set(value['objects'][0]), {'hash', 'key', 'bytes', 'mediaType'})
            self.assertEqual(set(value['occurrences'][0]), {'id', 'hash', 'sourceUrl', 'observedAt'})
            self.assertNotIn('SECRET', json.dumps(value))
            self.assertNotIn('accountId', json.dumps(value))
            self.assertNotIn('batch', value)
            saved = output.read_bytes()
            with patch.object(index, 'ROOT', root), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(index.main(args), 0)
            self.assertEqual(output.read_bytes(), saved)

    def test_public_manifest_refuses_incomplete_receipt_and_path_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            receipt = root / 'receipt.json'
            value = self.receipt()
            value['status'] = 'in_progress'
            receipt.write_text(json.dumps(value))
            allowed = root / 'data' / 'cloudflare'
            output = allowed / 'materials.json'
            args = ['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--write']
            with patch.object(index, 'ROOT', root, create=True), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(index.main(args + ['--public-manifest-output', str(output)]), 1)
                self.assertFalse(output.exists())
                receipt.write_text(json.dumps(self.receipt()))
                for target in (root / 'outside.json', allowed / '..' / 'outside.json'):
                    self.assertEqual(index.main(args + ['--public-manifest-output', str(target)]), 1)
                    self.assertFalse(target.exists())

    def test_public_manifest_refuses_symlinked_allowed_directory(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            data = root / 'data'
            data.mkdir()
            receipt = root / 'receipt.json'
            receipt.write_text(json.dumps(self.receipt()))
            try:
                (data / 'cloudflare').symlink_to(Path(outside), target_is_directory=True)
            except OSError as error:
                self.skipTest(type(error).__name__)
            target = data / 'cloudflare' / 'materials.json'
            with patch.object(index, 'ROOT', root, create=True), contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--public-manifest-output', str(target), '--write'])
            self.assertEqual(code, 1)
            self.assertFalse((Path(outside) / 'materials.json').exists())

    def test_public_manifest_pending_path_cannot_overlap_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            folder = root / 'data' / 'cloudflare'
            folder.mkdir(parents=True)
            output = folder / 'materials.json'
            receipt = folder / 'materials.json.pending'
            original = json.dumps(self.receipt()).encode()
            receipt.write_bytes(original)
            with patch.object(index, 'ROOT', root, create=True), contextlib.redirect_stdout(io.StringIO()):
                code = index.main(['--receipt', str(receipt), '--account-id', 'c'*32, '--bucket', 'private-test', '--public-manifest-output', str(output), '--write'])
            self.assertEqual(code, 1)
            self.assertEqual(receipt.read_bytes(), original)

    def test_resolved_pending_alias_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / '.local'
            source = root / 'receipt.json'
            output = root / 'packet.json'
            temporary = output.with_suffix('.json.pending')
            resolve = Path.resolve

            def mapped(path, *args, **kwargs):
                return resolve(source) if path == temporary else resolve(path, *args, **kwargs)

            with patch.object(Path, 'resolve', autospec=True, side_effect=mapped), self.assertRaises(index.IndexError):
                index.check_output_collisions([output], [source])

    def test_public_guard_rejects_parent_symlink_and_resolved_allowed_escape(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            allowed = root / 'data' / 'cloudflare'
            target = allowed / 'materials.json'
            resolve = Path.resolve

            def mapped(path, *args, **kwargs):
                return Path(outside) if path == allowed else resolve(path, *args, **kwargs)

            with patch.object(index, 'ROOT', root):
                for parent in (allowed, root / 'data'):
                    with patch.object(Path, 'is_symlink', autospec=True, side_effect=lambda path: path == parent), self.assertRaises(index.IndexError):
                        index.public_output(target)
                with patch.object(Path, 'resolve', autospec=True, side_effect=mapped), self.assertRaises(index.IndexError):
                    index.public_output(target)


class FakeReadClient:
    def __init__(self, packet, mode=None):
        self.packet = packet
        self.mode = mode

    def query_batch(self, statements):
        self.statements = statements

    def query(self, sql):
        if sql == 'SELECT * FROM "sqlite_master"':
            return [] if self.mode == 'absent' else [dict(type='table', name=name) for name in ('material_objects', 'material_occurrences')]
        if sql == 'PRAGMA foreign_key_check':
            return [dict(table='material_occurrences')] if self.mode == 'foreign_key' else []
        if sql == 'SELECT * FROM "material_objects"':
            values = [dict(zip(('hash', 'r2_key', 'bytes', 'media_type'), row)) for row in self.packet['objects']]
            if self.mode == 'extra':
                values.append(dict(hash='f'*64, r2_key='other', bytes=8, media_type='text/plain'))
            if self.mode == 'unknown_column':
                values[0]['unexpected'] = 'private'
            return values
        if sql == 'SELECT * FROM "material_occurrences"':
            return [] if self.mode == 'missing' else [dict(zip(('occurrence_id', 'hash', 'source_url', 'observed_at'), row)) for row in self.packet['occurrences']]
        raise AssertionError(sql)


if __name__ == '__main__':
    unittest.main()
