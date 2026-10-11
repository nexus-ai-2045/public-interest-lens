from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

try:
    from scripts.cloudflare_material_transfer import OFFICIAL_HOSTS, SCHEMA, check_target, private_output, write_json
except ModuleNotFoundError:
    from cloudflare_material_transfer import OFFICIAL_HOSTS, SCHEMA, check_target, private_output, write_json


INDEX_SCHEMA = 'cloudflare-material-index/v1'
VERIFIED = {'verified_existing', 'uploaded_verified'}
DDL = [
    'CREATE TABLE IF NOT EXISTS material_objects (hash TEXT PRIMARY KEY CHECK(length(hash)=64), r2_key TEXT NOT NULL UNIQUE, bytes INTEGER NOT NULL CHECK(bytes>=0), media_type TEXT NOT NULL)',
    'CREATE TABLE IF NOT EXISTS material_occurrences (occurrence_id TEXT PRIMARY KEY CHECK(length(occurrence_id)=64), hash TEXT NOT NULL REFERENCES material_objects(hash), source_url TEXT NOT NULL, observed_at TEXT NOT NULL)',
]


class IndexError(Exception):
    pass


def hash_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'[a-f0-9]{64}', value):
        raise IndexError('invalid_hash')
    return value


def build_packet(receipt, account_id, bucket):
    check_target(account_id, bucket)
    if receipt.get('schema') != SCHEMA or receipt.get('accountId') != account_id or receipt.get('bucket') != bucket:
        raise IndexError('receipt_target_mismatch')
    if receipt.get('status') != 'verified':
        raise IndexError('in_progress')
    objects = {}
    for item in receipt['objects']:
        digest = hash_value(item['hash'])
        if digest in objects or item['status'] not in VERIFIED:
            raise IndexError('invalid_object_receipt')
        if not re.fullmatch(rf'materials/{digest}/original\.[a-z0-9]{{1,12}}', item['key']):
            raise IndexError('invalid_object_key')
        if type(item['bytes']) is not int or item['bytes'] < 0:
            raise IndexError('invalid_bytes')
        objects[digest] = [digest, item['key'], item['bytes'], None]
    occurrences = {}
    for record in receipt['records']:
        occurrence_id = hash_value(record['recordId'])
        digest = hash_value(record['hash'])
        if occurrence_id in occurrences or digest not in objects or record['status'] not in VERIFIED:
            raise IndexError('invalid_occurrence_receipt')
        item = objects[digest]
        if record['key'] != item[1] or record['bytes'] != item[2]:
            raise IndexError('occurrence_integrity_mismatch')
        media_type = record['mediaType']
        if not isinstance(media_type, str) or not re.fullmatch(r'[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+', media_type):
            raise IndexError('invalid_media_type')
        if item[3] is not None and item[3] != media_type:
            raise IndexError('conflicting_media_type')
        item[3] = media_type
        url = record['sourceUrl']
        parsed = urlparse(url)
        if parsed.scheme not in {'http', 'https'} or parsed.hostname not in OFFICIAL_HOSTS or parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            raise IndexError('source_not_approved')
        query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        if query_keys & {'token', 'access_token', 'api_key', 'authorization', 'password', 'signature'} or any(key.startswith('x-amz') for key in query_keys):
            raise IndexError('source_credentials_refused')
        observed = datetime.fromisoformat(record['observedAt'])
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise IndexError('observed_at_timezone_missing')
        occurrences[occurrence_id] = [occurrence_id, digest, url, record['observedAt']]
    if not objects or any(row[3] is None for row in objects.values()):
        raise IndexError('missing_occurrences')
    object_rows = sorted(objects.values())
    occurrence_rows = sorted(occurrences.values())
    batch = [{'sql': sql} for sql in DDL]
    batch.extend(dict(sql='INSERT INTO material_objects (hash,r2_key,bytes,media_type) VALUES (?,?,?,?)', params=row) for row in object_rows)
    batch.extend(dict(sql='INSERT INTO material_occurrences (occurrence_id,hash,source_url,observed_at) VALUES (?,?,?,?)', params=row) for row in occurrence_rows)
    return dict(schema=INDEX_SCHEMA, status='verified_receipt', objects=object_rows, occurrences=occurrence_rows, batch=batch)


def pending_packet(packet, existing):
    batch = [{'sql': sql} for sql in DDL]
    skipped = {}
    for group, table, columns in [('objects', 'material_objects', 'hash,r2_key,bytes,media_type'), ('occurrences', 'material_occurrences', 'occurrence_id,hash,source_url,observed_at')]:
        expected = {row[0]: row for row in packet[group]}
        previous = {}
        for row in existing[group]:
            if not isinstance(row, list) or len(row) != 4 or row[0] in previous or row[0] not in expected or row != expected[row[0]]:
                raise IndexError('existing_index_conflict')
            previous[row[0]] = row
        missing = [row for row in packet[group] if row[0] not in previous]
        batch.extend(dict(sql=f'INSERT INTO {table} ({columns}) VALUES (?,?,?,?)', params=row) for row in missing)
        skipped[group] = len(previous)
    return dict(packet, batch=batch, skippedObjects=skipped['objects'], skippedOccurrences=skipped['occurrences'])


def normalize_numbers(value):
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: normalize_numbers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_numbers(item) for item in value]
    return value


