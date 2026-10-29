// @ts-nocheck
// @vitest-environment node
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { PledgeParty } from './PledgesPage';
import { parsePledges, pledgeRates, stanceTally } from './pledges';

const text = readFileSync(new URL('../public/distribution/pledges.json', import.meta.url), 'utf8');
const data = parsePledges(text);

describe('公約と成立法の対応', () => {
  it('全党の件数が項目と合い、公式の https 出典を持ちます', () => {
    expect(data.parties.length).toBeGreaterThanOrEqual(7);
    for (const p of data.parties) expect(p.source.url).toMatch(/^https:\/\//);
  });
  it('成立の割合は確定分≦上限で、法律不要を除いた分母は総数以下です', () => {
    for (const p of data.parties) { const r = pledgeRates(p); expect(r.upper).toBeGreaterThanOrEqual(r.confirmed ?? 0); expect(r.measurableDenominator).toBeLessThanOrEqual(p.total); }
  });
  it('成立と判定した項目は対応する法律を持ちます', () => {
    for (const p of data.parties) for (const i of p.items) if (i.status === 'enacted') expect(i.laws.length).toBeGreaterThan(0);
  });
  it('件数がずれたデータは読み込みません', () => {
    const bad = JSON.parse(text); bad.parties[0].counts.enacted += 1;
    expect(() => parsePledges(JSON.stringify(bad))).toThrow();
    expect(() => parsePledges('{}')).toThrow();
  });
  it('野党は賛成した本数も出し、与党は比べないよう注意を出します', () => {
    const opp = data.parties.find(p => !p.governing)!;
    expect(stanceTally(opp).laws).toBeGreaterThan(0);
    expect(renderToStaticMarkup(createElement(PledgeParty, { data, name: opp.name }))).toContain('衆議院で賛成側');
    expect(renderToStaticMarkup(createElement(PledgeParty, { data, name: data.parties.find(p => p.governing)!.name }))).toContain('直接比べないでください');
  });
});
