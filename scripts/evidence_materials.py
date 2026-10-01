"""登録済み原本から実資料の閲覧候補を作る。取得・人物同定・採点はしません。"""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from .fetch_diet_minutes import _validate_page, _verified_material
from .fetch_sangiin_votes import read_registered_votes

TOPIC_WORDS = ('研究', '科学技術', 'イノベーション', 'デジタル', '情報通信技術', '情報処理')
MAX_MATERIAL_BYTES = 32 * 1024 * 1024
MAX_ROWS = 1000


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _id(*values: str) -> str:
    return _digest(json.dumps(values, ensure_ascii=False, separators=(',', ':')).encode())


def _official(url: str) -> bool:
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    return (parsed.scheme == 'https' and not parsed.username and not parsed.password
            and ':' not in parsed.netloc and parsed.hostname in {'kokkai.ndl.go.jp', 'www.sangiin.go.jp'})


def _registered(path: Path, root: Path, expected_hash: str) -> tuple[dict, bytes]:
    path = path.resolve(strict=True)
    if not path.is_relative_to(root.resolve(strict=True)):
        raise ValueError('登録原本の参照が保管先外です')
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('登録原本のメタデータ上限を超えています')
    record = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(record, dict):
        raise ValueError('登録メタデータはJSONオブジェクトが必要です')
    size = record.get('bytes')
    if type(size) is not int or not 0 < size <= MAX_MATERIAL_BYTES or not _official(record.get('source_url', '')):
        raise ValueError('登録原本のURLまたはサイズが不正です')
    checked = _verified_material(path, roots=(root,), url=record['source_url'],
                                 digest=expected_hash, expected_bytes=size)
    payload = (path.parent / checked['saved_filename']).read_bytes()
    return checked, payload


def _speeches(payload: dict, endpoint: str):
    if not isinstance(payload, dict):
        raise ValueError('会議録はJSONオブジェクトが必要です')
    if endpoint == 'meeting':
        for meeting in payload.get('meetingRecord', []):
            for speech in meeting.get('speechRecord', []):
                yield {**speech, 'date': speech.get('date') or meeting.get('date'),
                       'imageKind': speech.get('imageKind') or meeting.get('imageKind')}
    elif endpoint == 'speech':
        yield from payload.get('speechRecord', [])
    else:
        raise ValueError('本文のない会議一覧は閲覧用本文へ昇格しません')


def _material(mid: str, record: dict, text: str) -> dict:
    return {'id': mid, 'text': text, 'url': record['source_url'],
            'originalHash': record['sha256'], 'contentHash': _digest(text.encode('utf-8')),
            'observedAt': record['observed_at'], 'publishedAt': None}


def read_material(ref: dict, material_root: Path, *, _cache=None) -> dict:
    """AIの本文を信用せず、検証した原本から本文と日時を再抽出します。"""
    if not isinstance(ref, dict) or not isinstance(ref.get('selector'), dict):
        raise ValueError('原本参照と位置指定はオブジェクトが必要です')
    cache = {} if _cache is None else _cache
    record_key = (str(Path(ref['recordPath']).resolve()), ref['originalHash'])
    if record_key not in cache:
        cache[record_key] = _registered(Path(ref['recordPath']), material_root, ref['originalHash'])
    record, payload = cache[record_key]
    selector = ref['selector']
    if selector['kind'] == 'ndl-speech':
        if urlsplit(record['source_url']).hostname != 'kokkai.ndl.go.jp':
            raise ValueError('会議録の取得元が不正です')
        parsed_key = ('speech', record_key)
        if parsed_key not in cache:
            source = json.loads(payload.decode('utf-8'))
            endpoint = 'meeting' if 'meetingRecord' in source else 'speech'
            cache[parsed_key] = list(_speeches(source, endpoint))
        matched = [s for s in cache[parsed_key] if s.get('speechID') == selector['speechId']]
        if len(matched) != 1:
            raise ValueError('発言の原本照合が一意ではありません')
        row = matched[0]
        if row.get('imageKind') != '会議録' or not isinstance(row.get('speech'), str) or not row['speech'].strip():
            raise ValueError('可読発言本文がありません')
        text = row['speech']
    elif selector['kind'] == 'vote-row':
        parsed_key = ('vote', record_key, selector['billId'], selector['title'])
        if parsed_key not in cache:
            cache[parsed_key] = read_registered_votes(Path(ref['recordPath']), material_root=material_root,
                bill_id=selector['billId'], title=selector['title'], url=record['source_url'])
        vote = cache[parsed_key]
        matched = [r for r in vote['rows'] if r['sourceLine'] == selector['sourceLine'] and r['nameText'] == selector['nameText']]
        if len(matched) != 1:
            raise ValueError('投票行の原本照合が一意ではありません')
        text = matched[0]['rowText']
    else:
        raise ValueError('未対応の原本位置です')
    return _material(ref['id'], record, text)


