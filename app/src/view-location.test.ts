import { describe, expect, it } from 'vitest';
import { rankingDataset } from './ranking-data';
import { actionKey, rankPeople } from './ranking';
import { readViewState } from './view-state';
import { readViewLocation, serializeViewLocation, viewDataVersion } from './view-location';
import { actionRevision, sha256 } from './evidence-evaluation';
import { RANKING_CONTENT_SHA256, rankingSnapshotContent, serializeRankingSnapshot } from './ranking-snapshot';

const data = rankingDataset;
const read = (url: string, fixture = data) => {
  const parsed = new URL(url, 'https://example.test');
  return readViewLocation(parsed.pathname, parsed.search, fixture.asOf, fixture);
};
describe('短い表示URL契約', () => {
  it('既定は順位ページだけで、先頭人物をURLへ昇格させない', () => {
    const initial = read('/ranking');
    expect(initial.invalid).toBeNull();
    expect(initial.page).toBe('ranking');
    expect(initial.state.selectedPersonId).toBe('fiction-a');
    expect(serializeViewLocation(initial.state, data, initial.page)).toBe('/ranking');
  });
  it('説明文を含む旧URLを明示IDへ移行する', () => {
    const params = new URLSearchParams({ person: 'fiction-a', action: actionKey(data.involvements[1]), policy: 'policy-harm-e', evidence: 'e-action-a-vote' });
    const restored = read(`/?${params}`);
    expect(restored.invalid).toBeNull();
    const url = serializeViewLocation(restored.state, data, restored.page);
    expect(url).toBe('/actions/fiction-a-vote?evidence=e-action-a-vote');
    expect(read(url).state.selectedActionKey).toBe(actionKey(data.involvements[1]));
  });
  it('説明・引用の訂正後も明示IDのURLが同じ行動へ戻る', () => {
    const updated = structuredClone(data);
    updated.involvements[0].description = '訂正後の説明';
    const restored = read('/actions/fiction-a-bill', updated);
    expect(restored.invalid).toBeNull();
    expect(restored.state.selectedActionKey).toBe(actionKey(updated.involvements[0]));
    expect(serializeViewLocation({ ...restored.state, selectedEvidenceId: '' }, updated, 'action')).toBe('/actions/fiction-a-bill');
  });
  it('総合の全重み0・非既定条件を保持する', () => {
    const restored = read('/ranking?domain=overall&view=benefit&years=8&economy=0&technology=0&assessment=outlook&history=all&tab=policy');
    expect(restored.state.options.weights).toEqual({ economy: 0, technology: 0 });
    const url = serializeViewLocation(restored.state, data, 'ranking');
    expect(read(url).state).toEqual(restored.state);
    expect(url).not.toContain('person=');
    expect(url).not.toContain('direction=');
  });
  it('分野別表示には結果に使わない重み・一時検索を入れない', () => {
    const state = readViewState('?economy=0&technology=0&q=検索', data.asOf);
    expect(serializeViewLocation(state, data, 'ranking')).toBe('/ranking');
  });
  it('条件外の明示行動と旧リンクは全履歴で復元する', () => {
    for (const url of ['/actions/fiction-b-decision', `/?person=fiction-b&action=${encodeURIComponent(actionKey(data.involvements[2]))}`]) {
      const restored = read(url);
      expect(restored.invalid).toBeNull();
      expect(restored.state.history).toBe('all');
      expect(restored.state.selectedPersonId).toBe('fiction-b');
    }
  });
  it('人物・行動・根拠・版が不明な場合は代替対象を開かない', () => {
    for (const url of ['/people/missing', '/actions/missing', '/ranking?version=missing', '/actions/fiction-a-bill?evidence=e-action-b', '/missing']) {
      expect(read(url).invalid).not.toBeNull();
    }
  });
  it('重複IDとID未採用の行動を拒否するが旧データの採点は許す', () => {
    const duplicate = structuredClone(data);
    duplicate.involvements[1].id = duplicate.involvements[0].id;
    expect(read('/actions/fiction-a-bill', duplicate).invalid).not.toBeNull();
    expect(() => serializeViewLocation(readViewState(`?person=fiction-a&action=${encodeURIComponent(actionKey(duplicate.involvements[0]))}`, data.asOf), duplicate, 'action')).toThrow('行動ID');
    const legacy = structuredClone(data);
    delete legacy.involvements[0].id;
    const state = readViewState(`?person=fiction-a&action=${encodeURIComponent(actionKey(legacy.involvements[0]))}`, data.asOf);
    expect(() => rankPeople(legacy, state.options)).not.toThrow();
    expect(read(`/?person=fiction-a&action=${encodeURIComponent(state.selectedActionKey)}`, legacy).invalid).not.toBeNull();
    expect(() => serializeViewLocation(state, legacy, 'action')).toThrow('行動ID');
  });
  it('共有時のみ既知の評価版を固定する', () => {
    const initial = read('/ranking');
    const pinned = serializeViewLocation(initial.state, data, 'ranking', viewDataVersion(data));
    expect(read(pinned).invalid).toBeNull();
    expect(pinned).toContain('version=');
    expect(() => serializeViewLocation(initial.state, data, 'ranking', 'unknown')).toThrow('評価版');
  });
  it('基準日が同じでも政策本文が違う版へ固定リンクを流用しない', () => {
    const original = viewDataVersion(data);
    const changed = structuredClone(data);
    changed.policies[0].impact = 1;
    expect(changed.asOf).toBe(data.asOf);
    expect(() => viewDataVersion(changed)).toThrow('データ内容');
    expect(read(`/ranking?version=${encodeURIComponent(original)}`, changed).invalid).not.toBeNull();
    expect(() => serializeViewLocation(read('/ranking', changed).state, changed, 'ranking', original)).toThrow('データ内容');
    expect(viewDataVersion(structuredClone(data))).toBe(original);
  });
  it('登録ハッシュを全データと算定契約から既存のハッシュ処理で検証する', async () => {
    const content = rankingSnapshotContent(data);
    expect(await actionRevision(content)).toBe(RANKING_CONTENT_SHA256);
    expect(await sha256(serializeRankingSnapshot(content))).toBe(RANKING_CONTENT_SHA256);
    expect(viewDataVersion(data)).toContain(RANKING_CONTENT_SHA256);
  });
  it('登録正本の後続mutationも固定リンクを拒否する', () => {
    const saved = data.coverage.scope;
    try {
      data.coverage.scope = '後続の書き換え';
      expect(() => viewDataVersion(data)).toThrow('データ内容');
    } finally { data.coverage.scope = saved; }
  });
});
