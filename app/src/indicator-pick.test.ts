import { describe, expect, it } from 'vitest';
import { FIELDS, FIELD_WORDS, NEW_FIELDS, NEW_FIELD_WORDS, PROXY_SUFFIX, PICK_TABLES, firstLawTitle, newIndicator, pickIndicator, resolveTie, triageV2 } from './indicator-pick';

// 提案 docs/提案/指標の選び方-v1.md の 4-1（指標の選び方の食い違い22本）と 4-2（評価対象の食い違い6本）の表をそのまま期待値にする。
const PICK_CASES: [string, string, string, string][] = [
  // [題名, 分野, 期待する指標, 当たる行]
  ['電子計算機を使用して作成する国税関係帳簿書類の保存方法等の特例に関する法律案', '行政のデジタル化', '電子申請率', '行政のデジタル化E1'],
  ['地方公共団体情報システムの標準化に関する法律案', '行政のデジタル化', '電子申請率', '行政のデジタル化E1'],
  ['デジタル社会の形成を図るための規制改革を推進するためのデジタル社会形成基本法等の一部を改正する法律案', '行政のデジタル化', '電子申請率', '行政のデジタル化E1'],
  ['介護労働者の雇用管理の改善等に関する法律の一部を改正する法律案', '労働市場', '雇用の流動性', '労働市場既定'],
  ['労働組合法の一部を改正する法律案', '労働市場', '雇用の流動性', '労働市場既定'],
  ['労働安全衛生法等の一部を改正する法律案', '労働市場', '労働生産性', '労働市場L2'],
  ['短時間労働者の雇用管理の改善等に関する法律の一部を改正する法律案', '労働市場', '雇用の流動性', '労働市場既定'],
  ['職業訓練の実施等による特定求職者の就職の支援に関する法律案', '労働市場', '雇用の流動性', '労働市場L3'],
  ['過労死等防止対策推進法案', '労働市場', '労働生産性', '労働市場L2'],
  ['労働者の職務に応じた待遇の確保等のための施策の推進に関する法律案', '労働市場', '賃金', '労働市場L1'],
  ['全国新幹線鉄道整備法の一部を改正する法律案', '交通・移動', '利用件数', '交通・移動T3'],
  ['空港整備法の一部を改正する法律案', '交通・移動', '利用件数', '交通・移動T3'],
  ['貨物自動車運送事業法の一部を改正する法律案', '交通・移動', '旅客輸送の付加価値', '交通・移動T2'],
  ['海上運送法等の一部を改正する法律案', '交通・移動', '旅客輸送の付加価値', '交通・移動T2'],
  ['貨物自動車運送事業の適正化のための体制の整備等の推進に関する法律案', '交通・移動', '旅客輸送の付加価値', '交通・移動T2'], // 「整備」(T3) より上の行 T2 が先
  ['金融機関等の組織再編成の促進に関する特別措置法案', '金融', '金融・保険業の付加価値', '金融既定'],
  ['株式会社日本政策金融公庫法案', '金融', '貸出残高', '金融F3'],
  ['株式会社商工組合中央金庫法及び中小企業信用保険法の一部を改正する法律案', '金融', '企業倒産件数', '金融F2'],
  ['特定高度情報通信技術活用システムの開発供給及び導入の促進に関する法律案', '通信・ネット', 'ブロードバンド普及率', '通信・ネットC1'],
  ['脱炭素成長型経済構造への円滑な移行のための低炭素水素等の供給及び利用の促進に関する法律案', 'エネルギー', '発電構成', 'エネルギーG2'],
];