def read_materials(refs: list[dict], material_root: Path) -> list[dict]:
    if not isinstance(refs, list) or any(not isinstance(r, dict) for r in refs):
        raise ValueError('原本参照の一覧が不正です')
    if len(refs) > 2 * MAX_ROWS or len({r['id'] for r in refs}) != len(refs):
        raise ValueError('原本参照が重複または上限超過です')
    cache = {}
    return [read_material(ref, material_root, _cache=cache) for ref in refs]


def select_policies(candidates: list[dict], as_of: str) -> dict:
    if not isinstance(candidates, list) or any(not isinstance(c, dict) for c in candidates):
        raise ValueError('候補政策の一覧が不正です')
    cutoff = date.fromisoformat(as_of)
    try:
        start = cutoff.replace(year=cutoff.year - 4)
    except ValueError:
        start = cutoff.replace(year=cutoff.year - 4, day=28)
    if len(candidates) > MAX_ROWS:
        raise ValueError('候補政策の上限を超えています')
    seen = set()
    selected = []
    for item in candidates:
        if not isinstance(item.get('id'), str) or not item['id'] or item['id'] in seen:
            raise ValueError('候補政策IDが空または重複しています')
        seen.add(item['id'])
        submitted = date.fromisoformat(item['submittedAt'])
        if start <= submitted <= cutoff and any(word in item['title'] for word in TOPIC_WORDS):
            selected.append(item)
    selected.sort(key=lambda item: (item['submittedAt'], item['id']), reverse=True)
    return {'criterionVersion': 'research-digital-registered-pilot-v1',
            'inventoryCompleteness': 'registered_candidates_only', 'asOf': as_of,
            'scope': '登録済み候補集合内で研究・デジタル語句と直近4年を固定し、最新順に最大3政策',
            'policies': selected[:3]}


