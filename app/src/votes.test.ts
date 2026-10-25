// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { blocStance, blocSummary, fromYear, lawYear, noLawsByMember, parseVotes } from './votes';

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
