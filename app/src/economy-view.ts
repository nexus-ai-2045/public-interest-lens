export type EconomicSeries = { id: string; label: string; unit: string; basis: string; sourceUrl: string; points: { year: number; value: number | null }[] };
export type OutcomeCandidate = { id: string; title: string; observationFrom: string; observationTo: string; implementation: string; observedResult: string; contribution: string; counterEvidence: string; reviewStatus: 'draft'; impact: null; actors: { name: string; action: string; attributionStatus: 'source_mention_not_individual_impact' }[]; sources: { title: string; url: string }[] };
export type EconomicSnapshot = { schemaVersion: 'economic-series/v1'; observedAt: string; provider: string; country: 'JPN'; series: EconomicSeries[]; unavailable: string[]; note: string; outcomes?: OutcomeCandidate[]; snapshotId?: string };
export function parseEconomicSnapshot(text: string): EconomicSnapshot {
  if (text.length > 1_000_000) throw new Error('統計データが大きすぎます。');
  const value = JSON.parse(text) as EconomicSnapshot;
  if (value?.schemaVersion !== 'economic-series/v1' || value.country !== 'JPN' || !Array.isArray(value.series) || !Array.isArray(value.unavailable)) throw new Error('統計データが不正です。');
  if (value.snapshotId !== undefined && !/^[a-f0-9]{64}$/.test(value.snapshotId)) throw new Error('統計版が不正です。');
  const ids = new Set<string>();
  for (const series of value.series) {
    const url = new URL(series.sourceUrl);
    if (ids.has(series.id) || !['real_gdp', 'nominal_gdp', 'population', 'real_gdp_per_capita'].includes(series.id) || ![series.label, series.unit, series.basis].every(text => typeof text === 'string') || url.protocol !== 'https:' || url.hostname !== 'api.worldbank.org' || url.username || url.password || !Array.isArray(series.points)) throw new Error('統計系列の参照が不正です。');
    ids.add(series.id);
    const years = new Set<number>();
    for (const point of series.points) {
      if (!Number.isSafeInteger(point.year) || point.year < 1900 || point.year > 2100 || years.has(point.year) || (point.value !== null && (typeof point.value !== 'number' || !Number.isFinite(point.value) || point.value < 0))) throw new Error('年次統計値が不正です。');
      years.add(point.year);
    }
  }
  if (value.outcomes !== undefined) {
    if (!Array.isArray(value.outcomes)) throw new Error('結果評価候補が不正です。');
    for (const outcome of value.outcomes) {
      if (!outcome || outcome.reviewStatus !== 'draft' || outcome.impact !== null || !Array.isArray(outcome.sources) || !Array.isArray(outcome.actors) || ![outcome.id, outcome.title, outcome.implementation, outcome.observedResult, outcome.contribution, outcome.counterEvidence].every(text => typeof text === 'string' && text.trim().length > 0 && text.length < 10000) || !/^\d{4}-\d{2}-\d{2}$/.test(outcome.observationFrom) || !/^\d{4}-\d{2}-\d{2}$/.test(outcome.observationTo) || outcome.observationFrom > outcome.observationTo) throw new Error('結果評価候補の内容が不正です。');
      for (const source of outcome.sources) {
        const url = new URL(source.url);
        if (url.protocol !== 'https:' || !['www.fsa.go.jp', 'www.imf.org'].includes(url.hostname) || url.username || url.password || !source.title) throw new Error('結果評価の出典が不正です。');
      }
      for (const actor of outcome.actors) if (actor.attributionStatus !== 'source_mention_not_individual_impact' || typeof actor.name !== 'string' || typeof actor.action !== 'string') throw new Error('人物の関与候補が不正です。');
    }
  }
  return value;
}
export function selectEconomicPeriod(series: EconomicSeries, period: string, from?: number, to?: number) {
  const years = series.points.map(point => point.year);
  const latest = years.length ? Math.max(...years) : null;
  if (latest === null) return [];
  const end = period === 'custom' ? to : latest;
  const start = period === 'custom' ? from : latest - Number(period) + 1;
  if (!Number.isSafeInteger(start) || !Number.isSafeInteger(end) || start! > end! || end! > latest || start! < Math.min(...years) || (period !== 'custom' && !['2', '4', '8', '30', '40'].includes(period))) throw new Error('期間を正しく指定してください。');
  const points = new Map(series.points.map(point => [point.year, point.value]));
  return Array.from({ length: end! - start! + 1 }, (_, index) => ({ year: start! + index, value: points.get(start! + index) ?? null }));
}
