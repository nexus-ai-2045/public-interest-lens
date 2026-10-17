import { describe, expect, it } from 'vitest';
import type { Classification } from './benefit-classification';
import type { LawResult } from './impact-batch';
import {
  adoptAgreed, agreementRow, compareBenefitLines, compareTriage, HELD_BY_TRIAGE, holdByTriage, parseBenefitLine2, triageAgreementRow,
} from './line-agreement';

// すべて人工のデータです。実在の法律ではありません。
const pick = (kinds: string[], directionConflict = false) => ({ kinds, quotes: [], directionConflict });
const cls = (a: string[], b: string[] | null, opts: { aConflict?: boolean; bConflict?: boolean } = {}): Classification => {
  const sameSet = b !== null && a.length === b.length && [...a].sort().every((v, i) => v === [...b].sort()[i]);
  const agreed = sameSet;
  const conflictAgreed = (opts.aConflict ?? false) === (opts.bConflict ?? false);
  return {
    texts: [{ targetId: 't', lawName: '人工法', version: '施行時', text: '（目的）第一条 人工', url: '' }], flags: [],
    a: pick(a, opts.aConflict), b: b === null ? null : { ...pick(b, opts.bConflict), note: '' },
    agreed, kinds: agreed ? [...a].sort() : null, directionConflict: agreed && conflictAgreed && (opts.aConflict ?? false),
    holdReason: !agreed ? '2系統の種類が一致しない' : !a.length ? '第1条に便益にあたる目的の記述が無い' : conflictAgreed ? null : '向きの矛盾の判定が2系統で一致しない',
  };
};

describe('目的の分類：系統1と系統2の比較（設計決定0007）', () => {
  it('labels.csv の行を読む（「・」区切り、空は目的の記述なし、「抑える」だけが向きの矛盾）', () => {
    const m = parseBenefitLine2([
      { id: 'x', 系統2_種類: '経済（内包）・移転', 系統2_向きの矛盾: 'なし' },
      { id: 'y', 系統2_種類: '', 系統2_向きの矛盾: '抑える' },
    ]);
    expect(m.get('x')).toEqual({ kinds: ['経済（内包）', '移転'], directionConflict: false });
    expect(m.get('y')).toEqual({ kinds: [], directionConflict: true });
  });

  it('種類の集合（順序は問わない）と向きの矛盾が同じなら一致で、系統1の分類をそのまま採用する', () => {
    const c = cls(['経済（内包）', '消費者保護'], ['消費者保護', '経済（内包）']);
    const ag = compareBenefitLines(c, { kinds: ['消費者保護', '経済（内包）'], directionConflict: false });
    expect(ag.status).toBe('一致');
    expect(adoptAgreed(c, ag)).toBe(c);
    expect(agreementRow('x', '人工法案', ag).slice(-2)).toEqual(['採用', '系統1と系統2が一致']);
  });

  it('種類が1つでも違えば不一致で、系統1が採用した種類も保留に替える', () => {
    const c = cls(['経済（内包）'], ['経済（内包）']);
    const ag = compareBenefitLines(c, { kinds: ['経済（内包）', '移転'], directionConflict: false });
    expect(ag.status).toBe('不一致');
    expect(ag.kindsMatch).toBe(false);
    const adopted = adoptAgreed(c, ag);
    expect(adopted.kinds).toBeNull();
    expect(adopted.directionConflict).toBe(false);
    expect(adopted.holdReason).toContain('2系統（設計決定0007）が一致しない');
    expect(adopted.holdReason).toContain('系統2：移転・経済（内包）');
  });

  it('種類が同じでも向きの矛盾が違えば不一致で保留', () => {
    const c = cls(['経済（内包）'], ['経済（内包）'], { aConflict: true, bConflict: true });
    const ag = compareBenefitLines(c, { kinds: ['経済（内包）'], directionConflict: false });
    expect(ag.kindsMatch).toBe(true);
    expect(ag.conflictMatch).toBe(false);
    expect(adoptAgreed(c, ag).kinds).toBeNull();
  });

  it('目的の記述なし（空集合）どうしも一致として比べる。採用は空のままで、便益の判定は従来どおり保留になる', () => {
    const c = cls([], []);
    const ag = compareBenefitLines(c, { kinds: [], directionConflict: false });
    expect(ag.status).toBe('一致');
    expect(adoptAgreed(c, ag).kinds).toEqual([]);
  });

  it('系統1が保留なら、系統2が付いていても保留のまま（系統2で埋めない）', () => {
    const c = cls(['経済（内包）', '消費者保護'], ['経済（内包）']);
    const ag = compareBenefitLines(c, { kinds: ['経済（内包）', '消費者保護'], directionConflict: false });
    expect(ag.status).toBe('系統1が保留');
    expect(adoptAgreed(c, ag).kinds).toBeNull();
    expect(agreementRow('x', '人工法案', ag)[8]).toBe('保留');
  });

  it('系統2が無い法律は保留', () => {
    const c = cls(['経済（内包）'], ['経済（内包）']);
    const ag = compareBenefitLines(c, undefined);
    expect(ag.status).toBe('系統2なし');
    expect(adoptAgreed(c, ag).kinds).toBeNull();
  });
});