def build_readable_evidence(source_dir: Path, material_root: Path, *, as_of: str,
                            candidates: list[dict], vote_records=()) -> dict:
    """有限保存済みページの引用を生成する。自己承認や本文からの採点はしません。"""
    date.fromisoformat(as_of)
    selection = select_policies(candidates, as_of)
    selected = {p.get('billId', p['id']): p for p in selection['policies']}
    manifest = json.loads((source_dir / 'manifest.json').read_text(encoding='utf-8'))
    if not isinstance(manifest, dict):
        raise ValueError('会議録manifestはオブジェクトが必要です')
    endpoint = manifest.get('endpoint')
    if manifest.get('schema_version') != 'diet-api-manifest/v1' or endpoint not in {'meeting', 'speech'} or manifest.get('status') not in {'capped', 'query_exhausted'}:
        raise ValueError('保存済み会議録manifestが不正です')
    pages = manifest.get('pages')
    if not isinstance(pages, list) or not pages:
        raise ValueError('取得ページがありません')
    speeches, votes, refs, materials, original_hashes = [], [], [], [], set()
    next_start, reported, seen, saved = 1, None, set(), 0
    speech_ids = set()
    for entry in pages:
        if entry['start_record'] != next_start:
            raise ValueError('取得ページの位置が連続していません')
        page_path = source_dir / 'pages' / f'{next_start:09d}.json'
        resolved = page_path.resolve(strict=True)
        if not resolved.is_relative_to((source_dir / 'pages').resolve()):
            raise ValueError('取得ページの参照が範囲外です')
        record, payload = _registered(Path(entry['record_path']), material_root, entry['sha256'])
        if payload != page_path.read_bytes() or record['source_url'] != entry['source_url']:
            raise ValueError('取得ページと登録原本が一致しません')
        data = json.loads(payload.decode('utf-8'))
        records, reported, ids, complete = _validate_page(data, endpoint, next_start, 100, reported, seen)
        if len(records) != entry['record_count']:
            raise ValueError('取得レコード数が一致しません')
        seen.update(ids)
        saved += len(records)
        original_hashes.add(record['sha256'])
        for speech in _speeches(data, endpoint):
            if speech.get('imageKind') != '会議録' or not isinstance(speech.get('speech'), str) or not speech['speech'].strip():
                continue
            event_date = speech.get('date')
            if not isinstance(event_date, str):
                continue
            date.fromisoformat(event_date)
            if event_date > as_of:
                continue
            sid = speech.get('speechID')
            if not isinstance(sid, str) or not sid or sid in speech_ids:
                raise ValueError('発言IDが空または重複しています')
            speech_ids.add(sid)
            mid = _id('ndl-material', record['sha256'], sid)
            ref = {'id': mid, 'recordPath': entry['record_path'], 'originalHash': record['sha256'],
                   'selector': {'kind': 'ndl-speech', 'speechId': sid}}
            material = _material(mid, record, speech['speech'])
            materials.append({key: material[key] for key in ('id', 'url', 'originalHash', 'contentHash', 'observedAt', 'publishedAt')})
            refs.append(ref)
            speeches.append({'id': sid, 'speakerName': speech.get('speaker') or '記載名不明',
                'date': event_date, 'text': material['text'], 'sourceUrl': record['source_url'],
                'observedAt': record['observed_at'], 'sha256': record['sha256'], 'locator': f'NDL speechID={sid}'})
        next_start += len(records)
    if saved != manifest.get('records_saved') or reported != manifest.get('records_reported'):
        raise ValueError('manifestの保存数・報告数が原本と一致しません')
    if bool(complete) != bool(manifest.get('complete')):
        raise ValueError('manifestの終端が原本と一致しません')
    if not isinstance(vote_records, (list, tuple)) or any(not isinstance(s, dict) for s in vote_records):
        raise ValueError('投票原本の一覧が不正です')
    if len(vote_records) > 3:
        raise ValueError('投票原本は最大3政策です')
    if len({source['billId'] for source in vote_records}) != len(vote_records):
        raise ValueError('同一議案の投票原本が重複しています')
    for source in vote_records:
        policy = selected.get(source['billId'])
        if policy is None:
            raise ValueError('選定外の投票原本です')
        vote = read_registered_votes(Path(source['recordPath']), material_root=material_root,
            bill_id=source['billId'], title=policy['title'], url=source['url'], as_of=as_of)
        original_hashes.add(vote['sha256'])
        for row in vote['rows']:
            rid = _id('vote-observation', vote['sha256'], str(row['sourceLine']), row['nameText'])
            mid = _id('vote-material', rid)
            ref = {'id': mid, 'recordPath': source['recordPath'], 'originalHash': vote['sha256'],
                   'selector': {'kind': 'vote-row', 'billId': source['billId'], 'title': policy['title'],
                                'sourceLine': row['sourceLine'], 'nameText': row['nameText']}}
            material = _material(mid, {'source_url': vote['sourceUrl'], 'sha256': vote['sha256'],
                                      'observed_at': vote['observedAt']}, row['rowText'])
            materials.append({key: material[key] for key in ('id', 'url', 'originalHash', 'contentHash', 'observedAt', 'publishedAt')})
            refs.append(ref)
            votes.append({'id': rid, 'nameText': row['nameText'], 'date': vote['eventDate'],
                'position': {'賛成': 'for', '反対': 'against', '投票なし': 'not_voted'}.get(row['voteText'], 'unknown'),
                'title': policy['title'], 'policyId': source['billId'], 'text': material['text'],
                'sourceUrl': vote['sourceUrl'], 'observedAt': vote['observedAt'], 'sha256': vote['sha256'],
                'locator': f'HTML line={row["sourceLine"]}; allPublishedRowsConfirmed={vote["allPublishedRowsConfirmed"]}'})
    if len(speeches) > MAX_ROWS or len(votes) > MAX_ROWS:
        raise ValueError('有限閲覧の行数上限に到達しました')
    inspection = {'schemaVersion': 'ranking-dataset/v1', 'fictional': False, 'asOf': as_of,
        'coverage': {'scope': '保存済み参院会議録・登録済み候補政策の有限閲覧（人物・政策影響は未照合）',
            'assessedPeople': 0, 'targetPeople': None, 'sourceStatus': 'pages_captured', 'sourceRecords': saved},
        'people': [], 'policies': [], 'involvements': [], 'evidence': [],
        'held': [{'id': p['id'], 'title': p['title'], 'submittedAt': p['submittedAt'],
                  'reason': '人物同定・立場別政策影響の独立検証が未完了です。', 'sourceUrl': p.get('sourceUrl')} for p in selection['policies']],
        'readableEvidence': {'verificationState': 'unverified', 'selectionScope': selection['scope'],
            'speeches': speeches, 'votes': votes, 'counts': {'savedRecords': len(original_hashes),
                'readableSpeechBodies': len(speeches), 'sourceVoteRows': len(votes), 'confirmedActionEvidence': 0}}}
    return {**inspection, 'policySelection': selection, 'materialRefs': refs,
            'evidenceEvaluation': {'schemaVersion': 'evidence-evaluation/v1', 'mode': 'real',
                'options': {'domain': 'economy', 'direction': 'harm', 'period': 4, 'asOf': as_of,
                            'weights': {'economy': 70, 'technology': 30}},
                'people': [], 'materials': materials, 'actions': [], 'assessments': []}}