describe('pickIndicator：分野の表を上から順に見て、最初に当たった行', () => {
  it.each(PICK_CASES)('%s', (title, field, indicator, rule) => {
    const p = pickIndicator(field as (typeof FIELDS)[number], title);
    expect(p.indicator).toBe(indicator);
    expect(p.rule).toBe(rule);
  });

  it('表の上の行が優先され、題名の中の語の位置は見ない', () => {
    // 「整備」(T3、題名の先頭側) と「運送事業」(T2、後ろ) → 表の上の T2
    expect(pickIndicator('交通・移動', '整備のための運送事業法').rule).toBe('交通・移動T2');
    // T1 は T2 より上
    expect(pickIndicator('交通・移動', '運送事業の運転者に関する法律').indicator).toBe('就業者数');
  });

  it('どの行にも当たらなければ分野ごとの既定', () => {
    const defaults = Object.fromEntries(FIELDS.map(f => [f, pickIndicator(f, '').indicator]));
    expect(defaults).toEqual({
      '金融': '金融・保険業の付加価値', '交通・移動': '利用件数', '宿泊・観光': '宿泊者数', '通信・ネット': '通信業の付加価値',
      '半導体・電子': '生産額', 'エネルギー': '電力価格', '労働市場': '雇用の流動性', '行政のデジタル化': '電子申請率',
    });
  });

  it('表の指標は spec の候補の中にある', () => {
    const candidates: Record<string, string[]> = {
      '金融': ['不良債権比率', '貸出残高', '企業倒産件数', '金融・保険業の付加価値'], '交通・移動': ['旅客輸送の付加価値', '利用件数', '就業者数'],
      '宿泊・観光': ['宿泊者数', '宿泊業の付加価値', '客室数'], '通信・ネット': ['通信業の付加価値', 'ブロードバンド普及率', 'ネット企業の時価総額'],
      '半導体・電子': ['世界輸出シェア', '生産額'], 'エネルギー': ['電力価格', '発電構成', 'エネルギー効率'],
      '労働市場': ['労働生産性', '賃金', '雇用の流動性'], '行政のデジタル化': ['電子申請率', '行政手続きの時間'],
    };
    for (const f of FIELDS) {
      const used = [PICK_TABLES[f].default, ...PICK_TABLES[f].rules.map(r => r.indicator)];
      for (const i of used) expect(candidates[f]).toContain(i);
    }
  });
});

