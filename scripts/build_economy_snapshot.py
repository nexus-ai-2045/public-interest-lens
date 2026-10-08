from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path


INDICATORS = {'NY.GDP.MKTP.KN': ('real_gdp', '実質GDP', '円・一定価格'), 'NY.GDP.MKTP.CN': ('nominal_gdp', '名目GDP', '円・当年価格'), 'SP.POP.TOTL': ('population', '人口', '人')}


def build_snapshot(input_root: Path) -> dict:
    series = []
    for indicator, (identifier, label, unit) in INDICATORS.items():
        raw = (input_root / f'{indicator}.json').read_bytes()
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
        series.append({'id': identifier, 'label': label, 'unit': unit, 'basis': '提供元が公表する単一系列。別基準の国内系列とは接続していません。', 'sourceUrl': f'https://api.worldbank.org/v2/country/JPN/indicator/{indicator}?format=json&date=1980:2025&per_page=100', 'originalSha256': hashlib.sha256(raw).hexdigest(), 'sourceUpdatedAt': payload[0].get('lastupdated'), 'points': sorted(points, key=lambda point: point['year'])})
    population = {point['year']: point['value'] for point in series[2]['points']}
    real = series[0]
    per_capita = [{**point, 'value': point['value'] / population[point['year']] if point['value'] is not None and population.get(point['year']) else None} for point in real['points']]
    series.append({**real, 'id': 'real_gdp_per_capita', 'label': '一人当たり実質GDP', 'unit': '円／人・一定価格', 'derivedFrom': ['real_gdp', 'population'], 'points': per_capita})
    return {'schemaVersion': 'economic-series/v1', 'observedAt': datetime.now(timezone.utc).isoformat(), 'provider': 'World Bank WDI', 'country': 'JPN', 'series': series, 'unavailable': ['労働生産性', '設備投資', '研究開発投資'], 'causes': [], 'note': '統計の推移だけで、特定の政策や人物による影響とは認定しません。'}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--input-root', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--outcomes-input', type=Path)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input_root)
    if args.outcomes_input:
        outcomes = json.loads(args.outcomes_input.read_text(encoding='utf-8'))
        if not isinstance(outcomes, list) or any(not isinstance(outcome, dict) or outcome.get('reviewStatus') != 'draft' or outcome.get('impact') is not None for outcome in outcomes):
            raise ValueError('結果評価候補の形式が不正です')
        snapshot['outcomes'] = outcomes
    stable = {key: value for key, value in snapshot.items() if key != 'observedAt'}
    snapshot['snapshotId'] = hashlib.sha256(json.dumps(stable, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
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
