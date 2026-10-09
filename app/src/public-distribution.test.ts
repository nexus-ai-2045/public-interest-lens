import { describe, expect, it } from 'vitest';
import { distributionCaseUrl, distributionEconomyUrl, parsePublicCase, type PublicCase } from './public-distribution';

const citation = { id: 'c1', title: '談話', url: 'https://www.fsa.go.jp/danwa/danwa/20050525-1.html', license: 'PDL1.0', locator: '第1項', quote: '不良債権比率は2.9％となった。' };
function sample(): PublicCase {
  return {
    schemaVersion: 'public-case/v1', snapshotId: 'a'.repeat(64), caseId: 'case', title: '金融再生プログラム', scoringStatus: 'held', impactScale: null, gdpLoss: null, responsibilityShare: null,
    holdReason: '影響の規模は保留です。', periodNote: '2002年から2005年の結果です。', observationFrom: '2002-10-30', observationTo: '2005-05-25',
    implementations: [{ id: 'i', date: '2002-10-30', text: '公表されました。' }],
    observations: [{ id: 'o', text: '比率の前後だけを確認しています。', method: 'before_after_not_causal' }],
    comparison: '対照群はありません。', counterEvidence: ['他の原因を分けられていません。'],
    actors: [
      { id: 'a', label: '竹中平蔵', date: '2002-11-29', action: '実施すると述べました。', identityNote: '英文談話の氏名です。', citationIds: ['c1'] },
      { id: 'b', label: '伊藤（副大臣）', date: '2002-10-30', action: '日程を説明しました。', identityNote: '名はページにありません。', citationIds: ['c1'] },
      { id: 'c', label: '岡本（室長）', date: '2002-12-19', action: '工程表の公表を説明しました。', identityNote: '名は議事録にありません。', citationIds: ['c1'] },
    ],
    organizations: [{ id: 'fsa', name: '金融庁', relation: '公表した機関です。' }],
    contextMentions: [{ id: 'm', label: '香西泰', basis: '名簿のみです。' }],
    missingMaterials: ['個人別の採決は未接続です。'],
    citations: [citation, { ...citation, id: 'c2', locator: '別の箇所' }, { ...citation, id: 'c3', locator: '利用ルール' }],
    statisticLink: { seriesId: 'real_gdp', relation: 'temporal_overlap_not_attribution', note: '時期が重なるだけです。' },
    causeCandidates: [{ id: 'npl', label: '不良債権。GDPの原因ではない。', status: 'unestablished' }],
  };
}

describe('公開配布版', () => {
  it('指定版と現在版のURLを混ぜません', () => {
    expect(distributionEconomyUrl('')).toBe('/distribution/economy.json');
    expect(distributionCaseUrl('ab'.repeat(32))).toBe(`/distribution/cases/${'ab'.repeat(32)}.json`);
    expect(() => distributionEconomyUrl('current')).toThrow();
  });
  it('点数や損失額を拒否します', () => {
    const scored = sample();
    (scored.actors[0] as PublicCase['actors'][number] & { score?: number }).score = 1;
    expect(() => parsePublicCase(JSON.stringify(scored))).toThrow();
    const priced = sample();
    priced.gdpLoss = 10 as unknown as null;
    expect(() => parsePublicCase(JSON.stringify(priced))).toThrow();
  });
});
