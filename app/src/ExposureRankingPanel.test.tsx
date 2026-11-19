// @vitest-environment node
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { EXPOSURE_DISCLAIMER, summarizeUnallocated, toPanelExposureRanking, type ExposureRanking } from './exposure-ranking';
import { ExposureRankingPanel, ROLE_LABEL, canShowCellAmounts, exposureRange, exposureScale, exposureYen, groupByTier, orderWithinTiers, reasonKind, totalsCheck, totalsOfRanked, unrankedBreakdown } from './ExposureRankingPanel';
import { SAMPLE_GROUPS, SAMPLE_PARTY_NAMES, SAMPLE_PERSON_NAMES, sampleExposureRanking } from './exposure-ranking-sample';
import { formatYen } from './laws-catalog';

const ranking = sampleExposureRanking();
const render = (r: ExposureRanking = ranking, tab: 'people' | 'parties' = 'people') =>
  renderToStaticMarkup(<ExposureRankingPanel ranking={toPanelExposureRanking(r)} groups={SAMPLE_GROUPS} personNames={SAMPLE_PERSON_NAMES} partyNames={SAMPLE_PARTY_NAMES} initialTab={tab} />);
/** 開始タグから次の同じ開始タグまでを切り出す（行ごとの中身を調べる）。 */
const blocks = (html: string, open: string) => html.split(open).slice(1);