describe('triageV2：D1〜D5', () => {
  const t = (title: string, kind: string, field: string) => triageV2({ title, kind, field });

  it('D3：新設法人の根拠法は組織手続にせず新規（189-27）', () => {
    const r = t('株式会社海外通信・放送・郵便事業支援機構法案', '組織手続', '通信・ネット');
    expect(r).toMatchObject({ kind: '新規', field: '通信・ネット', indicator: '通信業の付加価値', verdict: '評価対象' });
    expect(r.rules).toContain('D3');
  });

  it('D2：設置法を含む題名は最初の法律で決める。語表に当たらなければ対応表なし（197-1）', () => {
    expect(firstLawTitle('出入国管理及び難民認定法及び法務省設置法の一部を改正する法律案')).toBe('出入国管理及び難民認定法の一部を改正する法律案');
    const r = t('出入国管理及び難民認定法及び法務省設置法の一部を改正する法律案', '実質改正', '労働市場');
    expect(r).toMatchObject({ field: '対応表なし', indicator: '', verdict: '評価対象外' });
    expect(r.rules).toEqual(['D2', 'D1']);
  });

  it('D2：設置法の部分にだけ分野の語があっても、最初の法律で決める', () => {
    const r = t('出入国管理及び難民認定法及び労働省設置法の一部を改正する法律案', '実質改正', '労働市場');
    expect(r.field).toBe('対応表なし');
  });

  it('D2：設置法を含むこと自体では評価対象外にしない', () => {
    const r = t('労働基準法及び厚生労働省設置法の一部を改正する法律案', '実質改正', '労働市場');
    expect(r).toMatchObject({ field: '労働市場', indicator: '賃金', verdict: '評価対象' });
  });

  it.each([
    ['地域人口の急減に対処するための特定地域づくり事業の推進に関する法律案', '労働市場'],
    ['特定受託事業者に係る取引の適正化等に関する法律案', '労働市場'],
    ['株式会社地域経済活性化支援機構法の一部を改正する法律案', '金融'],
    ['脱炭素成長型経済構造への円滑な移行の推進に関する法律及び資源の有効な利用の促進に関する法律の一部を改正する法律案', 'エネルギー'],
  ])('D1：題名に8分野の語が無ければ対応表なし（%s）', (title, field) => {
    const r = t(title, '実質改正', field);
    expect(r).toMatchObject({ field: '対応表なし', indicator: '', verdict: '評価対象外' });
    expect(r.rules).toContain('D1');
  });

  it('D1：AI の対応表なしより題名の語を使う', () => {
    expect(t('労働基準法の一部を改正する法律案', '実質改正', '対応表なし')).toMatchObject({ field: '労働市場', verdict: '評価対象' });
  });

  it.each([
    ['特定高度情報通信技術活用システムの開発供給及び導入の促進に関する法律案', '通信・ネット', '行政のデジタル化'],
    ['道路と銀行に関する法律案', '金融', '交通・移動'],
    ['銀行と道路に関する法律案', '交通・移動', '金融'],
  ])('D1：最初の語の位置で分野を決める %s', (title, field, expected) => {
    expect(t(title, '新規', field).field).toBe(expected);
  });

  it('HR1（v2.1）：最初の位置に異なる分野の語が重なったら、他の語の一部でない最長の語の分野を採る', () => {
    expect(t('電子商取引法案', '新規', '通信・ネット')).toMatchObject({ verdict: '評価対象', field: '通信・ネット', indicator: 'ネット企業の時価総額', rules: ['HR1', 'D1', '通信・ネットC2'] });
    expect(t('海洋再生可能エネルギー発電設備の整備に係る海域の利用の促進に関する法律案', '新規', 'エネルギー')).toMatchObject({ field: 'エネルギー', indicator: '発電構成' });
  });

  it('D5：他の語の一部でない語が複数の分野に残る競合は解けず、競合した分野と語を理由に残して保留', () => {
    expect(resolveTie([{ field: '金融', word: 'AB' }, { field: '交通・移動', word: 'AC' }])).toEqual({
      kind: 'hold', reason: 'D5：最初の語の位置で複数の分野が競合し、他の語の一部でない語が複数の分野に残るため保留（金融「AB」／交通・移動「AC」）',
    });
    expect(resolveTie([{ field: '金融', word: '再生' }, { field: 'エネルギー', word: '再生可能' }])).toEqual({ kind: 'hit', hit: { field: 'エネルギー', word: '再生可能' } });
  });

  it('D4：既存の機構法などの改正は組織手続でなく実質改正', () => {
    const r = t('株式会社企業再生支援機構法の一部を改正する法律案', '組織手続', '金融');
    expect(r).toMatchObject({ kind: '実質改正', field: '金融', verdict: '評価対象' });
    expect(r.rules).toContain('D4');
  });

  it('組織手続のうち設置法・整備法の題名は組織手続のまま（評価対象外）', () => {
    expect(t('総務省設置法の一部を改正する法律案', '組織手続', '通信・ネット')).toMatchObject({ kind: '組織手続', verdict: '評価対象外' });
  });

  it('定型改正は評価対象外。指標は分野が8分野なら付く', () => {
    expect(t('国家公務員の給与に関する法律の一部を改正する法律案', '定型改正', '労働市場')).toMatchObject({ verdict: '評価対象外', indicator: '賃金' });
  });

  it('HR2（v2.1）：機構法等の一部改正はD4と同じく実質改正（設置法を含む題名は直さない）', () => {
    expect(t('地方公共団体情報システム機構法等の一部を改正する法律案', '組織手続', '行政のデジタル化')).toMatchObject({ kind: '実質改正', verdict: '評価対象', rules: ['HR2', 'D1', '行政のデジタル化E1'] });
    expect(t('法務省設置法等の一部を改正する法律案', '組織手続', '対応表なし')).toMatchObject({ kind: '組織手続' });
  });

  it('D5：定義にない種類・分野は推測で埋めず保留', () => {
    expect(t('労働基準法の一部を改正する法律案', '', '労働市場')).toMatchObject({ verdict: '保留', rules: ['D5'] });
    expect(t('労働基準法の一部を改正する法律案', '実質改正', '医療')).toMatchObject({ verdict: '保留', rules: ['D5'] });
  });

  it('純関数：同じ入力は同じ出力', () => {
    const input = { title: '労働安全衛生法等の一部を改正する法律案', kind: '実質改正', field: '労働市場' };
    expect(triageV2(input)).toEqual(triageV2({ ...input }));
  });
});

