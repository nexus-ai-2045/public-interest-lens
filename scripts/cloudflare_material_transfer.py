from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import tomllib
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    from scripts.register_external_material import sha256_file, validate_source_url
except ModuleNotFoundError:
    from register_external_material import sha256_file, validate_source_url


SCHEMA = 'cloudflare-material-transfer/v1'
OFFICIAL_HOSTS = frozenset({
    'kokkai.ndl.go.jp', 'laws.e-gov.go.jp', 'www.sangiin.go.jp',
    'www.shugiin.go.jp', 'hourei.ndl.go.jp', 'www.soumu.go.jp',
    'www.e-stat.go.jp', 'www.mof.go.jp', 'www.kanpo.go.jp',
    'www.jbaudit.go.jp', 'rssystem.go.jp',
})
MAX_OBJECT_BYTES = 300_000_000
DEFAULT_CREDENTIAL_FILE = Path.home() / '.wrangler/config/default.toml'


class TransferError(Exception):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise TransferError('redirect_refused')


urlopen = build_opener(NoRedirect()).open


def check_target(account_id, bucket):
    if not re.fullmatch(r'[a-f0-9]{32}', account_id):
        raise TransferError('invalid_account')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket):
        raise TransferError('invalid_bucket')


def private_output(path):
    resolved = path.resolve()
    if '.local' not in resolved.parts:
        raise TransferError('output_not_private_local')
    return resolved