describe('曝露ランキングの画面部品', () => {
  it('架空データに、階層に入る人・下限未満の人・未配分・負の額・本数の少ない内訳がそろっています（前提）', () => {
    expect(ranking.parties.some(p => p.tier === null)).toBe(true);
    expect(ranking.people.some(p => p.tier !== null && p.cells.some(c => c.laws < ranking.params.minLaws))).toBe(true);
    expect(ranking.parties.some(p => p.tier !== null && p.exposureYen.median < 0 && p.cells.every(c => c.role === 'no'))).toBe(true);
    expect(ranking.people.some(p => p.tier !== null)).toBe(true);
    expect(ranking.people.some(p => p.tier === null)).toBe(true);
    expect(ranking.people.some(p => p.exposureYen.median < 0)).toBe(true);
    expect(ranking.unallocated.length).toBeGreaterThan(0);
    expect(new Set(ranking.people.map(p => p.tier)).size).toBeGreaterThan(2);
  });

  it('最上部に「因果ではなく記述」と、集計器の注記をそのまま出します', () => {
    const html = render();
    expect(html).toContain('因果ではなく記述');
    expect(html).toContain(EXPOSURE_DISCLAIMER);
    expect(html.indexOf('因果ではなく記述')).toBeLessThan(html.indexOf('xr-tier'));
    expect(html.indexOf(EXPOSURE_DISCLAIMER)).toBeLessThan(html.indexOf('xr-tier'));
  });

  it('順位ではなく階層で出し、階層の数と人数が集計器の出力と一致します', () => {
    const html = render();
    const ranked = ranking.people.filter(p => p.tier !== null);
    const tiers = groupByTier(ranking.people);
    expect(tiers.map(t => t.tier)).toEqual([...new Set(ranked.map(p => p.tier))]);
    for (const t of tiers) expect(html).toContain(`aria-label="第${t.tier}階層"`);
    expect(blocks(html, '<li class="xr-row')).toHaveLength(ranked.length);
    expect(html).not.toMatch(/\d位/);
    expect(html).toContain('並び順に、差の意味はありません');
  });

  it('階層に入る人は、額・幅・関与した本数と群の数を出します', () => {
    const html = render();
    for (const p of ranking.people.filter(x => x.tier !== null)) {
      const row = blocks(html, '<li class="xr-row').find(b => b.includes(`>${SAMPLE_PERSON_NAMES[p.actorId]}<`));
      expect(row, p.actorId).toBeDefined();
      expect(row).toContain(`<summary aria-label="${SAMPLE_PERSON_NAMES[p.actorId]}、${exposureYen(p.exposureYen.median)}、${exposureRange(p.exposureYen)}、関与した法律${p.laws}本・${p.groups}群">`);
      expect(row).toContain(`aria-label="${formatYen(Math.abs(p.exposureYen.median))}"`);
      expect(row).toContain(exposureRange(p.exposureYen));
      expect(row).toContain(`関与した法律 ${p.laws}本・${p.groups}群`);
      expect(row).toContain(`<span class="xr-side">${p.exposureYen.median < 0 ? '逆側' : '伸び損ね側'}</span>`);
    }
  });

  it('実名の横に「国賊」「国士」の札を付けず、先頭の人を目立たせる演出も付けません', () => {
    const html = render() + render(ranking, 'parties');
    expect(html).not.toContain('国賊');
    expect(html).not.toContain('国士');
    expect(html).not.toContain('burst');
  });

  it('同じ階層の中は名前の順に並べ、額の順にしません', () => {
    const nameOf = (r: { actorId: string }) => SAMPLE_PERSON_NAMES[r.actorId];
    const ordered = orderWithinTiers(ranking.people, nameOf);
    const html = render();
    const shown = blocks(html, '<li class="xr-row').map(b => /<span class="xr-name">([^<]*)</.exec(b)![1]);
    expect(shown).toEqual(ordered.map(nameOf));
    for (const t of groupByTier(ordered)) {
      const names = t.rows.map(nameOf);
      expect(names).toEqual([...names].sort((a, b) => a.localeCompare(b, 'ja')));
    }
  });

  it('読みがあれば、階層の中は読みの五十音順に並べます（読みの無い人は名前で）', () => {
    const ranked = ranking.people.filter(p => p.tier !== null);
    // 名前の順と逆になる読みを付ける。
    const byName = orderWithinTiers(ranking.people, r => SAMPLE_PERSON_NAMES[r.actorId]);
    const kana = 'あいうえおかきくけこさしすせそ';
    const readings = Object.fromEntries(byName.map((r, i) => [r.actorId, kana[byName.length - 1 - i]]));
    const html = renderToStaticMarkup(<ExposureRankingPanel ranking={toPanelExposureRanking(ranking)} personNames={SAMPLE_PERSON_NAMES} personReadings={readings} />);
    const shown = blocks(html, '<li class="xr-row').map(b => /<span class="xr-name">([^<]*)</.exec(b)![1]);
    const expected = orderWithinTiers(ranking.people, r => readings[r.actorId]).map(r => SAMPLE_PERSON_NAMES[r.actorId]);
    // 読みの無い人は、読みのある人の後に名前の順で並ぶ。
    const [first, ...rest] = byName;
    const partial = Object.fromEntries(rest.map(r => [r.actorId, readings[r.actorId]]));
    // 階層を1つにそろえて、読みの無い1人が必ず末尾に来ることを見る。
    const oneTier: ExposureRanking = { ...ranking, people: ranking.people.map(p => (p.tier === null ? p : { ...p, tier: 1 })) };
    const html2 = renderToStaticMarkup(<ExposureRankingPanel ranking={toPanelExposureRanking(oneTier)} personNames={SAMPLE_PERSON_NAMES} personReadings={partial} />);
    const shown2 = blocks(html2, '<li class="xr-row').map(b => /<span class="xr-name">([^<]*)</.exec(b)![1]);
    expect(shown2[shown2.length - 1]).toBe(SAMPLE_PERSON_NAMES[first.actorId]);
    expect(shown2.slice(0, -1)).toEqual([...rest].sort((a, b) => partial[a.actorId].localeCompare(partial[b.actorId], 'ja')).map(r => SAMPLE_PERSON_NAMES[r.actorId]));
    expect(shown).toEqual(expected);
    expect(ranked.length).toBeGreaterThan(1);
  });

  it('階層が1つだけのときは、そう書きます', () => {
    const one: ExposureRanking = { ...ranking, people: ranking.people.map(p => (p.tier === null ? p : { ...p, tier: 1 })) };
    expect(render(one)).toContain('階層は1つだけです。並びは読みの五十音順（読みの無い人はその後に名前の文字の順）で、額の大きい順ではありません');
    const oneParty: ExposureRanking = { ...ranking, parties: ranking.parties.map(p => (p.tier === null ? p : { ...p, tier: 1 })) };
    const partiesHtml = render(oneParty, 'parties');
    expect(partiesHtml).toContain('並びは名前の文字の順で、額の大きい順ではありません');
    expect(partiesHtml).not.toContain('五十音');
    expect(render()).not.toContain('階層は1つだけです');
  });

  it('衆議院の賛否は会派の欄に入ることと、閣僚の額が大きくなりやすいことを出します', () => {
    const html = render();
    expect(html).toContain('衆議院の賛成・反対は会派単位の記録しか無いため「会派」の欄に入り');
    expect(html).toContain('閣僚は関与の量が多く額が大きくなりやすい');
  });

  it('関与した法律が下限に満たない人は、額を出さず、関与した群と本数だけを出します', () => {
    const html = render();
    const unranked = ranking.people.filter(p => p.tier === null);
    const rows = blocks(html, '<li class="xr-unranked-row">').map(b => b.split('</ul></li>')[0]);
    expect(rows).toHaveLength(unranked.length);
    for (const p of unranked) {
      const row = rows.find(b => b.includes(SAMPLE_PERSON_NAMES[p.actorId]))!;
      expect(row).toContain(`関与した法律 ${p.laws}本・${p.groups}群（額は出しません）`);
      expect(row).toContain(`理由：${p.unrankedReason}`);
      expect(row).toContain('架空の小売（2011〜2020年）');
      expect(row).not.toMatch(/円/);
      expect(row).not.toContain('伸び損ね');
      expect(row).not.toContain('逆側');
    }
    const breakdown = unrankedBreakdown(ranking.people);
    expect(breakdown.reduce((n, b) => n + b.count, 0)).toBe(unranked.length);
    expect(html).toContain(`額を出さない人（理由つき）：${unranked.length}人（${breakdown.map(b => `${b.reason} ${b.count}`).join('・')}）`);
  });

  it('理由の種類は末尾の「（○本）」を外して数えます', () => {
    expect(reasonKind('関与した法律が5本に満たない（3本）')).toBe('関与した法律が5本に満たない');
    expect(reasonKind('上位3本の占有率が50.0%を超える（61.2%）')).toBe('上位3本の占有率が50.0%を超える');
    expect(reasonKind('産業別の群への関与の記録が無い（全産業の別欄にある）')).toBe('産業別の群への関与の記録が無い（全産業の別欄にある）');
    expect(reasonKind('群に属する法律への関与の記録が無い')).toBe('群に属する法律への関与の記録が無い');
  });

  it('下限に満たない会派も、額を出さず群と本数だけを出します', () => {
    const html = render(ranking, 'parties');
    const rows = blocks(html, '<li class="xr-unranked-row">').map(b => b.split('</ul></li>')[0]);
    expect(rows).toHaveLength(ranking.parties.filter(p => p.tier === null).length);
    for (const row of rows) {
      expect(row).toContain('架空の会D');
      expect(row).not.toMatch(/円/);
    }
  });

  it('内訳に本数が下限に満たない群×役割が1つでもある人は、内訳の額を全部伏せます（合計との引き算で復元させない）', () => {
    const min = ranking.params.minLaws;
    const rows = [...blocks(render(), '<li class="xr-row'), ...blocks(render(ranking, 'parties'), '<li class="xr-row')];
    const names = { ...SAMPLE_PERSON_NAMES, ...SAMPLE_PARTY_NAMES };
    let hidden = 0;
    let shown = 0;
    for (const actor of [...ranking.people, ...ranking.parties].filter(r => r.tier !== null)) {
      const detail = rows.find(b => b.includes(`>${names[actor.actorId]}<`))!.split('<div class="xr-detail">')[1];
      const ok = canShowCellAmounts(actor, min);
      expect(ok).toBe(actor.cells.every(c => c.laws >= min));
      if (ok) { shown++; for (const cell of actor.cells) expect(detail).toContain(`<b>${ROLE_LABEL[cell.role]}</b> ${cell.laws}本 ・ ${exposureYen(cell.exposureYen.median)}`); }
      else { hidden++; expect(detail.split('<ul class="xr-cells">')[1]).not.toMatch(/円/); expect(detail).toContain('内訳の額は全部伏せます'); }
    }
    expect(hidden).toBeGreaterThan(0);
    expect(shown).toBeGreaterThan(0);
  });

  it('負の額を「上回り」と書きません（伸び損ねた群への反対でも負になるため「逆側」と呼び、意味を説明します）', () => {
    const html = render() + render(ranking, 'parties');
    expect(html).not.toContain('上回り');
    expect(html).toContain('伸び損ねた群に反対した額');
    expect(html).toContain('群が上回ったという意味とは限りません');
  });

  it('検算欄は、額を出さない人・会派の分を未配分と合わせた1行にし、1つだけのときは合計の額を出しません', () => {
    const section = (html: string) => blocks(html, '<details class="xr-totals">')[0];
    const rankedTotals = totalsOfRanked(ranking);
    const rest = totalsCheck(ranking.totals).sum.median - rankedTotals.people.median - rankedTotals.parties.median;
    const html = section(render());
    expect(html).toContain(`<dt>階層に入る議員</dt><dd>${exposureYen(rankedTotals.people.median)}</dd>`);
    expect(html).toContain(`<dd>${exposureYen(rest)}</dd>`);
    expect(html).not.toContain(`<dd>${exposureYen(ranking.totals.people.median)}</dd>`);
    expect(html).not.toContain(`<dd>${exposureYen(ranking.totals.unallocated.median)}</dd>`);
    const one: ExposureRanking = { ...ranking, parties: ranking.parties.filter(p => p.tier !== null) };
    const hiddenOne = section(render(one));
    expect(hiddenOne).toContain('合計の額は出しません');
    expect(hiddenOne).not.toContain('<dt>合計</dt>');
    expect(hiddenOne).not.toContain('それ以外');
    expect(render(one)).not.toMatch(/配らなかった額（未配分）：[^<]*円/);
  });

  it('法律の ID も法律ごとの額も画面に出しません', () => {
    const html = render() + render(ranking, 'parties');
    for (const id of ['info-1', 'retail-1', 'machine-1']) expect(html).not.toContain(id);
  });

  it('会派の表示に切り替えられ、会派名と階層を出します', () => {
    const html = render(ranking, 'parties');
    for (const p of ranking.parties.filter(x => x.tier !== null)) expect(html).toContain(`>${SAMPLE_PARTY_NAMES[p.actorId]}<`);
    expect(html).toContain('aria-label="第1階層"');
    expect(html).not.toContain(SAMPLE_PERSON_NAMES.P01);
  });

  it('配らなかった額は、群×役割の合計で理由つきに出し、「N本ぶんの枠」は出しません', () => {
    const html = render();
    const items = blocks(html, '<ul class="xr-unallocated-list">')[0].split('</ul>')[0];
    const summary = summarizeUnallocated(ranking.unallocated, ranking.params.minLaws);
    expect(items.split("<li>").length - 1).toBe(Math.min(summary.length, 30));
    for (const u of ranking.unallocated) expect(items).toContain(u.reason);
    expect(items).not.toContain('本ぶんの枠');
    expect(items).toContain('全役割');
    expect(items).toContain('本数の少ない群×役割（まとめ）');
  });

  it('検算が合えば「一致」、合わなければ警告を出します', () => {
    expect(totalsCheck(ranking.totals).ok).toBe(true);
    expect(render()).toContain('：一致');
    const broken: ExposureRanking = { ...ranking, totals: { ...ranking.totals, expected: { low: 0, median: 1e12, high: 2e12 } } };
    expect(totalsCheck(broken.totals).ok).toBe(false);
    const html = render(broken);
    expect(html).toContain('：不一致');
    expect(html).toContain('role="alert"');
  });

  it('階層に入る人がいないときは、額の一覧を出さず理由を出します', () => {
    const empty: ExposureRanking = { ...ranking, people: ranking.people.filter(p => p.tier === null) };
    const html = render(empty);
    expect(html).toContain('階層に入る人がまだいません');
    expect(html).not.toContain('class="xr-row');
  });

  it('名前の対応が無いときは ID を、群の対応が無いときは群の ID を出します', () => {
    const html = renderToStaticMarkup(<ExposureRankingPanel ranking={toPanelExposureRanking(ranking)} />);
    expect(html).toContain('>P01<');
    expect(html).toContain('G-info-2001');
    expect(html).not.toContain('NaN');
    expect(html).not.toContain('undefined');
  });

  it('額は向きを言葉で付け、幅はゼロをまたぐときだけ両端に向きを付けます', () => {
    expect(exposureYen(3e12)).toBe('伸び損ね側 3兆円');
    expect(exposureYen(-2e12)).toBe('逆側 2兆円');
    expect(exposureYen(0)).toBe('0円');
    expect(exposureRange({ low: 1e12, median: 2e12, high: 3e12 })).toBe('幅 伸び損ね側 1兆円〜3兆円');
    expect(exposureRange({ low: -3e12, median: -2e12, high: -1e12 })).toBe('幅 逆側 1兆円〜3兆円');
    expect(exposureRange({ low: -1e12, median: 1e12, high: 3e12 })).toBe('幅 逆側 1兆円〜伸び損ね側 3兆円');
    expect(exposureRange({ low: 0, median: 0, high: 0 })).toBe('幅 0億円〜0億円');
  });

  it('棒の物差しはゼロを必ず含み、0〜100% に収まります', () => {
    const scale = exposureScale(ranking.people.filter(p => p.tier !== null));
    expect(scale.min).toBeLessThan(0);
    expect(scale.position(scale.min)).toBe(0);
    expect(scale.position(scale.max)).toBe(100);
    expect(scale.position(0)).toBeGreaterThan(0);
    expect(scale.position(scale.max * 2)).toBe(100);
    const flat = exposureScale([]);
    expect(Number.isFinite(flat.position(0))).toBe(true);
  });
});
