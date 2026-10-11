import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from scripts import cloudflare_material_transfer as transfer


class MaterialTransferTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / '.local' / 'corpus'
        self.root.mkdir(parents=True)

    def record(self, name='one', payload=b'original', **changes):
        folder = self.root / name
        folder.mkdir()
        (folder / 'original.pdf').write_bytes(payload)
        record = dict(schema_version='external-material/v1', source_url='https://www.soumu.go.jp/report.pdf', observed_at='2026-10-01T10:00:00+09:00', saved_filename='original.pdf', bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(), media_type='application/pdf', title='private title', purpose='private purpose')
        record.update(changes)
        (folder / 'record.json').write_text(json.dumps(record), encoding='utf-8')
        return folder

    def test_duplicate_sources_preserved_without_private_metadata(self):
        self.record()
        self.record('two', source_url='https://www.soumu.go.jp/other.pdf')
        plan = transfer.build_plan(self.root)
        self.assertEqual(len(plan['objects']), 1)
        self.assertEqual(len(plan['records']), 2)
        self.assertEqual(len(plan['objects'][0]['occurrences']), 2)
        self.assertNotIn('private title', json.dumps(plan))
        self.assertTrue(plan['objects'][0]['key'].endswith('/original.pdf'))

    def test_local_mismatch_stops(self):
        self.record(bytes=900)
        with self.assertRaises(transfer.TransferError):
            transfer.build_plan(self.root)

    def test_path_escape_and_unapproved_hosts_stop(self):
        for changes in ({'saved_filename': '../original.pdf'}, {'source_url': 'https://evil.example/x'}, {'source_url': 'https://secret@www.soumu.go.jp/x'}):
            with self.subTest(changes=changes):
                self.record(str(len(list(self.root.iterdir()))), **changes)
                with self.assertRaises(transfer.TransferError):
                    transfer.build_plan(self.root)

    def test_dry_run_does_not_read_credentials_or_send(self):
        self.record()
        with patch.object(transfer, 'load_token', side_effect=AssertionError), patch.object(transfer, 'R2Client', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()) as output:
            result = transfer.main(['--corpus-root', str(self.root), '--account-id', 'a'*32, '--bucket', 'private-test'])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'planned')

    def test_existing_remote_is_hash_verified_without_put(self):
        self.record()
        client = MemoryClient(b'original')
        result = transfer.transfer_object(transfer.build_plan(self.root)['objects'][0], client)
        self.assertEqual(result['status'], 'verified_existing')
        self.assertEqual(client.puts, 0)

    def test_missing_remote_put_then_full_verify(self):
        self.record()
        client = MemoryClient(None)
        result = transfer.transfer_object(transfer.build_plan(self.root)['objects'][0], client)
        self.assertEqual(result['status'], 'uploaded_verified')
        self.assertEqual(client.puts, 1)

    def test_remote_conflict_never_overwrites(self):
        self.record()
        client = MemoryClient(b'conflict')
        with self.assertRaises(transfer.TransferError):
            transfer.transfer_object(transfer.build_plan(self.root)['objects'][0], client)
        self.assertEqual(client.puts, 0)

    def test_local_recheck_prevents_changed_file(self):
        folder = self.record()
        item = transfer.build_plan(self.root)['objects'][0]
        (folder / 'original.pdf').write_bytes(b'changed')
        client = MemoryClient(None)
        with self.assertRaises(transfer.TransferError):
            transfer.transfer_object(item, client)
        self.assertEqual(client.puts, 0)

    def test_retry_is_bounded_and_does_not_print_secrets(self):
        with patch.object(transfer, 'urlopen', side_effect=URLError('SECRET raw body')) as request, patch.object(transfer.time, 'sleep'):
            client = transfer.R2Client('a'*32, 'private-test', 'SECRET')
            with self.assertRaises(transfer.TransferError) as raised:
                client.get('materials/' + 'b'*64 + '/original.pdf')
        self.assertEqual(request.call_count, 3)
        self.assertNotIn('SECRET', str(raised.exception))

    def test_http_403_is_not_absence_or_retry(self):
        error = HTTPError('https://api.cloudflare.com', 403, 'SECRET', {}, io.BytesIO(b'SECRET'))
        with patch.object(transfer, 'urlopen', side_effect=error) as request:
            with self.assertRaises(transfer.TransferError):
                transfer.R2Client('a'*32, 'private-test', 'SECRET').get('materials/' + 'b'*64 + '/original.pdf')
        self.assertEqual(request.call_count, 1)

    def test_receipt_and_plan_output_require_private_local(self):
        self.record()
        with contextlib.redirect_stdout(io.StringIO()):
            result = transfer.main(['--corpus-root', str(self.root), '--account-id', 'a'*32, '--bucket', 'private-test', '--plan-output', str(Path(self.temp.name) / 'public.json')])
        self.assertNotEqual(result, 0)

    def test_resume_reverifies_remote_and_keeps_record_occurrences(self):
        self.record()
        self.record('two')
        plan = transfer.build_plan(self.root)
        output = self.root / 'receipts.json'
        client = MemoryClient(None)
        receipt = transfer.transfer_plan(plan, client, output, 'a'*32, 'private-test', 2)
        self.assertEqual(len(receipt['records']), 2)
        self.assertEqual(receipt['status'], 'verified')
        client.payload = b'corrupted'
        with self.assertRaises(transfer.TransferError):
            transfer.transfer_plan(plan, client, output, 'a'*32, 'private-test', 2)
        self.assertEqual(json.loads(output.read_text())['status'], 'failed')
        self.assertEqual(client.puts, 1)

    def test_receipt_target_mismatch_is_rejected(self):
        self.record()
        output = self.root / 'receipt.json'
        output.write_text(json.dumps(dict(schema=transfer.SCHEMA, accountId='b'*32, bucket='wrong')))
        with self.assertRaises(transfer.TransferError):
            transfer.transfer_plan(transfer.build_plan(self.root), MemoryClient(None), output, 'a'*32, 'private-test')

    def test_post_upload_missing_readback_is_failure(self):
        self.record()
        client = MemoryClient(None)
        with patch.object(client, 'get', return_value=None), self.assertRaises(transfer.TransferError):
            transfer.transfer_object(transfer.build_plan(self.root)['objects'][0], client)
        self.assertEqual(client.puts, 1)

    def test_generic_exception_is_redacted(self):
        self.record()
        with patch.object(transfer, 'build_plan', side_effect=ValueError('SECRET private path')), contextlib.redirect_stdout(io.StringIO()) as output:
            result = transfer.main(['--corpus-root', str(self.root), '--account-id', 'a'*32, '--bucket', 'private-test'])
        self.assertEqual(result, 1)
        self.assertNotIn('SECRET', output.getvalue())
        self.assertNotIn(str(self.root), output.getvalue())

    def test_redirect_is_refused(self):
        with self.assertRaises(transfer.TransferError):
            transfer.NoRedirect().redirect_request(None, None, 302, 'SECRET', {}, 'https://evil.example')

    def test_put_uses_raw_body_and_literal_key_slashes(self):
        body = io.BytesIO(b'{"success":true}')
        with patch.object(transfer, 'urlopen', return_value=body) as request:
            transfer.R2Client('a'*32, 'private-test', 'SECRET').put('materials/' + 'b'*64 + '/original.pdf', b'original', 'application/pdf')
        sent = request.call_args.args[0]
        self.assertEqual(sent.data, b'original')
        self.assertNotIn('%2F', sent.full_url)
        self.assertEqual(sent.method, 'PUT')

    def test_invalid_success_body_is_not_success(self):
        for payload in (b'{"success":false,"errors":["SECRET"]}', b'SECRET'):
            with patch.object(transfer, 'urlopen', return_value=io.BytesIO(payload)), self.assertRaises(transfer.TransferError) as raised:
                transfer.R2Client('a'*32, 'private-test', 'SECRET').put('key', b'x', 'application/pdf')
            self.assertNotIn('SECRET', str(raised.exception))

    def test_help_and_unknown_arguments(self):
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as raised:
            transfer.main(['--help'])
        self.assertEqual(raised.exception.code, 0)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            transfer.main(['--unknown'])
        self.assertNotEqual(raised.exception.code, 0)

    def test_plan_and_receipt_not_created_without_write(self):
        self.record()
        plan_path = self.root / 'plan.json'
        receipt_path = self.root / 'receipt.json'
        with contextlib.redirect_stdout(io.StringIO()):
            result = transfer.main(['--corpus-root', str(self.root), '--account-id', 'a'*32, '--bucket', 'private-test', '--plan-output', str(plan_path), '--receipt-output', str(receipt_path)])
        self.assertEqual(result, 0)
        self.assertFalse(plan_path.exists())
        self.assertFalse(receipt_path.exists())

    def test_write_plan_only_never_reads_token_or_sends(self):
        self.record()
        plan_path = self.root / 'plan.json'
        with patch.object(transfer, 'load_token', side_effect=AssertionError), patch.object(transfer, 'R2Client', side_effect=AssertionError), contextlib.redirect_stdout(io.StringIO()):
            result = transfer.main(['--corpus-root', str(self.root), '--account-id', 'a'*32, '--bucket', 'private-test', '--write', '--plan-only', '--plan-output', str(plan_path)])
        self.assertEqual(result, 0)
        self.assertTrue(plan_path.exists())

    def test_credential_query_keys_are_rejected(self):
        folder = self.record()
        path = folder / 'record.json'
        record = json.loads(path.read_text())
        for key in ('token', 'access_token', 'api_key', 'authorization', 'password', 'signature', 'X-Amz-Credential', 'x-amz-signature'):
            with self.subTest(key=key):
                record['source_url'] = f'https://www.soumu.go.jp/report.pdf?{key}=SECRET'
                path.write_text(json.dumps(record))
                with self.assertRaises(transfer.TransferError):
                    transfer.build_plan(self.root)


class MemoryClient:
    def __init__(self, payload):
        self.payload = payload
        self.puts = 0

    def get(self, key):
        return self.payload

    def put(self, key, payload, media_type):
        self.puts += 1
        self.payload = payload


if __name__ == '__main__':
    unittest.main()