// field-expansion-v1（docs/提案/分野の拡張-v1.md）：新分野の語は、既存8分野の語が無い題名にだけ当てる。代理の語は「（代理）」付きの別の指標（参考扱い）。
describe('triageV2：field-expansion-v1 の新分野', () => {
  const t = (title: string, kind: string, field: string) => triageV2({ title, kind, field });

  it('新分野は9つ。水道・廃棄物は作らない（承認項目 B3 の推奨）', () => {
    expect(NEW_FIELDS).toHaveLength(9);
    expect(NEW_FIELDS as string[]).not.toContain('水道・廃棄物');
    expect(t('下水道法の一部を改正する法律案', '実質改正', '対応表なし')).toMatchObject({ field: '対応表なし', verdict: '評価対象外' });
  });

  it('新分野の語は既存8分野の語と重ならない', () => {
    const existing = new Set(Object.values(FIELD_WORDS).flat());
    const shared = NEW_FIELDS.flatMap(f => [...NEW_FIELD_WORDS[f].direct, ...NEW_FIELD_WORDS[f].proxy]).filter(w => existing.has(w));
    expect(shared).toEqual([]);
  });

  it('既存優先：既存8分野の語が題名にあれば、新分野の語が前にあっても既存の規則どおり', () => {
    // 同じ位置なら既存優先。R1：「介護保険」の「保険」は金融の語に当てない（医療・福祉）。R3：新分野の語が題名の先なら新分野。
    expect(t('介護保険法の一部を改正する法律案', '実質改正', '対応表なし')).toMatchObject({ field: '医療・福祉' });
    expect(t('建築物のエネルギー消費性能の向上に関する法律案', '新規', '対応表なし')).toMatchObject({ field: '建設' });
    expect(t('建築物のエネルギー消費性能の向上に関する法律案', '新規', '対応表なし').rules).toContain('R3');
    // 既存8分野で決まる題名の結果は、新分野を足す前と同じ（D5 の保留も含む）
    expect(t('電子商取引法案', '新規', '通信・ネット')).toMatchObject({ verdict: '評価対象', field: '通信・ネット' });
    expect(t('労働基準法の一部を改正する法律案', '実質改正', '労働市場')).toMatchObject({ field: '労働市場', indicator: '賃金' });
  });

  it('既存の語が無いときだけ新分野の語を当て、題名で最も前の語の分野に決める', () => {
    expect(t('農業経営基盤強化促進法の一部を改正する法律案', '実質改正', '対応表なし')).toMatchObject({ field: '農林水産', indicator: '農林水産業の付加価値', verdict: '評価対象' });
    expect(t('農業のための大学の整備に関する法律案', '新規', '対応表なし').field).toBe('農林水産');
    expect(t('大学のための農業の整備に関する法律案', '新規', '対応表なし').field).toBe('教育');
  });

  it('直接の語は指標名そのまま、代理の語は「（代理）」付きの別の指標', () => {
    const direct = t('建設業法の一部を改正する法律案', '実質改正', '対応表なし');
    expect(direct).toMatchObject({ field: '建設', indicator: '建設業の付加価値', rules: ['D1', '建設直接'] });
    const proxy = t('河川法の一部を改正する法律案', '実質改正', '対応表なし');
    expect(proxy).toMatchObject({ field: '建設', indicator: '建設業の付加価値' + PROXY_SUFFIX, rules: ['D1', '建設代理'] });
    expect(newIndicator('建設', '代理')).toBe('建設業の付加価値（代理）');
    // 代理の語しか持たない分野は常に（代理）付き
    for (const f of NEW_FIELDS.filter(f => NEW_FIELD_WORDS[f].direct.length === 0)) {
      expect(t(`${NEW_FIELD_WORDS[f].proxy[0]}法案`, '新規', '対応表なし').indicator).toBe(NEW_FIELD_WORDS[f].indicator + PROXY_SUFFIX);
    }
  });

  it('同じ位置の語が別の語の一部なら長い語を採る（建築 → 建築士）', () => {
    expect(t('建築士法の一部を改正する法律案', '実質改正', '対応表なし')).toMatchObject({ field: '専門サービス・研究開発', indicator: '専門・科学技術、業務支援サービス業の付加価値' });
    expect(t('土地改良法の一部を改正する法律案', '実質改正', '対応表なし').field).toBe('農林水産');
  });

  it('D2：設置法の部分にだけ新分野の語があっても、最初の法律で決める', () => {
    expect(t('公職選挙法及び農林水産省設置法の一部を改正する法律案', '実質改正', '対応表なし').field).toBe('対応表なし');
  });

  it('種類が定型改正・組織手続なら新分野でも評価対象外。AI の入力分野に新分野名があっても受け付ける', () => {
    expect(t('農業振興法の一部を改正する法律案', '定型改正', '対応表なし')).toMatchObject({ field: '農林水産', verdict: '評価対象外' });
    expect(t('農業法案', '新規', '農林水産').verdict).toBe('評価対象');
    expect(t('農業法案', '新規', '水道・廃棄物')).toMatchObject({ verdict: '保留', rules: ['D5'] });
  });

  it('語が当たらなければ対応表なしのまま', () => {
    expect(t('公職選挙法の一部を改正する法律案', '実質改正', '対応表なし')).toMatchObject({ field: '対応表なし', indicator: '', verdict: '評価対象外' });
  });
});
