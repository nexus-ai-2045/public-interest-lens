import { describe, expect, it } from 'vitest';
import { readViewState, serializeViewState } from './view-state';

describe('表示条件のURL復元', () => {
  it('履歴は既定で現在の条件、全履歴だけURLへ保存して往復する', () => {
    for (const search of ['', '?history=view', '?history=invalid']) {
      const state = readViewState(search, '2026-09-24');
      expect(state.history).toBe('view');
      expect(new URLSearchParams(serializeViewState(state)).has('history')).toBe(false);
    }
    const all = readViewState('?history=all', '2026-09-24');
    expect(all.history).toBe('all');
    expect(new URLSearchParams(serializeViewState(all)).get('history')).toBe('all');
    expect(readViewState(serializeViewState(all), all.options.asOf)).toEqual(all);
  });
  it('選択した根拠資料を別の根拠へ置き換えずURLで復元する', () => {
    const state = readViewState('?tab=evidence&evidence=e-action-a-vote', '2026-09-24');
    expect(state).toHaveProperty('selectedEvidenceId', 'e-action-a-vote');
    expect(readViewState(serializeViewState(state), state.options.asOf)).toHaveProperty('selectedEvidenceId', 'e-action-a-vote');
  });
  it('検索・選択・表示タブと非総合分野の重みも往復する', () => {
    const search = '?domain=technology&direction=benefit&period=8&q=架空&house=参議院&role=大臣&person=p&action=a&policy=s&assessment=outlook&tab=evidence&economy=12&technology=88';
    const state = readViewState(search, '2026-09-24');
    expect(state.selectedPolicyId).toBe('s');
    expect(state.tab).toBe('evidence');
    expect(state.options.weights).toEqual({ economy: 12, technology: 88 });
    const encoded = serializeViewState(state);
    expect(encoded.startsWith('?')).toBe(false);
    expect(readViewState(encoded, state.options.asOf)).toEqual(state);
  });
  it('不正な列挙値と非有限・範囲外の重みは初期値に戻す', () => {
    const state = readViewState('?domain=no&direction=no&period=3&house=no&role=no&assessment=no&tab=no&economy=Infinity&technology=-1', '2026-09-24');
    expect(state.options).toEqual({ domain: 'economy', direction: 'harm', period: 4, asOf: '2026-09-24', weights: { economy: 70, technology: 30 } });
    expect(state.house).toBe('all'); expect(state.roleClass).toBe('all');
    expect(state.assessment).toBe('actions'); expect(state.tab).toBe('actions');
    expect(readViewState('?economy=&technology=NaN', '2026-09-24').options.weights).toEqual({ economy: 70, technology: 30 });
  });
  it('文字列を2000文字に制限しゼロの重みと累積を保持する', () => {
    const state = readViewState(`?q=${'a'.repeat(2500)}&action=${'b'.repeat(2500)}&period=cumulative&economy=0&technology=100`, '2026-09-24');
    expect(state.query.length).toBe(2000); expect(state.selectedActionKey.length).toBe(2000);
    expect(state.options.period).toBe('cumulative'); expect(state.options.weights.economy).toBe(0);
  });
});
