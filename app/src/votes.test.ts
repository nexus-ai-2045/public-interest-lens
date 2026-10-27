// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { BlocPanel, MemberSearch } from './VotesPage';
import { blocStance, blocSummary, fromYear, lawYear, noLawsByMember, parseVotes, type VoteLaw } from './votes';

const data = parseVotes(readFileSync(new URL('../public/distribution/votes.json', import.meta.url), 'utf8'));

describe('法律ごとの賛否データ', () => {
  it('新しい順で、最新は2026年の法律です', () => {
    expect(lawYear(data.laws[0])).toBeGreaterThanOrEqual(2026);
    const dates = data.laws.map(l => l.promulgated ?? '');
    expect([...dates].sort().reverse()).toEqual(dates);
  });
  it('期間で絞ると、その年以降の法律だけが残ります', () => {
    const recent = fromYear(data.laws, '2023');
    expect(recent.length).toBeGreaterThan(0);
    expect(recent.every(l => lawYear(l) >= 2023)).toBe(true);
  });
  it('系統ごとの衆院の賛成側・反対側と参院の票を数えます', () => {
    const law = data.laws.find(l => l.shu && l.shu.no.length > 0 && l.san?.groups)!;
    const opposing = law.shu!.no[0];
    const bloc = (['共産', '立憲', '維新', 'れいわ', '国民民主', '参政', '社民', '自民', '公明'] as const).find(b => blocStance(law, b).shu === 'no');
    expect(bloc, opposing).toBeDefined();
    const s = blocSummary(data.laws, bloc!);
    expect(s.shuNo).toBeGreaterThan(0);
    expect(s.shuYes + s.shuNo).toBeGreaterThan(0);
  });
  it('議員ごとの反対した法律の数は、名簿の反対数と一致します', () => {
    const by = noLawsByMember(data.laws, data.members.length);
    data.members.forEach((m, i) => expect(by[i].length).toBe(m.no));
  });
  it('形式が不正なら読み込みません', () => {
    expect(() => parseVotes('{"schema":"x"}')).toThrow();
    expect(() => parseVotes(JSON.stringify({ schema: 'public-votes/v1', notes: [], counts: {}, members: [], laws: [{ id: 'a', title: 'b', san: { no: [3], url: 'https://x', method: 'ballot' }, shu: null }] }))).toThrow();
  });
});

describe('直近4年と自民との一致', () => {
  it('直近4年は最新の日付から4年前までです', async () => {
    const { recentCutoff } = await import('./votes');
    const cut = recentCutoff(data.laws);
    const recent = fromYear(data.laws, 'recent4');
    expect(recent.length).toBeGreaterThan(0);
    expect(recent.length).toBeLessThan(data.laws.length);
    expect(recent.every(l => (l.promulgated ?? l.shu?.date ?? l.san?.date ?? '') > cut)).toBe(true);
  });
  it('自民と同じ側だった数は、衆院に会派の記載がある法律の範囲に収まります', () => {
    const s = blocSummary(data.laws, '公明');
    expect(s.withLdpLaws).toBeGreaterThan(0);
    expect(s.withLdpSame).toBeLessThanOrEqual(s.withLdpLaws);
    expect(s.withLdpSame / s.withLdpLaws).toBeGreaterThan(0.5);
  });
});


const fixtureLaw = (id: string, date: string | null, yes: string[], no: string[] = []): VoteLaw => ({
  id, title: id, kind: '法律', session: 1, proposer: '', promulgated: date,
  url: 'https://example.test/law', shu: { date: null, yes, no }, san: null,
});

describe('比較可能な賛否と表示期間の回帰', () => {
  it('双方の賛否が一意な法律だけを一致率の分母にし、記載なしと割れを除きます', () => {
    const laws = [
      fixtureLaw('same-yes', null, ['自由民主党', '公明党']),
      fixtureLaw('same-no', null, [], ['自由民主党', '公明党']),
      fixtureLaw('different', null, ['自由民主党'], ['公明党']),
      fixtureLaw('target-missing', null, ['自由民主党']),
      fixtureLaw('target-split', null, ['自由民主党', '公明党'], ['公明党']),
      fixtureLaw('ldp-missing', null, ['公明党']),
      fixtureLaw('ldp-split', null, ['自由民主党', '公明党'], ['自由民主党']),
    ];
    expect(blocSummary(laws, '公明')).toMatchObject({
      shuLaws: 6, withLdpSame: 2, withLdpLaws: 3, withLdpExcluded: 4,
    });
  });
  it('比較できる法律が0本なら0%とせず、比較できない旨と除外数を出します', () => {
    const laws = [fixtureLaw('missing', null, ['自由民主党'])];
    const html = renderToStaticMarkup(createElement(BlocPanel, { laws, bloc: '公明' }));
    expect(html).toContain('比較できる法律はありません');
    expect(html).toContain('除外 1本');
    expect(html).not.toContain('0%');
  });
  it('最新日を基準とし4年前の同日は除外し、翌日と最新日は含めます', async () => {
    const { recentCutoff } = await import('./votes');
    const laws = [
      fixtureLaw('before', '2022-10-26', []),
      fixtureLaw('boundary', '2022-10-27', []),
      fixtureLaw('after', '2022-10-28', []),
      fixtureLaw('latest', '2026-10-27', []),
      fixtureLaw('undated', null, []),
    ];
    expect(recentCutoff(laws)).toBe('2022-10-27');
    expect(fromYear(laws, 'recent4').map(l => l.id)).toEqual(['after', 'latest']);
    expect(fromYear([], 'recent4')).toEqual([]);
  });
  it('公布日がなければ衆院、次に参院の日付を使います', async () => {
    const { recentCutoff } = await import('./votes');
    const law = fixtureLaw('fallback', null, []);
    law.shu.date = '2024-04-01';
    law.san = { url: 'https://example.test/vote', method: 'ballot', date: '2025-04-01' };
    expect(recentCutoff([law])).toBe('2020-04-01');
    law.shu.date = null;
    expect(recentCutoff([law])).toBe('2021-04-01');
  });
  it('議員の賛否総数と初期表示順を全期間と明記し、選択期間の反対法数を別に出します', () => {
    const law = fixtureLaw('selected', '2026-01-01', []);
    law.san = { url: 'https://example.test/vote', method: 'ballot', date: '2026-01-01', no: [0] };
    const fixture = { schema: 'public-votes/v1', notes: [], counts: {}, laws: [law],
      members: [{ name: '架空議員', group: '架空会派', yes: 10, no: 2, absent: 3, last: '' }] };
    const html = renderToStaticMarkup(createElement(MemberSearch, { data: fixture, laws: [] }));
    expect(html).toContain('全期間の反対票が多い順');
    expect(html).toContain('全期間：賛成 10・反対 2・欠席 3');
    expect(html).toContain('選択期間の反対法数 0本');
  });
});
