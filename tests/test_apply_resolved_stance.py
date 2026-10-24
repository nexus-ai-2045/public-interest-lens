"""scripts/apply_resolved_stance.py：読み直しで決まった立場を関与の一覧に反映する。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from allocation_involvements import HEADER  # noqa: E402
from apply_resolved_stance import apply  # noqa: E402

URL = 'https://kokkai.ndl.go.jp/txt/119304319X01520170512/10'


def row(**kw):
    r = {k: '' for k in HEADER}
    r.update({'法律ID': '閣法-193-59', '題名': '架空の法律案', '院': '参議院', '行動': 'question', '立場区分': 'other', '証拠URL': URL})
    r.update(kw)
    return r


def res(name, stance, how='系統C・Dの一致'):
    return {'法案ID': '閣法-193-59', '氏名': name, '院': '参議院', '区分': '議員', '立場': stance, '決め方': how,
            '証拠URL': URL, '系統C': stance, '系統D': stance}


def votes_dir(tmp_path, ballots):
    (tmp_path / 'ballots').mkdir()
    (tmp_path / 'votes_index.csv').write_text('投票ID,回次,投票日,議案名,出典URL\n193-1-v001,193,2017-05-26,架空の法律案(内閣提出),https://www.sangiin.go.jp/x\n', encoding='utf-8')
    (tmp_path / 'members.csv').write_text('回次,議員ID,議員名\n' + ''.join(f'193,{i},{n}\n' for i, n in enumerate(ballots)), encoding='utf-8')
    (tmp_path / 'ballots' / 'ballots_193.csv').write_text('投票ID,議員ID,賛否\n' + ''.join(f'193-1-v001,{i},{v}\n' for i, v in enumerate(ballots.values())), encoding='utf-8')
    return tmp_path


def test_disagreement_is_replaced_but_other_exclusions_kept(tmp_path):
    inv = [row(氏名='甲', 算入='いいえ', 除外理由='2系統の立場が一致しない（A:中立、B:支持。ADR 0007）'),
           row(氏名='乙', 算入='いいえ', 除外理由='参議院本会議で反対票（反対者として数えない）'),
           row(氏名='丙', 算入='いいえ', 除外理由='2系統の立場が一致しない（A:中立、B:支持。ADR 0007）')]
    out, c = apply(inv, [res('甲', '支持'), res('乙', '支持'), res('丙', '中立')], votes_dir(tmp_path, {}))
    by = {r['氏名']: r for r in out}
    assert by['甲']['算入'] == 'はい' and by['甲']['除外理由'] == ''
    assert by['乙']['除外理由'].startswith('参議院本会議で反対票')
    assert by['丙']['算入'] == 'いいえ' and '中立' in by['丙']['除外理由']
    assert len(out) == 3


def test_new_speaker_is_added_and_no_vote_excluded(tmp_path):
    inv = [row(氏名='甲', 算入='はい')]
    out, c = apply(inv, [res('丁', '支持'), res('戊', '支持'), res('己', '無関係')], votes_dir(tmp_path, {'丁': 'Y', '戊': 'N'}))
    by = {r['氏名']: r for r in out}
    assert by['丁']['算入'] == 'はい' and by['丁']['日付'] == '2017-05-12' and by['丁']['参院本会議の賛否'] == 'Y'
    assert by['戊']['算入'] == 'いいえ' and by['戊']['除外理由'].startswith('参議院本会議で反対票')
    assert '己' not in by


def test_judge_only_support_is_not_counted_and_non_legislator_not_added(tmp_path):
    inv = [row(氏名='甲', 算入='いいえ', 除外理由='2系統の立場が一致しない（A:中立、B:支持。ADR 0007）')]
    judge = dict(res('甲', '支持', '上位の読み手の判定'), 系統C='中立', 系統D='反対')
    agreed = dict(res('乙', '支持', '上位の読み手の判定'), 系統C='支持', 系統D='中立')
    out, c = apply(inv, [judge, agreed, res('丙', '支持')], votes_dir(tmp_path, {}), legislators={'甲', '乙'})
    by = {r['氏名']: r for r in out}
    assert by['甲']['算入'] == 'いいえ' and by['甲']['除外理由'].startswith('上位の読み手だけの判定')
    assert by['甲']['系統A'] == '' and by['乙']['算入'] == 'はい'
    assert '丙' not in by and c['足さない:国会議員と確かめられない'] == 1


def test_house_is_read_from_meeting_id():
    from apply_resolved_stance import house_of
    assert house_of('https://kokkai.ndl.go.jp/txt/119314319X01520170512/10', '衆議院') == '参議院'
    assert house_of('https://kokkai.ndl.go.jp/txt/119604289X00620180302/4', '参議院') == '衆議院'


def test_speech_after_final_vote_is_not_added(tmp_path):
    inv = [row(氏名='甲', 行動='vote', 日付='2017-05-10', 算入='はい')]
    late = dict(res('乙', '支持'), 証拠URL='https://kokkai.ndl.go.jp/txt/119314319X01520170720/3')
    out, c = apply(inv, [late, res('丙', '支持')], votes_dir(tmp_path, {}))
    names = {r['氏名'] for r in out}
    assert '乙' not in names and '丙' not in names and c['足さない:最終の採決より後の発言'] == 2


def test_proposer_or_minister_is_not_added_as_question(tmp_path):
    from allocation_involvements import Cabinet
    inv = [row(氏名='甲', 行動='decide', 算入='はい')]
    cab = Cabinet([{'氏名': '乙', '区分': '閣僚', '役職': '国土交通大臣', '内閣名': '架空内閣', '就任日_西暦': '2017-01-01', '退任日_西暦': ''}])
    out, c = apply(inv, [res('甲', '支持'), res('乙', '支持'), res('丙', '支持')], votes_dir(tmp_path, {}), cabinet=cab)
    by = {(r['氏名'], r['行動']) for r in out}
    assert ('甲', 'question') not in by and ('乙', 'question') not in by and ('丙', 'question') in by
    assert c['足さない:提出者・政府側・委員長の発言'] == 2


def test_rerun_follows_corrected_stance(tmp_path):
    inv = [row(氏名='甲', 算入='いいえ', 除外理由='2系統の立場が一致しない（A:中立、B:支持。ADR 0007）')]
    vd = votes_dir(tmp_path, {})
    once, _ = apply(inv, [res('甲', '支持'), res('乙', '支持')], vd)
    again, _ = apply(once, [res('甲', '中立'), res('乙', '中立')], vd)
    by = {r['氏名']: r for r in again}
    assert len(again) == 2
    assert by['甲']['算入'] == 'いいえ' and by['乙']['算入'] == 'いいえ'
    same, _ = apply(again, [res('甲', '中立'), res('乙', '中立')], vd)
    assert same == again


def test_replaced_row_is_excluded_when_stance_disappears(tmp_path):
    inv = [row(氏名='甲', 算入='いいえ', 除外理由='2系統の立場が一致しない（A:中立、B:支持。ADR 0007）')]
    vd = votes_dir(tmp_path, {})
    once, _ = apply(inv, [res('甲', '支持')], vd)
    assert once[0]['算入'] == 'はい'
    again, _ = apply(once, [res('甲', '無関係')], vd)
    assert again[0]['算入'] == 'いいえ' and again[0]['除外理由'].startswith('読み直しで立場が決まらない')


def test_speech_on_another_bill_is_not_added(tmp_path):
    out, c = apply([row(氏名='甲', 算入='はい')], [res('乙', '支持')], votes_dir(tmp_path, {}),
                   on_bill=lambda law, name, url: False)
    assert '乙' not in {r['氏名'] for r in out} and c['足さない:別の法案の審議での発言'] == 1


def test_bill_checker_does_not_mistake_a_part_of_own_name_for_another_bill(tmp_path):
    import json
    from apply_resolved_stance import bill_checker
    sp = tmp_path / 'speeches'
    for law, kw in (('閣法-196-2', '国際観光旅客税法案'), ('閣法-196-4', '国際観光振興法')):
        (tmp_path / f'{law}.json').write_text(json.dumps({'id': law, 'keywords': [kw]}), encoding='utf-8')
        (sp / law).mkdir(parents=True)
    u = 'https://kokkai.ndl.go.jp/txt/119605254X01120180404/'
    talk = {'甲': '国際観光旅客税法案について伺います。', '乙': '国際観光振興法の改正について伺います。'}
    for law in ('閣法-196-2', '閣法-196-4'):
        for name, body in talk.items():
            (sp / law / f'x_{name}.txt').write_text(
                f'■ 2018-04-04 衆議院 本会議 第1号 発言番号1\nspeechURL: {u}{name}\n\n{body}\n', encoding='utf-8')
    ok = bill_checker(sp, [])
    # 「国際観光旅客税」の中の「国際観光」（閣法-196-4 の通称）を別の法案の名前と数えない。
    assert ok('閣法-196-2', '甲', u + '甲')
    assert not ok('閣法-196-4', '甲', u + '甲')
    assert ok('閣法-196-4', '乙', u + '乙')


def test_namesake_stance_is_not_used(tmp_path):
    # 人物台帳で同姓同名に分かれた名前は、読み直しが氏名で結ぶのでどちらの人の立場か分からず、置き換えも追加もしない。
    inv = [row(氏名='甲', 算入='いいえ', 除外理由='2系統の立場が一致しない（A:中立、B:支持。ADR 0007）')]
    out, c = apply(inv, [res('甲', '支持'), res('乙', '支持')], votes_dir(tmp_path, {}), split={'甲', '乙'})
    assert out == inv
    assert c['使わない:同姓同名で人物を決められない'] == 2