def rows_hash(rows):
    canonical = sorted(json.dumps(normalize_numbers(row), ensure_ascii=False, sort_keys=True, separators=(',', ':')) for row in rows)
    return hashlib.sha256(json.dumps(canonical, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


class WranglerReadClient:
    def __init__(self, account_id, database_name):
        if not re.fullmatch(r'[a-f0-9]{32}', account_id) or not re.fullmatch(r'[a-z0-9-]{3,63}', database_name):
            raise IndexError('invalid_database_target')
        self.account_id = account_id
        self.database_name = database_name
        self.results = {}

    def query_batch(self, statements):
        if any(not (re.fullmatch(r'SELECT \* FROM "[a-z_]+"', sql) or sql == 'PRAGMA foreign_key_check') for sql in statements):
            raise IndexError('read_query_not_allowed')
        executable = shutil.which('wrangler.cmd') or shutil.which('wrangler')
        if not executable:
            raise IndexError('wrangler_unavailable')
        env = dict(os.environ, CLOUDFLARE_ACCOUNT_ID=self.account_id, WRANGLER_SEND_METRICS='false')
        completed = subprocess.run([executable, 'd1', 'execute', self.database_name, '--remote', '--command', ';'.join(statements)+';', '--json'], capture_output=True, timeout=120, env=env)
        if completed.returncode:
            raise IndexError('wrangler_query_failed')
        values = json.loads(completed.stdout.decode('utf-8'))
        if not isinstance(values, list) or len(values) != len(statements):
            raise IndexError('query_results_missing')
        for sql, result in zip(statements, values, strict=True):
            if result.get('success') is not True or result.get('meta', {}).get('changed_db') is True or result.get('meta', {}).get('rows_written', 0) != 0:
                raise IndexError('query_not_readonly')
            if not isinstance(result.get('results'), list):
                raise IndexError('query_results_missing')
            self.results[sql] = result['results']

    def query(self, sql):
        return self.results[sql]


def compare_catalog(path, client):
    uri = path.resolve(strict=True).as_uri() + '?mode=ro'
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if any(not re.fullmatch('[a-z_]+', table) for table in tables):
            raise IndexError('invalid_catalog_table')
        client.query_batch([f'SELECT * FROM "{table}"' for table in tables] + ['PRAGMA foreign_key_check'])
        checks = []
        for table in tables:
            if not re.fullmatch('[a-z_]+', table):
                raise IndexError('invalid_catalog_table')
            sql = f'SELECT * FROM "{table}"'
            local = [dict(row) for row in connection.execute(sql)]
            remote = client.query(sql)
            if rows_hash(local) != rows_hash(remote):
                raise IndexError('catalog_row_mismatch_' + table)
            checks.append(dict(table=table, rows=len(local), hash=rows_hash(local)))
        if connection.execute('PRAGMA foreign_key_check').fetchall() or client.query('PRAGMA foreign_key_check'):
            raise IndexError('foreign_key_mismatch')
        return dict(schema=INDEX_SCHEMA, status='catalog_verified', tables=len(checks), rows=sum(row['rows'] for row in checks), checks=checks)
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='検証済みR2受領記録から非公開D1材料索引packetを生成。D1書込み機能はありません。')
    parser.add_argument('--account-id', required=True)
    parser.add_argument('--bucket')
    parser.add_argument('--receipt', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--existing-index', type=Path, help='objects/occurrences配列形式の読取済み全索引。全値一致は除外し矛盾は停止')
    parser.add_argument('--write', action='store_true', help='非公開.localへのpacketまたは検証結果保存だけを許可')
    parser.add_argument('--verify-catalog', type=Path, help='公開SQLite全行をD1読取り結果と照合')
    parser.add_argument('--database-name')
    args = parser.parse_args(argv)
    try:
        if args.verify_catalog:
            if not args.database_name or args.receipt or (args.write and not args.output):
                raise IndexError('invalid_catalog_mode')
            client = WranglerReadClient(args.account_id, args.database_name)
            result = compare_catalog(args.verify_catalog, client)
            if args.write:
                write_json(args.output, result)
        else:
            if not args.receipt or not args.bucket:
                raise IndexError('receipt_and_bucket_required')
            receipt = json.loads(args.receipt.read_text(encoding='utf-8'))
            if receipt.get('status') != 'verified':
                print(json.dumps(dict(schema=INDEX_SCHEMA, status='in_progress', indexedObjects=0)))
                return 1
            packet = build_packet(receipt, args.account_id, args.bucket)
            if args.existing_index:
                packet = pending_packet(packet, json.loads(args.existing_index.read_text(encoding='utf-8')))
            if args.output:
                private_output(args.output)
            if args.write:
                if not args.output:
                    raise IndexError('output_required')
                write_json(args.output, packet)
            result = dict(schema=INDEX_SCHEMA, status='packet_saved' if args.write else 'planned', objects=len(packet['objects']), occurrences=len(packet['occurrences']), batchQueries=len(packet['batch']), packetHash=rows_hash(packet['objects']+packet['occurrences']))
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except IndexError as error:
        code = str(error) if re.fullmatch('[a-z0-9_]+', str(error)) else 'index_error'
    except Exception:
        code = 'invalid_input_or_io'
    print(json.dumps(dict(schema=INDEX_SCHEMA, status='failed', errorCode=code)), flush=True)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