describe('振り分け：系統1と系統2の比較（設計決定0007）', () => {
  const l1 = { id: 'x', 結果: '評価対象', 分野: '金融', 指標: '貸出残高' };
  const l2 = { id: 'x', 系統2_判定: '評価対象', 系統2_分野: '金融', 系統2_指標: '貸出残高' };
  const law: LawResult = {
    id: 'x', title: '人工法案', field: '金融', indicator: '貸出残高', start: '2005-04-01',
    series: '人工', verdict: '段階2', direction: '貢献', effect: 1, spread: 0.1, cross: '段階1・貢献（比較国3か国、条件を満たした国2）', reason: '国内：人工',
  };

  it('判定・分野・指標がすべて同じときだけ一致で、impact-v1 の行はそのまま', () => {
    const ag = compareTriage('x', l1, l2);
    expect(ag.agreed).toBe(true);
    expect(holdByTriage(law, ag)).toBe(law);
    expect(triageAgreementRow('人工法案', ag)[8]).toBe('採用');
  });

  it('指標だけが違っても不一致で、段階・向きを採用せず保留にする（計算結果は理由欄に参考として残す）', () => {
    const ag = compareTriage('x', l1, { ...l2, 系統2_指標: '企業倒産件数' });
    expect(ag.agreed).toBe(false);
    expect(ag.reason).toContain('指標（系統1：貸出残高、系統2：企業倒産件数）');
    const held = holdByTriage(law, ag);
    expect(held.verdict).toBe(HELD_BY_TRIAGE);
    expect(held.direction).toBe('');
    expect(held.cross).toContain('保留（参考：段階1・貢献');
    expect(held.reason).toContain('参考：系統1の分野・指標での判定は段階2・貢献');
    // loss-batch は「段階N」の行だけを拾うので、保留にした行は損失額・公開の判定に進まない。
    expect(/^段階[123]$/.test(held.verdict)).toBe(false);
  });

  it('判定が違えば（系統2が評価対象外）不一致', () => {
    const ag = compareTriage('x', l1, { ...l2, 系統2_判定: '評価対象外', 系統2_分野: '対応表なし', 系統2_指標: '' });
    expect(ag.agreed).toBe(false);
    expect(ag.reason).toContain('判定（系統1：評価対象、系統2：評価対象外）');
    expect(ag.reason).toContain('指標（系統1：貸出残高、系統2：なし）');
  });

  it('両系統が保留でも採用しない', () => {
    const ag = compareTriage('x', { ...l1, 結果: '保留' }, { ...l2, 系統2_判定: '保留' });
    expect(ag.agreed).toBe(false);
    expect(holdByTriage(law, ag).verdict).toBe(HELD_BY_TRIAGE);
  });

  it('どちらかの系統が無ければ不一致（保留）', () => {
    expect(compareTriage('x', l1, undefined).agreed).toBe(false);
    expect(compareTriage('x', undefined, l2).reason).toBe('系統1の振り分けが無い');
  });

  it('系統2で参考計算した保留行は、系統1の計算と表示しない', () => {
    const held = holdByTriage(law, compareTriage('x', undefined, l2), '系統2');
    expect(held.reason).toContain('参考：系統2の分野・指標での判定');
    expect(held.reason).not.toContain('参考：系統1');
    expect(held.verdict).toBe(HELD_BY_TRIAGE);
  });

  it('両系統が欠落した行は参考計算の入力なしと表示する', () => {
    const held = holdByTriage(law, compareTriage('x', undefined, undefined), '入力');
    expect(held.reason).toContain('参考計算なし：両系統の分野・指標が無い');
    expect(held.reason).not.toContain('入力の分野・指標での判定');
  });
});
