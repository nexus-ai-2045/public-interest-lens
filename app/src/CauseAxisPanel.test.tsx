// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import causeAxis from './cause-axis.json';
import { AccountingTable, AxisTable, CauseAxisPanel, PeerBars, industryLead, industrySeries } from './CauseAxisPanel';

const byCode = (code: string) => causeAxis.industries.find(i => i.code === code)!;

describe('産業別の付加価値の比較（原因の軸）', () => {
  it('折れ線は日本と比べる国の中央値の2本で、2000年が100です', () => {
    const lines = industrySeries(byCode('J61'));
    expect(lines.map(l => l.id)).toEqual(['JPN', 'MEDIAN']);
    expect(lines[0].points[0].year).toBe(2001);
    for (const line of lines) for (const p of line.points) expect(p.value).toBeGreaterThan(0);
  });
  it('置換検定が3位以内の産業だけ「参考」、ほかは誤差の範囲として額を軸に配りません', () => {
    expect(industryLead(byCode('J61'))).toContain('参考として載せます');
    expect(industryLead(byCode('J62_63'))).toContain('誤差の範囲');
    expect(industryLead(byCode('C26'))).toContain('日本の方が伸びた');
    for (const i of causeAxis.industries) expect(i.certainty).toBe(i.rank <= 3 ? '参考' : '誤差の範囲');
  });
  it('国の棒は日本を含み、並びは2023年の比の降順です', () => {
    const html = renderToStaticMarkup(<PeerBars industry={byCode('J62_63')} />);
    expect(html).toContain('class="is-japan"');
    expect(html).not.toContain('NaN');
  });
  it('軸の表は記録だけの軸に額を出さず、便益の軸には「損失の額はつけない」と書きます', () => {
    const html = renderToStaticMarkup(<AxisTable data={causeAxis} />);
    expect(html).toContain('損失の額はつけない');
    expect(html).toContain('決定の効果の推定ができるまで配らない');
    const e1 = causeAxis.axes.find(a => a.code === 'E1')!;
    expect(e1.trillionYen).toBeNull();
  });
  it('成長会計は系列の無い産業を「—」と印で示し、割合を作りません', () => {
    const html = renderToStaticMarkup(<AccountingTable data={causeAxis} />);
    expect(html).toContain('日本の就業者・資本の系列が STAN に無い');
    expect(html).not.toContain('NaN');
  });
  it('パネル全体が描画でき、原因の断定をしない注記を持ちます', () => {
    const html = renderToStaticMarkup(<CauseAxisPanel />);
    expect(html).toContain('産業ごとに、日本は同じ産業の他国より伸びたか');
    expect(html).toContain('人や組織にはまだ配っていません');
  });
  it('全ての産業で、日本と比べる国の中央値の2本の線が実際に描かれます（2000年の点が無い系列を指数化で捨てない）', () => {
    for (const industry of causeAxis.industries) {
      const html = renderToStaticMarkup(<CauseAxisPanel initial={industry.code} />);
      expect(html.match(/class="m-line-path[^"]*" d="M/g)?.length, industry.code).toBe(2);
      expect(html).toContain('>日本</text>');
      expect(html).toContain('>比べる国の中央値</text>');
      expect(html).not.toContain('NaN');
    }
  });
  it('経済全体だけは、全体の伸びで割らず就業者1人当たりの伸びだと図に書きます（説明と計算をそろえる）', () => {
    const total = byCode('_T');
    expect(total.measure).toContain('就業者1人当たり');
    expect(total.measure).toContain('割らない');
    expect(byCode('J61').measure).toContain('全体の実質の伸び');
    const html = renderToStaticMarkup(<CauseAxisPanel initial="_T" />);
    expect(html).toContain('data-measure="_T"');
    expect(html).toContain('この図の値：就業者1人当たり');
  });
});