def write_json(path, data):
    target = private_output(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = pending_path(target)
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(target)


def pending_path(path):
    return path.with_suffix(path.suffix + '.pending')


def check_output_paths(corpus_root, plan, outputs):
    root = corpus_root.resolve(strict=True)
    inputs = {Path(row[key]).resolve() for row in plan['records'] for key in ('recordPath', 'sourcePath') if row.get(key)}
    seen = set()
    for output in outputs:
        target = private_output(output)
        for path in (target, pending_path(target).resolve()):
            if path in seen or path in inputs:
                raise TransferError('output_path_conflict')
            if path.is_relative_to(root) and (path.name == 'record.json' or path.name.startswith('original.')):
                raise TransferError('output_path_conflict')
            seen.add(path)


def build_plan(corpus_root):
    root = corpus_root.resolve(strict=True)
    objects = {}
    records = []
    for record_path in sorted(root.rglob('record.json')):
        if record_path.is_symlink() or not record_path.resolve().is_relative_to(root):
            raise TransferError('record_path_escape')
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if record.get('schema_version') != 'external-material/v1':
            raise TransferError('invalid_record_schema')
        source_url = record['source_url']
        validate_source_url(source_url)
        parsed = urlparse(source_url)
        if parsed.hostname not in OFFICIAL_HOSTS or parsed.username or parsed.password:
            raise TransferError('source_not_approved')
        if parsed.port not in {None, 80, 443}:
            raise TransferError('source_port_not_approved')
        query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        secret_keys = {'token', 'access_token', 'api_key', 'authorization', 'password', 'signature'}
        if query_keys & secret_keys or any(key.startswith('x-amz') for key in query_keys):
            raise TransferError('source_credentials_refused')
        observed = datetime.fromisoformat(record['observed_at'])
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise TransferError('observed_at_timezone_missing')
        filename = record['saved_filename']
        if not re.fullmatch(r'original(?:\.[A-Za-z0-9]{1,12})?', filename):
            raise TransferError('invalid_original_filename')
        source = record_path.parent / filename
        if source.is_symlink() or not source.resolve(strict=True).is_relative_to(root) or not source.is_file():
            raise TransferError('original_path_escape')
        size = source.stat().st_size
        digest = sha256_file(source)
        if type(record['bytes']) is not int or size != record['bytes'] or digest != record['sha256']:
            raise TransferError('local_integrity_mismatch')
        if size > MAX_OBJECT_BYTES:
            raise TransferError('object_too_large')
        media_type = record['media_type']
        if not isinstance(media_type, str) or not re.fullmatch(r'[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+', media_type):
            raise TransferError('invalid_media_type')
        safe = dict(sourceUrl=source_url, observedAt=record['observed_at'], hash=digest, bytes=size, mediaType=media_type)
        record_id = hashlib.sha256(record_path.relative_to(root).as_posix().encode()).hexdigest()
        entry = dict(recordId=record_id, sourcePath=str(source.resolve()), recordPath=str(record_path.resolve()), **safe)
        records.append(entry)
        if digest not in objects:
            suffix = source.suffix.lower() or '.bin'
            objects[digest] = dict(hash=digest, bytes=size, mediaType=media_type, sourcePath=str(source.resolve()), key=f'materials/{digest}/original{suffix}', occurrences=[])
        item = objects[digest]
        if item['bytes'] != size:
            raise TransferError('duplicate_integrity_mismatch')
        if item['mediaType'] != media_type:
            raise TransferError('duplicate_media_type_conflict')
        if safe not in item['occurrences']:
            item['occurrences'].append(safe)
        entry['key'] = item['key']
    if not records:
        raise TransferError('empty_corpus')
    originals = list(root.rglob('original.*'))
    if len(originals) != len(records):
        raise TransferError('unregistered_originals')
    return dict(schema=SCHEMA, records=records, objects=list(objects.values()))


def load_token(path):
    with path.open('rb') as handle:
        return validated_token(tomllib.load(handle))


def validated_token(data):
    token = data.get('oauth_token')
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise TransferError('credential_unavailable')
    return token


def utc_now():
    return datetime.now(timezone.utc)


class OAuthTokenProvider:
    def __init__(self, path, account_id):
        if not re.fullmatch(r'[a-f0-9]{32}', account_id):
            raise TransferError('invalid_account')
        self.path = path.resolve()
        self.account_id = account_id
        self.lock = Lock()
        self.refresh_failed = False

    def credential(self):
        try:
            with self.path.open('rb') as handle:
                data = tomllib.load(handle)
            token = validated_token(data)
            expiry = datetime.fromisoformat(data['expiration_time'])
            if expiry.tzinfo is None or expiry.utcoffset() is None:
                raise ValueError
            return token, expiry, data
        except Exception:
            raise TransferError('credential_invalid') from None

    def get_token(self):
        with self.lock:
            if self.refresh_failed:
                raise TransferError('credential_refresh_failed')
            token, expiry, data = self.credential()
            if expiry > utc_now():
                return token
            if self.path != DEFAULT_CREDENTIAL_FILE.resolve():
                raise TransferError('custom_credential_expired')
            self.refresh_failed = True
            executable = shutil.which('wrangler.cmd') or shutil.which('wrangler')
            if not executable or not isinstance(data.get('refresh_token'), str) or not data['refresh_token']:
                raise TransferError('credential_refresh_unavailable')
            try:
                env = dict(os.environ, CI='true', WRANGLER_SEND_METRICS='false', CLOUDFLARE_ACCOUNT_ID=self.account_id)
                result = subprocess.run([executable, 'whoami', '--json'], capture_output=True, stdin=subprocess.DEVNULL, timeout=120, env=env)
                identity = json.loads(result.stdout)
                if result.returncode or identity.get('loggedIn') is not True or self.account_id not in {row['id'] for row in identity.get('accounts', [])}:
                    raise ValueError
                token, expiry, updated = self.credential()
                if expiry <= utc_now() or updated.get('scopes') != data.get('scopes'):
                    raise ValueError
            except Exception:
                raise TransferError('credential_refresh_failed') from None
            self.refresh_failed = False
            return token


class R2Client:
    def __init__(self, account_id, bucket, token, token_provider=None):
        check_target(account_id, bucket)
        self.base = f'https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket}/objects/'
        self.token = token
        self.token_provider = token_provider

    def request(self, method, key, payload=None, media_type=None):
        url = self.base + quote(key, safe='/')
        boundary_refreshed = False
        for attempt in range(3):
            token = self.token_provider.get_token() if self.token_provider else self.token
            headers = {'Authorization': 'Bearer ' + token}
            if media_type:
                headers['Content-Type'] = media_type
            request = Request(url, data=payload, headers=headers, method=method)
            try:
                with urlopen(request, timeout=120) as response:
                    body = response.read(MAX_OBJECT_BYTES + 1)
                    if len(body) > MAX_OBJECT_BYTES:
                        raise TransferError('response_too_large')
                    return body
            except HTTPError as error:
                code = error.code
                error.close()
                if method == 'GET' and code == 404:
                    return None
                if code == 401 and self.token_provider and not boundary_refreshed:
                    current_token = self.token_provider.get_token()
                    if current_token != token:
                        boundary_refreshed = True
                        continue
                if code not in {429, 500, 502, 503, 504}:
                    raise TransferError(f'http_{code}') from None
            except (URLError, TimeoutError, OSError):
                pass
            if attempt < 2:
                time.sleep(2 ** attempt)
        raise TransferError('network_retry_exhausted')

    def get(self, key):
        return self.request('GET', key)

    def put(self, key, payload, media_type):
        body = self.request('PUT', key, payload, media_type)
        try:
            response = json.loads(body)
        except (ValueError, TypeError):
            raise TransferError('invalid_upload_receipt') from None
        if response.get('success') is not True:
            raise TransferError('upload_not_successful')


def verify_payload(payload, item):
    if payload is None or len(payload) != item['bytes'] or hashlib.sha256(payload).hexdigest() != item['hash']:
        raise TransferError('remote_integrity_mismatch')


def transfer_object(item, client):
    payload = Path(item['sourcePath']).read_bytes()
    if len(payload) != item['bytes'] or hashlib.sha256(payload).hexdigest() != item['hash']:
        raise TransferError('local_integrity_changed')
    existing = client.get(item['key'])
    if existing is not None:
        verify_payload(existing, item)
        status = 'verified_existing'
    else:
        client.put(item['key'], payload, item['mediaType'])
        verify_payload(client.get(item['key']), item)
        status = 'uploaded_verified'
    return dict(hash=item['hash'], bytes=item['bytes'], key=item['key'], status=status)


def transfer_plan(plan, client, receipt_output, account_id, bucket, workers=2):
    private_output(receipt_output)
    results = {}
    if receipt_output.exists():
        old = json.loads(receipt_output.read_text(encoding='utf-8'))
        if old.get('schema') != SCHEMA or old.get('accountId') != account_id or old.get('bucket') != bucket:
            raise TransferError('receipt_target_mismatch')
    receipt = dict(schema=SCHEMA, accountId=account_id, bucket=bucket, status='in_progress', objects=[], records=[])
    write_json(receipt_output, receipt)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        items = iter(plan['objects'])
        pending = {}
        for _ in range(workers):
            item = next(items, None)
            if item is not None:
                pending[executor.submit(transfer_object, item, client)] = item
        while pending:
            completed, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in completed:
                item = pending.pop(future)
                try:
                    result = future.result()
                except Exception:
                    for other in pending:
                        other.cancel()
                    receipt['status'] = 'failed'
                    receipt['errorCode'] = 'transfer_failed'
                    write_json(receipt_output, receipt)
                    raise
                results[item['hash']] = result
                receipt['objects'] = list(results.values())
                receipt['records'] = [dict(row, status=results[row['hash']]['status']) for row in plan['records'] if row['hash'] in results]
                write_json(receipt_output, receipt)
                if len(results) % 20 == 0:
                    print(json.dumps(dict(schema=SCHEMA, status='in_progress', verifiedObjects=len(results)), ensure_ascii=False), flush=True)
            for _ in completed:
                item = next(items, None)
                if item is not None:
                    pending[executor.submit(transfer_object, item, client)] = item
    receipt['status'] = 'verified'
    write_json(receipt_output, receipt)
    return receipt


def build_parser():
    parser = argparse.ArgumentParser(description='非公開R2への原資料移行計画とハッシュ検証。既定は読取りのみ。内容の正確性は検証しません。')
    parser.add_argument('--corpus-root', type=Path, required=True)
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--bucket', required=True)
    parser.add_argument('--credential-file', type=Path, default=DEFAULT_CREDENTIAL_FILE)
    parser.add_argument('--plan-output', type=Path, help='--write指定時のみ非公開.local配下へ計画保存')
    parser.add_argument('--receipt-output', type=Path)
    parser.add_argument('--workers', type=int, choices=[1, 2], default=2)
    parser.add_argument('--write', action='store_true', help='原資料のみ送信。record.jsonは送信しない。全文GETで照合しreceiptを保存')
    parser.add_argument('--plan-only', action='store_true', help='--writeと併用時も計画保存のみ。認証情報を読まず送信しない')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        check_target(args.account_id, args.bucket)
        if args.plan_output:
            private_output(args.plan_output)
        if args.receipt_output:
            private_output(args.receipt_output)
        if args.write and args.plan_only and not args.plan_output:
            raise TransferError('plan_output_required')
        if args.write and not args.plan_only and not args.receipt_output:
            raise TransferError('receipt_required')
        plan = build_plan(args.corpus_root)
        check_output_paths(args.corpus_root, plan, [path for path in (args.plan_output, args.receipt_output) if path])
        if args.write and args.plan_output:
            write_json(args.plan_output, plan)
        if args.write and not args.plan_only:
            client = R2Client(args.account_id, args.bucket, None, OAuthTokenProvider(args.credential_file, args.account_id))
            transfer_plan(plan, client, args.receipt_output, args.account_id, args.bucket, args.workers)
        summary = dict(schema=SCHEMA, status='verified' if args.write and not args.plan_only else 'planned', records=len(plan['records']), uniqueObjects=len(plan['objects']), duplicateRecords=len(plan['records'])-len(plan['objects']), uploadBytes=sum(row['bytes'] for row in plan['objects']))
        print(json.dumps(summary, ensure_ascii=False), flush=True)
        return 0
    except TransferError as error:
        code = str(error)
        if not re.fullmatch('[a-z0-9_]+', code):
            code = 'transfer_error'
        print(json.dumps(dict(schema=SCHEMA, status='failed', errorCode=code)), flush=True)
        return 1
    except Exception:
        print(json.dumps(dict(schema=SCHEMA, status='failed', errorCode='invalid_input_or_io')), flush=True)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
