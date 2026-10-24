import { describe, expect, it } from 'vitest';
import type { Classification } from './benefit-classification';
import type { LawResult } from './impact-batch';
import {
  adoptAgreed, agreementRow, compareBenefitLines, compareTriage, HELD_BY_TRIAGE, holdByTriage, parseBenefitLine2, resolveTriageDiff, triageAgreementRow,
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

  it('第3の判定者（TB2）が選んだ系統を採る。新しい値は作らず、選んだ系統が保留や保留を選んだときは採らない（v2 だけ）', () => {
    const l2out = { ...l2, 系統2_判定: '評価対象外', 系統2_分野: '金融', 系統2_指標: '貸出残高' };
    const tb = (採用: string) => ({ id: 'x', 採用, 決め方: '一致', 理由: '期限の延長だけ' });
    const two = compareTriage('x', l1, l2out, '人工法案', tb('系統2'));
    expect(two).toMatchObject({ agreed: true, rule: 'TB2', resolved: { verdict: '評価対象外', field: '金融' } });
    expect(two.reason).toContain('TB2：第3の判定者が系統2を採った（一致：期限の延長だけ）');
    expect(compareTriage('x', l1, l2out, '人工法案', tb('系統1')).resolved).toMatchObject({ verdict: '評価対象', indicator: '貸出残高' });
    expect(compareTriage('x', l1, l2out, '人工法案', tb('保留')).agreed).toBe(false);
    // 題名を渡さない v1 では当てない
    expect(compareTriage('x', l1, l2out, undefined, tb('系統2')).agreed).toBe(false);
    // 片方が保留：定義済みの系統を選べば採り、保留の系統を選べば採らない
    const held = { ...l1, 結果: '保留' };
    expect(compareTriage('x', held, l2out, '人工法案', tb('系統2'))).toMatchObject({ agreed: true, rule: 'TB2' });
    expect(compareTriage('x', held, l2out, '人工法案', tb('系統1')).agreed).toBe(false);
    // 2つの判定が一致していない決定（Sonnet・Opus の単独の決定）は採らない
    for (const how of ['Sonnetが決定', 'Opusが修正']) {
      expect(compareTriage('x', l1, l2out, '人工法案', { ...tb('系統2'), 決め方: how }).agreed).toBe(false);
    }
  });

  it('両系統が保留でも採用しない', () => {
    const ag = compareTriage('x', { ...l1, 結果: '保留' }, { ...l2, 系統2_判定: '保留' });
    expect(ag.agreed).toBe(false);
    expect(holdByTriage(law, ag).verdict).toBe(HELD_BY_TRIAGE);
  });

  it('新分野（field-expansion-v1）の法律で系統2の行がまだ無ければ、系統1が評価対象でも保留にする（新しい法律は系統2のラベル付けまで入らない）', () => {
    const newLaw: LawResult = { ...law, field: '建設', indicator: '建設業の付加価値' };
    const line1 = { id: 'x', 結果: '評価対象', 分野: '建設', 指標: '建設業の付加価値' };
    const ag = compareTriage('x', line1, undefined);
    expect(ag).toMatchObject({ agreed: false, reason: '系統2の振り分けが無い' });
    expect(holdByTriage(newLaw, ag).verdict).toBe(HELD_BY_TRIAGE);
    // 系統2が同じ新分野・同じ指標に決めれば一致する
    expect(compareTriage('x', line1, { id: 'x', 系統2_判定: '評価対象', 系統2_分野: '建設', 系統2_指標: '建設業の付加価値' }).agreed).toBe(true);
    // 直接と代理で指標が違えば不一致
    expect(compareTriage('x', line1, { id: 'x', 系統2_判定: '評価対象', 系統2_分野: '建設', 系統2_指標: '建設業の付加価値（代理）' }).agreed).toBe(false);
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

describe('振り分けの保留の解消（v2.1：HR3・HR4）', () => {
  const l = (verdict: string, field: string, indicator: string, kind = '新規') => ({ verdict, field, indicator, kind });
  const row1 = (x: ReturnType<typeof l>, rules = '') => ({ id: 'x', 結果: x.verdict, 分野: x.field, 指標: x.indicator, 種類: x.kind, 理由: '', 規則: rules });
  const row2 = (x: ReturnType<typeof l>, rules = '') => ({ id: 'x', 系統2_判定: x.verdict, 系統2_分野: x.field, 系統2_指標: x.indicator, 系統2_種類: x.kind, 系統2_理由: '', 系統2_規則: rules });

  it('HR3：同じ分野で指標だけ違えば、分野の表の上の行の指標を固定の優先順で採る', () => {
    const r = resolveTriageDiff('預金保険法案', l('評価対象', '金融', '貸出残高'), l('評価対象', '金融', '不良債権比率'));
    expect(r).toMatchObject({ rule: 'HR3', line: { indicator: '不良債権比率' } });
    expect(resolveTriageDiff('x', l('評価対象', '金融', '貸出残高'), l('評価対象', '金融', '企業倒産件数'))).toMatchObject({ rule: 'HR3', line: { indicator: '企業倒産件数' } });
    expect(resolveTriageDiff('x', l('評価対象', '金融', '貸出残高'), l('評価対象外', '金融', '不良債権比率')).rule).toBe('');
    expect(resolveTriageDiff('x', l('評価対象', '金融', '未知の指標'), l('評価対象', '金融', '貸出残高')).rule).toBe('');
  });

  it('HR4：片方が対応表なしで、題名に分野の直接の語があり種類が同じときだけ分野を採る', () => {
    expect(resolveTriageDiff('銀行法案', l('評価対象外', '対応表なし', ''), l('評価対象', '金融', '貸出残高')))
      .toMatchObject({ rule: 'HR4', line: { field: '金融', indicator: '金融・保険業の付加価値', verdict: '評価対象' } });
    expect(resolveTriageDiff('銀行法案', l('評価対象外', '対応表なし', '', '定型改正'), l('評価対象', '金融', '貸出残高')).rule).toBe('');
    const none = resolveTriageDiff('ほげ法案', l('評価対象外', '対応表なし', ''), l('評価対象', '金融', '貸出残高'));
    expect(none.rule).toBe('');
    expect(none.reason).toContain('直接の語が無い');
  });

  it('保留が混じる、別々の分野は解消しない', () => {
    expect(resolveTriageDiff('x', l('保留', '', ''), l('評価対象', '金融', '貸出残高')).rule).toBe('');
    expect(resolveTriageDiff('x', l('評価対象', '金融', '貸出残高'), l('評価対象', '労働市場', '賃金')).rule).toBe('');
  });

  it('compareTriage は title を渡したときだけ解消し、規則・区分・採用した振り分けを残す。渡さなければ従来どおり保留', () => {
    const a = l('評価対象', '金融', '貸出残高'), b = l('評価対象', '金融', '不良債権比率');
    expect(compareTriage('x', row1(a), row2(b)).agreed).toBe(false);
    const ag = compareTriage('x', row1(a), row2(b), '預金保険法案');
    expect(ag).toMatchObject({ agreed: true, rule: 'HR3', category: '同じ分野で指標の食い違い', resolved: { indicator: '不良債権比率' } });
    expect(triageAgreementRow('預金保険法案', ag).slice(8)).toEqual(['採用', ag.reason, 'HR3', '同じ分野で指標の食い違い']);
  });

  it('各系統の中で HR1・HR2 を使って一致した行は、規則と解消前の区分を残す', () => {
    const a = l('評価対象', '通信・ネット', 'ネット企業の時価総額');
    const ag = compareTriage('x', row1(a, 'HR1／D1／通信・ネットC2'), row2(a, 'HR1／D1／通信・ネットC2'), '電子商取引法案');
    expect(ag).toMatchObject({ agreed: true, rule: 'HR1', category: '同位置の分野競合（D5）' });
    expect(ag.reason).toContain('解消前は保留または食い違い');
  });

  it('解消できない食い違いは、区分と具体的な理由を残して保留のまま', () => {
    const ag = compareTriage('x', row1(l('評価対象', '金融', '貸出残高')), row2(l('評価対象', '労働市場', '賃金')), 'x');
    expect(ag).toMatchObject({ agreed: false, category: '別々の分野の食い違い' });
    expect(ag.reason).toContain('v2.1の解消規則（HR3・HR4）に当たらない');
  });
});
