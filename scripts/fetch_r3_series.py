"""R3：影響の判定で「系列なし」「比較群なし」になっている指標のうち、OECD・世界銀行から取れば埋まる可能性のある国際系列を取得する（task-id r3-series）。

取得するもの（SERIES_PLAN を参照。★は取得できるかをこの環境から確かめていないもの＝未確認）
- 世界銀行 WDI（api.worldbank.org、13か国を1回の呼び出しで）
  ★IS.AIR.PSGR       航空旅客数（登録航空会社が運んだ旅客数）            ← 指標「利用件数」のうち空港・航空の法律の候補
  ★IS.SHP.GOOD.TU    コンテナ港湾取扱量（TEU）                           ← 同、港湾・海事の法律の候補
  ★IS.RRS.PASG.KM    鉄道旅客キロ                                         ← 同、鉄道の法律の候補（欠ける国が多いと思われる）
  ★SL.GDP.PCAP.EM.KD 就業者1人当たりGDP（2021年PPP固定価格）              ← 指標「労働生産性」の代理（いまの労働力人口当たりGDPより就業者ベース）
- OECD（sdmx.oecd.org、SDMX REST）
  ★OECD.ELS.SAE,DSD_TENURE@DF_TENURE_FREQ,1.0 の日本の全系列（指標「雇用の流動性」。日本の開始前の値が2013年からしか無い件で、
    それより前の年・別の区分が日本にあるかを確かめる探査。gap-stats/status.csv は2013年以降だけと記録している）

金融・保険業の付加価値（OECD 表6の産業 K）は取得し直さない：data/acquired/oecd-industry/industry_va.csv に13か国すべて取得済み
（日本 1994〜2024年、連鎖実質 L・LR）。足りないのは取得ではなく指標から系列への対応表（app/src/impact-batch.ts）と読み込み先（run-impact-v1.mjs が
oecd-industry を読まない）。

原本は --raw（既定 .local/r3-series/raw、再開用の控え）に保存し、.local/external-materials/r3-series/ に外部資料として登録します（record.json、初期状態 unverified）。
URL・sha256・HTTP の結果・material_id を manifest.csv に残します（原本は Git に入れない）。
整えた表は --out（既定 data/acquired/r3-series）の r3-series.csv（列: 国,指標,年,値,単位,基準年,出典URL。intl-stats と同じ列）に書きます。
欠けた年・空の値は書きません（0で埋めない・補間しない）。status.csv に系列ごとの取得状況（取得できた国・年の範囲、取得できなかった理由）を書きます。
すでに原本があれば取りに行かない（途中で止まっても同じコマンドで再開できる）。取りに行く間隔は既定1.1秒。

使い方:
  python3 scripts/fetch_r3_series.py --dry-run          # 取りに行く URL と保存先を表示するだけ（通信もファイル書き込みもしない）
  python3 scripts/fetch_r3_series.py                    # 全部取る
  python3 scripts/fetch_r3_series.py --only wb          # 世界銀行だけ（oecd も同様。系列の符号 IS.AIR.PSGR なども指定できる）
  python3 scripts/fetch_r3_series.py --rebuild          # 取得せず、保存済みの原本から表だけ作り直す
  python3 scripts/fetch_r3_series.py --prior-manifest 前の manifest.csv  # manifest を作り直すとき、最初の取得時刻を引き継ぐ
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

try:  # 直接実行（python3 scripts/...）とモジュール実行の両方に対応
    from scripts.register_external_material import register_once
except ImportError:  # pragma: no cover
    from register_external_material import register_once

COUNTRIES = ['JPN', 'USA', 'GBR', 'FRA', 'DEU', 'ITA', 'CAN', 'KOR', 'NLD', 'NOR', 'SWE', 'ESP', 'AUS']
# 観測状態：取得元が付けた観測の状態（世界銀行 obs_status、OECD OBS_STATUS。A=通常、E=推計、P=暫定など）。空は状態の印なし
OUT_COLUMNS = ['国', '指標', '年', '値', '単位', '基準年', '出典URL', '観測状態']
MANIFEST_COLUMNS = ['url', 'path', 'sha256', 'http', 'fetched_at', 'material_id']
TASK_ID = 'r3-series'  # 外部資料の保管庫 <root>/.local/external-materials/r3-series/（AGENTS.md）
STATUS_COLUMNS = ['系列', '対象', '状況', '理由', '出典URL']
INTERVAL_SECONDS = 1.1
UA = 'public-interest-lens r3-series (research)'
SDMX_ACCEPT = 'application/vnd.sdmx.data+csv; charset=utf-8'
WB_BASE = 'https://api.worldbank.org/v2'
OECD_BASE = 'https://sdmx.oecd.org/public/rest/data'

# 世界銀行の指標コード：(日本語の名前, 単位, 使い道)。いずれもこの環境からは確かめていない（未確認）。コードは知識による。
WB_SERIES: dict[str, tuple[str, str, str]] = {
    'IS.AIR.PSGR': ('航空旅客数（登録航空会社が運んだ旅客数）', '人', '利用件数（空港・航空）'),
    'IS.SHP.GOOD.TU': ('コンテナ港湾取扱量（TEU）', 'TEU', '利用件数（港湾・海事）'),
    'IS.RRS.PASG.KM': ('鉄道旅客キロ', '人キロ', '利用件数（鉄道）。欠ける国が多い可能性'),
    'SL.GDP.PCAP.EM.KD': ('就業者1人当たりGDP（PPP固定米ドル。基準年は未確認）', '米ドル', '労働生産性の代理（就業者ベース）。基準年の表記（2021）は未確認'),
}
# OECD：id -> (データフロー, 次元キー, 指標名の接頭辞, 開始年, 使い道)。次元キーは gap-stats の oecd-tenure の URL（7次元）から、日本だけに絞って他を全部指定なし（空）にしたもの。
OECD_SERIES: dict[str, tuple[str, str, str, int, str]] = {
    'TENURE-JPN': ('OECD.ELS.SAE,DSD_TENURE@DF_TENURE_FREQ,1.0', 'JPN......', 'OECD:TENURE_FREQ', 1980, '雇用の流動性：日本の勤続年数別の全系列（2013年より前・別の区分の探査）'),
}


# ---- 純粋関数：URL・応答の解釈 ----

def wb_url(code: str, page: int = 1) -> str:
    """more-stats の世界銀行の呼び出しと同じ形（13か国を ; でつなぐ）。page=1 は page を付けない。"""
    base = f'{WB_BASE}/country/{";".join(COUNTRIES)}/indicator/{code}?format=json&per_page=2000&date=1960:2025'
    return base if page == 1 else f'{base}&page={page}'


def oecd_url(series_id: str) -> str:
    flow, key, _, start, _ = OECD_SERIES[series_id]
    return f'{OECD_BASE}/{flow}/{key}?startPeriod={start}'


def parse_wb_json(text: str, code: str, label: str, unit: str, url: str) -> tuple[list[dict[str, str]], int]:
    """世界銀行 API v2 の応答を (整えた行, 総ページ数) にする。値が null の観測は捨てる。
    エラーは HTTP 200 で [{"message": [...]}] として返ることがあるので、その場合は ValueError。"""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f'JSON として読めない: {e}') from e
    if not isinstance(data, list) or not data:
        raise ValueError('想定外の応答の形（リストでない／空）')
    head = data[0]
    if not isinstance(head, dict):
        raise ValueError('想定外の応答の形（先頭がオブジェクトでない）')
    if 'message' in head and 'page' not in head:
        msgs = head.get('message') or []
        detail = '; '.join(f"{m.get('id', '')} {m.get('value', '')}".strip() for m in msgs if isinstance(m, dict))
        raise ValueError(f'世界銀行がエラーを返した: {detail or head}')
    pages = int(head.get('pages') or 1)
    rows: dict[tuple[str, str], dict[str, str]] = {}
    for obs in (data[1] if len(data) > 1 and data[1] else []):
        value = obs.get('value')
        if value is None or str(value).strip() == '':
            continue
        country = (obs.get('countryiso3code') or '').strip()
        if country not in COUNTRIES:
            continue  # 集計地域などは比較国ではない
        year = str(obs.get('date', '')).strip()
        if not year:
            continue
        key = (country, year)
        row = {'国': country, '指標': f'WB:{code}', '年': year, '値': str(value), '単位': f'{label}（{unit}）', '基準年': '', '出典URL': url,
               '観測状態': str(obs.get('obs_status') or '').strip()}
        if key in rows and rows[key]['値'] != row['値']:
            raise ValueError(f'同じキーで値が食い違う: {key}')
        rows[key] = row
    return sorted(rows.values(), key=lambda r: (r['国'], int(r['年']) if r['年'].isdigit() else 0)), pages


_META = {'STRUCTURE', 'STRUCTURE_ID', 'STRUCTURE_NAME', 'ACTION'}


SDMX_META = {'DATAFLOW', 'STRUCTURE', 'STRUCTURE_ID', 'STRUCTURE_NAME', 'ACTION'}


def parse_sdmx_csv(text: str, prefix: str, url: str, countries: list[str] | None = None) -> list[dict[str, str]]:
    """SDMX-CSV（labels=id）を intl-stats と同じ列の行にする。国は REF_AREA。
    指標名は「prefix:」に、REF_AREA・FREQ・TIME_PERIOD 以外の次元の値を . でつないだもの（SDMX のキーの並びと同じ）。
    値が空の行は捨てる。同じキーで値が食い違えば止める。"""
    reader = csv.DictReader(io.StringIO(text.lstrip('﻿')))
    fields = reader.fieldnames or []
    for need in ('REF_AREA', 'TIME_PERIOD', 'OBS_VALUE'):
        if need not in fields:
            raise ValueError(f'SDMX-CSV に列 {need} が無い（列: {fields}）')
    # 次元は TIME_PERIOD より前の列（属性は OBS_VALUE の後ろ）。SDMX-CSV の形（STRUCTURE 形式・DATAFLOW 形式）の
    # どちらでも、データフローを示す列・ACTION は系列の名前に入れない
    dims = [f for f in fields[:fields.index('TIME_PERIOD')] if f not in SDMX_META and f not in ('REF_AREA', 'FREQ')]
    rows: dict[tuple[str, str, str], dict[str, str]] = {}
    for rec in reader:
        value = (rec.get('OBS_VALUE') or '').strip()
        if not value:
            continue
        country = rec['REF_AREA'].strip()
        if countries is not None and country not in countries:
            continue
        indicator = f"{prefix}:{'.'.join((rec.get(d) or '').strip() for d in dims)}"
        year = rec['TIME_PERIOD'].strip()
        mult = (rec.get('UNIT_MULT') or '').strip()
        unit = (rec.get('UNIT_MEASURE') or '').strip() + (f'（UNIT_MULT={mult}）' if mult not in ('', '0') else '')
        base = (rec.get('BASE_PER') or rec.get('REF_YEAR_PRICE') or '').strip()
        row = {'国': country, '指標': indicator, '年': year, '値': value, '単位': unit, '基準年': base, '出典URL': url,
               '観測状態': (rec.get('OBS_STATUS') or '').strip()}
        key = (country, indicator, year)
        if key in rows and rows[key]['値'] != value:
            raise ValueError(f'同じキーで値が食い違う: {key}')
        rows[key] = row
    return sorted(rows.values(), key=lambda r: (r['指標'], r['国'], r['年']))


def nonempty(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """保存前の確かめ：値のある行が1つも無い応答は使わない（控えに残すと、上流が直っても取り直さない）。"""
    if not rows:
        raise ValueError('値のある行が無い')
    return rows


def coverage(rows: list[dict[str, str]]) -> dict[str, dict[str, tuple[int, int, int]]]:
    """指標 -> 国 -> (最初の年, 最後の年, 点数)。年が数字でない行（四半期など）は数えない。"""
    out: dict[str, dict[str, list[int]]] = {}
    for r in rows:
        if not r['年'].isdigit():
            continue
        out.setdefault(r['指標'], {}).setdefault(r['国'], []).append(int(r['年']))
    return {i: {c: (min(ys), max(ys), len(ys)) for c, ys in cs.items()} for i, cs in out.items()}


def describe_coverage(cov: dict[str, tuple[int, int, int]]) -> str:
    """status.csv の理由欄用：国の数と日本の範囲、国ごとの範囲。"""
    if not cov:
        return '値のある国なし'
    jp = cov.get('JPN')
    head = f'{len(cov)}/{len(COUNTRIES)}か国' + (f'、日本 {jp[0]}〜{jp[1]}年（{jp[2]}点）' if jp else '、日本の値なし')
    return head + '：' + ' '.join(f'{c}:{a}-{b}' for c, (a, b, _) in sorted(cov.items()))


def plan_requests(only: list[str] | None = None) -> list[dict[str, str]]:
    """取りに行くものの一覧（通信しない）。only は wb・oecd・系列の符号（IS.AIR.PSGR など）の組。空なら全部。"""
    wanted = {o.lower() for o in only} if only else None
    out: list[dict[str, str]] = []
    for code in WB_SERIES:
        if wanted is None or 'wb' in wanted or code.lower() in wanted:
            out.append({'kind': 'wb', 'id': code, 'url': wb_url(code), 'raw': f'wb/{code}.json', 'accept': 'application/json'})
    for sid in OECD_SERIES:
        if wanted is None or 'oecd' in wanted or sid.lower() in wanted:
            out.append({'kind': 'oecd', 'id': sid, 'url': oecd_url(sid), 'raw': f'oecd/{sid}.csv', 'accept': SDMX_ACCEPT})
    if wanted is not None:
        known = {'wb', 'oecd'} | {c.lower() for c in WB_SERIES} | {s.lower() for s in OECD_SERIES}
        unknown = wanted - known
        if unknown:
            raise ValueError(f'未知の --only: {sorted(unknown)}（使えるもの: wb, oecd, {", ".join(list(WB_SERIES) + list(OECD_SERIES))}）')
    return out


def rel_path(dest: Path, root: Path) -> str:
    """manifest の path 用。リポジトリからの相対パス。外にあるときはファイル名だけ（絶対パスを残さない）。"""
    try:
        return dest.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return dest.name


# ---- 入出力 ----

def append_manifest(manifest: Path, row: list) -> None:
    new = not manifest.exists()
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with manifest.open('a', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(MANIFEST_COLUMNS)
        w.writerow(row)


def default_open(url: str, accept: str) -> tuple[int, bytes | None]:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept}), timeout=180) as res:
            return res.status, res.read()
    except urllib.error.HTTPError as e:
        return e.code, None
    except (urllib.error.URLError, TimeoutError) as e:
        print(f'接続できない: {url} {e}', file=sys.stderr)
        return -1, None


def register(dest: Path, url: str, root: Path, fetched_at: str | None = None) -> str:
    """使える原本を外部資料として登録し、material_id を返す（同じ日・同じ中身は登録し直さない）。
    fetched_at が無い（控えから登録する）ときは、控えの更新時刻を取得時刻の代わりに記録の根拠つきで入れる。"""
    return register_once(input_path=dest, source_url=url, task_id=TASK_ID, title=f'R3 の国際系列の原本（{dest.name}）',
                         purpose='確かな額を増やす（R3）', storage_root=root / '.local' / 'external-materials',
                         observed_at=fetched_at)


def prior_fetches(path: Path | None) -> dict[tuple[str, str, str], tuple[str, str]]:
    """前の manifest の (url, path, sha256) → (http, fetched_at)。取得時刻の分かる行だけ（控えから作り直しても最初の取得時刻を消さない）。"""
    if not path or not path.exists():
        return {}
    with path.open(encoding='utf-8', newline='') as fh:
        return {(r['url'], r['path'], r['sha256']): (r['http'], r['fetched_at'])
                for r in csv.DictReader(fh) if r.get('fetched_at')}


def fetch(url: str, dest: Path, manifest: Path, root: Path, accept: str, validate: Callable[[bytes], None] | None = None,
          opener: Callable[[str, str], tuple[int, bytes | None]] = default_open, interval: float = INTERVAL_SECONDS,
          sleep: Callable[[float], None] = time.sleep,
          prior: dict[tuple[str, str, str], tuple[str, str]] | None = None) -> tuple[bytes | None, int]:
    """原本があればそれを使う（再開）。無ければ取りに行き、結果を manifest に残す。(本文, HTTP の結果) を返す。
    validate が例外を出す本文（HTTP 200 のエラー応答など）は dest に保存せず、dest.invalid に残して None を返す。"""
    if dest.exists() and validate is not None:
        try:
            validate(dest.read_bytes())
        except (ValueError, UnicodeDecodeError) as e:  # 前の版が残した・壊れた控えは退避して取り直す
            dest.replace(dest.with_name(dest.name + '.invalid'))
            print(f'控えが使えないので取り直す: {url} {e}', file=sys.stderr)
    if dest.exists():
        body = dest.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        known = False
        if manifest.exists():
            with manifest.open(encoding='utf-8') as fh:
                known = any(r.get('url') == url and r.get('sha256') == digest for r in csv.DictReader(fh))
        if not known:
            # 前の manifest に同じ URL・置き場所・中身の行があれば、その HTTP と取得時刻を引き継ぐ。無ければ取得時刻は分からないので空欄
            http, fetched_at = (prior or {}).get((url, rel_path(dest, root), digest), ('cache', ''))
            append_manifest(manifest, [url, rel_path(dest, root), digest, http, fetched_at,
                                       register(dest, url, root, fetched_at or None)])
        return body, 200
    sleep(interval)
    status, body = opener(url, accept)
    fetched_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    digest = hashlib.sha256(body).hexdigest() if body else ''
    if body is None or status != 200:
        append_manifest(manifest, [url, rel_path(dest, root), digest, status, fetched_at, ''])
        print(f'取得できない: {url} http={status}', file=sys.stderr)
        return None, status
    if validate is not None:
        try:
            validate(body)
        except (ValueError, UnicodeDecodeError) as e:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.with_name(dest.name + '.invalid').write_bytes(body)
            append_manifest(manifest, [url, rel_path(dest, root), digest, status, fetched_at, ''])
            print(f'応答が使えない: {url} {e}', file=sys.stderr)
            return None, status
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    # 使える原本は外部資料として登録する（record.json、内容の初期状態は unverified）
    append_manifest(manifest, [url, rel_path(dest, root), digest, status, fetched_at, register(dest, url, root, fetched_at)])
    return body, status


def run(plan: list[dict[str, str]], raw: Path, out: Path, root: Path, rebuild: bool = False,
        opener: Callable[[str, str], tuple[int, bytes | None]] = default_open, interval: float = INTERVAL_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
        prior: dict[tuple[str, str, str], tuple[str, str]] | None = None) -> tuple[list[dict[str, str]], list[list[str]], list[str]]:
    """plan の順に取り、(全行, status.csv の行, 失敗した系列) を返す。prior は前の manifest（prior_fetches）。"""
    manifest = out / 'manifest.csv'
    all_rows: list[dict[str, str]] = []
    status_rows: list[list[str]] = []
    failed: list[str] = []
    for item in plan:
        kind, sid, url = item['kind'], item['id'], item['url']
        rows: list[dict[str, str]] = []
        reason = ''
        ok = True
        if kind == 'wb':
            label, unit, _ = WB_SERIES[sid]
            page, pages = 1, 1
            while page <= pages:
                purl = wb_url(sid, page)
                dest = raw / (item['raw'] if page == 1 else item['raw'].replace('.json', f'-p{page}.json'))
                if rebuild:
                    body = dest.read_bytes() if dest.exists() else None
                    http = 200 if body else 0
                else:
                    body, http = fetch(purl, dest, manifest, root, item['accept'], validate=lambda b: nonempty(parse_wb_json(b.decode('utf-8'), sid, label, unit, purl)[0]),
                                       opener=opener, interval=interval, sleep=sleep, prior=prior)
                if body is None:
                    ok, reason = False, f'取得できない（HTTP {http}）' if http != 200 else '応答が使えない（dest.invalid を見る）'
                    break
                got, pages = parse_wb_json(body.decode('utf-8'), sid, label, unit, purl)
                rows.extend(got)
                page += 1
        else:
            _, _, prefix, _, _ = OECD_SERIES[sid]
            dest = raw / item['raw']
            if rebuild:
                body = dest.read_bytes() if dest.exists() else None
                http = 200 if body else 0
            else:
                # 世界銀行と同じく、表として読めない応答（HTTP 200 の HTML など）は控えに残さず、次の実行で取り直す
                body, http = fetch(url, dest, manifest, root, item['accept'], opener=opener, interval=interval, sleep=sleep,
                                   prior=prior, validate=lambda b: nonempty(parse_sdmx_csv(b.decode('utf-8'), prefix, url)))
            if body is None:
                ok, reason = False, f'取得できない（HTTP {http}）'
            else:
                try:
                    rows = parse_sdmx_csv(body.decode('utf-8'), prefix, url)
                except ValueError as e:
                    ok, reason = False, f'表として読めない: {e}'
        if ok and not rows:  # 値の無い応答で前回の行を消さない（取れなかった系列として扱う）
            ok, reason = False, '取得したが値のある行が無い'
        if ok:
            cov = coverage(rows)
            if kind == 'wb':
                reason = describe_coverage(cov.get(f'WB:{sid}', {}))
            else:
                reason = f'{len(cov)}系列。' + '；'.join(f'{i} {describe_coverage(cs)}' for i, cs in sorted(cov.items())[:50])
            all_rows.extend(rows)
        else:
            failed.append(sid)
        status_rows.append([sid, kind, '取得できた' if ok else '取得できず', reason, url])
    return all_rows, status_rows, failed


def series_of(indicator: str) -> str:
    """表の「指標」→ 系列の符号（plan の id）。世界銀行は WB:<符号>、OECD は接頭辞で決める。"""
    if indicator.startswith('WB:'):
        return indicator[3:]
    for sid, (_, _, prefix, _, _) in OECD_SERIES.items():
        if indicator.startswith(prefix + ':'):
            return sid
    return ''


def merge_outputs(out: Path, plan: list[dict[str, str]], rows: list[dict[str, str]], status_rows: list[list[str]],
                  failed: list[str]) -> tuple[list[dict[str, str]], list[list[str]]]:
    """今回取れた系列だけを置き換え、--only で選ばなかった系列と取れなかった系列は前の表の行を残す。"""
    done = {item['id'] for item in plan} - set(failed)
    old_rows, old_status = [], {}
    if (out / 'r3-series.csv').exists():
        with (out / 'r3-series.csv').open(encoding='utf-8', newline='') as fh:
            old_rows = [r for r in csv.DictReader(fh) if series_of(r['指標']) not in done]
    if (out / 'status.csv').exists():
        with (out / 'status.csv').open(encoding='utf-8', newline='') as fh:
            old_status = {r[0]: r for r in list(csv.reader(fh))[1:] if r}
    kept = {series_of(r['指標']) for r in old_rows}
    new_status = {}
    for r in status_rows:
        if r[0] in failed and r[0] in kept:
            r = r[:3] + [r[3] + '（前回の行を残した）'] + r[4:]
        new_status[r[0]] = r
    status = [new_status.get(sid) or old_status[sid] for sid in dict.fromkeys([*old_status, *new_status])]
    return [{c: r.get(c) or '' for c in OUT_COLUMNS} for r in old_rows] + rows, status


def write_outputs(out: Path, rows: list[dict[str, str]], status_rows: list[list[str]]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / 'r3-series.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(sorted(rows, key=lambda r: (r['指標'], r['国'], r['年'])))
    with (out / 'status.csv').open('w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh)
        w.writerow(STATUS_COLUMNS)
        w.writerows(status_rows)


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[1]
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument('--raw', type=Path, default=root / '.local' / 'r3-series' / 'raw', help='原本の保存先（既定 .local/r3-series/raw）')
    p.add_argument('--out', type=Path, default=root / 'data' / 'acquired' / 'r3-series', help='表と manifest の出力先（既定 data/acquired/r3-series）')
    p.add_argument('--only', nargs='+', help='wb・oecd・系列の符号（IS.AIR.PSGR など）。既定は全部')
    p.add_argument('--interval', type=float, default=INTERVAL_SECONDS, help='取りに行く間隔の秒数（既定1.1）')
    p.add_argument('--dry-run', action='store_true', help='取りに行く URL と保存先を表示するだけ（通信もファイル書き込みもしない）')
    p.add_argument('--rebuild', action='store_true', help='取得せず、保存済みの原本から表を作り直す')
    p.add_argument('--prior-manifest', type=Path, default=None,
                   help='前の manifest（作り直す前の写し）。同じ URL・置き場所・中身の控えは、その HTTP と取得時刻を引き継ぐ')
    ns = p.parse_args(argv)
    try:
        plan = plan_requests(ns.only)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if ns.dry_run:
        for item in plan:
            dest = ns.raw / item['raw']
            print(f"{item['kind']}\t{item['id']}\t{'原本あり（取りに行かない）' if dest.exists() else '取りに行く'}\t{item['url']}\t-> {rel_path(dest, root)}")
        print(f'{len(plan)}件（間隔 {ns.interval} 秒。世界銀行は総ページが2以上なら page=2.. も取る）')
        return 0
    rows, status_rows, failed = run(plan, ns.raw, ns.out, root, rebuild=ns.rebuild, interval=ns.interval,
                                    prior=prior_fetches(ns.prior_manifest))
    rows, status_rows = merge_outputs(ns.out, plan, rows, status_rows, failed)
    write_outputs(ns.out, rows, status_rows)
    print(f'{len(rows)} 行を書きました。取得できなかった系列: {failed or "なし"}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
