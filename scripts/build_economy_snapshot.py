from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path


INDICATORS = {'NY.GDP.MKTP.KN': ('real_gdp', '実質GDP', '円・一定価格'), 'NY.GDP.MKTP.CN': ('nominal_gdp', '名目GDP', '円・当年価格'), 'SP.POP.TOTL': ('population', '人口', '人')}


def _load_indicator(input_root: Path, indicator: str, *, registered: bool) -> tuple[bytes, str | None]:
    if not registered:
        return (input_root / f'{indicator}.json').read_bytes(), None
    try:
        from scripts.register_external_material import normalize_observed_at
    except ImportError:
        from register_external_material import normalize_observed_at
    root = input_root.resolve()
    matches = []
    for record_path in root.rglob('record.json'):
        if not record_path.resolve().is_relative_to(root):
            raise ValueError('登録記録が入力先の外です')
        record = json.loads(record_path.read_text(encoding='utf-8'))
        if not isinstance(record, dict):
            raise ValueError('登録記録の形式が不正です')
        url = record.get('source_url')
        path = url.split('?', 1)[0] if isinstance(url, str) else ''
        if f'/indicator/{indicator}' not in path:
            continue
        name = record.get('saved_filename')
        if not isinstance(name, str) or not name or name != Path(name).name:
            raise ValueError('登録原本のファイル名が不正です')
        saved = (record_path.parent / name).resolve()
        if not saved.is_relative_to(record_path.parent.resolve()) or not saved.is_file():
            raise ValueError('登録原本が記録の外です')
        payload = saved.read_bytes()
        if hashlib.sha256(payload).hexdigest() != record.get('sha256'):
            raise ValueError('登録原本のハッシュが一致しません')
        observed, _ = normalize_observed_at(record.get('observed_at'))
        matches.append((observed, payload))
    if len(matches) != 1:
        raise ValueError('登録済みの統計原本が一つに定まりません')
    return matches[0][1], matches[0][0]


def build_snapshot(input_root: Path, *, registered: bool = False) -> dict:
    series = []
    observed_times = []
    for indicator, (identifier, label, unit) in INDICATORS.items():
        raw, observed = _load_indicator(input_root, indicator, registered=registered)
        if observed:
            observed_times.append(datetime.fromisoformat(observed))
        payload = json.loads(raw)
        if not isinstance(payload, list) or len(payload) != 2 or payload[0].get('pages') != 1 or not isinstance(payload[1], list) or payload[0].get('total') != len(payload[1]):
            raise ValueError('提供元のページまたは件数が不一致です')
        seen = set()
        points = []
        for row in payload[1]:
            year, value = row.get('date'), row.get('value')
            if row.get('countryiso3code') != 'JPN' or row.get('indicator', {}).get('id') != indicator or not isinstance(year, str) or not year.isdigit() or year in seen:
                raise ValueError('国・指標・年の参照が不正です')
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0):
                raise ValueError('統計値が不正です')
            seen.add(year)
            points.append({'year': int(year), 'value': value})
        item = {'id': identifier, 'label': label, 'unit': unit, 'basis': '提供元が公表する単一系列。別基準の国内系列とは接続していません。', 'sourceUrl': f'https://api.worldbank.org/v2/country/JPN/indicator/{indicator}?format=json&date=1980:2025&per_page=100', 'originalSha256': hashlib.sha256(raw).hexdigest(), 'sourceUpdatedAt': payload[0].get('lastupdated'), 'points': sorted(points, key=lambda point: point['year'])}
        if observed:
            item['sourceObservedAt'] = observed
        series.append(item)
    population = {point['year']: point['value'] for point in series[2]['points']}
    real = series[0]
    per_capita = {**real, 'id': 'real_gdp_per_capita', 'label': '一人当たり実質GDP', 'unit': '円／人・一定価格', 'derivedFrom': ['real_gdp', 'population'], 'points': [{**point, 'value': point['value'] / population[point['year']] if point['value'] is not None and population.get(point['year']) else None} for point in real['points']]}
    per_capita.pop('sourceObservedAt', None)
    series.append(per_capita)
    observed_at = max(observed_times).isoformat(timespec='seconds') if observed_times else datetime.now(timezone.utc).isoformat()
    return {'schemaVersion': 'economic-series/v1', 'observedAt': observed_at, 'provider': 'World Bank WDI', 'country': 'JPN', 'series': series, 'unavailable': ['労働生産性', '設備投資', '研究開発投資'], 'causes': [], 'note': '統計の推移だけで、特定の政策や人物による影響とは認定しません。'}


def snapshot_digest(snapshot: dict) -> str:
    stable = {key: value for key, value in snapshot.items() if key not in {'observedAt', 'snapshotId'}}
    return hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--outcomes-input', type=Path)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input_root, registered=True)
    if args.outcomes_input:
        outcomes = json.loads(args.outcomes_input.read_text(encoding='utf-8'))
        if not isinstance(outcomes, list) or any(not isinstance(outcome, dict) or outcome.get('reviewStatus') != 'draft' or outcome.get('impact') is not None for outcome in outcomes):
            raise ValueError('結果評価候補の形式が不正です')
        snapshot['outcomes'] = outcomes
    stable = {key: value for key, value in snapshot.items() if key != 'observedAt'}
    snapshot['snapshotId'] = snapshot_digest(snapshot)
    args.output_root.mkdir(parents=True, exist_ok=True)
    releases = args.output_root / 'releases'
    releases.mkdir(exist_ok=True)
    version = releases / (snapshot['snapshotId'] + '.json')
    if version.exists():
        serialized = version.read_text(encoding='utf-8')
        old = json.loads(serialized)
        if {key: value for key, value in old.items() if key not in {'observedAt', 'snapshotId'}} != stable:
            raise ValueError('保存済み統計版と同じ識別子の内容が一致しません')
    else:
        serialized = json.dumps(snapshot, ensure_ascii=False, indent=2)
        version_stage = releases / (snapshot['snapshotId'] + '.pending.json')
        with version_stage.open('w', encoding='utf-8') as output:
            output.write(serialized)
        os.replace(version_stage, version)
    stage = args.output_root / 'current.pending.json'
    stage.write_text(serialized, encoding='utf-8')
    os.replace(stage, args.output_root / 'current.json')
    print(json.dumps({'series': len(snapshot['series']), 'points': sum(len(series['points']) for series in snapshot['series']), 'output': str(args.output_root / 'current.json')}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
