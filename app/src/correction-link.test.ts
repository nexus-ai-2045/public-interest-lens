import { expect, it } from 'vitest';
import { correctionIssueUrl, correctionListUrl, correctionMailUrl } from './correction-link';
import { memberCorrectionTarget } from './MembersPage';
import type { PublicMember, PublicMemberLaw } from './members-build';

it('対象と画面の出典を Issue テンプレートの欄に入れる', () => {
  const url = new URL(correctionIssueUrl({ title: '旅館業法改正（閣法-1-1）', page: '/ranking#%E9%96%A3', sources: [{ label: '議案情報', url: 'https://www.shugiin.go.jp/a' }, { label: '重複', url: 'https://www.shugiin.go.jp/a' }] }));
  expect(url.pathname).toBe('/nexus-ai-2045/public-interest-lens/issues/new');
  expect(url.searchParams.get('template')).toBe('correction.yml');
  expect(url.searchParams.get('title')).toBe('[訂正] 旅館業法改正（閣法-1-1）');
  expect(url.searchParams.get('target')).toBe('旅館業法改正（閣法-1-1）（https://kokuzoku.nexusai2045.com/ranking#%E9%96%A3）');
  expect(url.searchParams.get('cited')).toBe('- 議案情報：https://www.shugiin.go.jp/a');
});

it('出典が多すぎる時は URL が長くなりすぎないよう減らし、残りの件数を書く', () => {
  const sources = Array.from({ length: 40 }, (_, i) => ({ label: `出典${i}`.repeat(30), url: `https://kokkai.ndl.go.jp/${'x'.repeat(200)}${i}` }));
  const url = correctionIssueUrl({ title: '甲', page: '/members', sources });
  expect(url.length).toBeLessThanOrEqual(7000);
  expect(new URL(url).searchParams.get('cited')).toMatch(/ほか\d+件は画面を参照$/);
});

it('出典が無い時もそう書いて開く', () => {
  expect(new URL(correctionIssueUrl({ title: '乙', page: '/members', sources: [] })).searchParams.get('cited')).toBe('（この画面に出典の記載なし）');
});

it('議員の欄は、行動（額に入れていないものも）の一次資料・投票結果・議案情報を順に入れる', () => {
  const law = { id: 'L1', title: '法A', source: 'https://www.shugiin.go.jp/L1', game: { voteUrl: 'https://www.sangiin.go.jp/v1' } } as unknown as PublicMemberLaw;
  const member = { id: '丙', name: '丙', laws: [{ lawId: 'L1', evidence: [{ actionLabel: '提出', date: '2013-11-20', url: 'https://kokkai.ndl.go.jp/1' }], context: [{ actionLabel: '質疑', date: '2013-11-21', url: 'https://kokkai.ndl.go.jp/2' }] }] } as unknown as PublicMember;
  const t = memberCorrectionTarget(member, new Map([['L1', law]]));
  expect(t.page).toBe(`/members?name=${encodeURIComponent('丙')}`);
  expect(t.sources.map(s => s.url)).toEqual(['https://kokkai.ndl.go.jp/1', 'https://kokkai.ndl.go.jp/2', 'https://www.sangiin.go.jp/v1', 'https://www.shugiin.go.jp/L1']);
  expect(t.sources[0].label).toBe('法A・提出（2013-11-20）');
});

it('寄せられた反論・訂正の一覧は、ラベルと題名で絞った GitHub の検索を開く', () => {
  const url = new URL(correctionListUrl('法"A'));
  expect(url.searchParams.get('q')).toBe('is:issue label:correction in:title "法A"');
});

it('メールの下書きは件名と本文に対象と出典を入れ、長すぎる時は出典を減らす', () => {
  const url = correctionMailUrl({ title: '丁', page: '/members?name=%E4%B8%81', sources: [{ label: '会議録', url: 'https://kokkai.ndl.go.jp/1' }] }, 'box@example.org');
  expect(url.startsWith('mailto:box@example.org?subject=')).toBe(true);
  const body = decodeURIComponent(url.split('&body=')[1]);
  expect(decodeURIComponent(url.split('subject=')[1].split('&')[0])).toBe('[訂正] 丁');
  expect(body).toContain('対象：丁（https://kokuzoku.nexusai2045.com/members?name=%E4%B8%81）');
  expect(body).toContain('- 会議録：https://kokkai.ndl.go.jp/1');
  const many = Array.from({ length: 30 }, (_, i) => ({ label: `出典${i}`, url: `https://kokkai.ndl.go.jp/${'y'.repeat(60)}${i}` }));
  const long = correctionMailUrl({ title: '丁', page: '/members', sources: many }, 'box@example.org');
  expect(long.length).toBeLessThanOrEqual(1900);
  expect(decodeURIComponent(long.split('&body=')[1])).toMatch(/ほか\d+件は画面を参照/);
});
