/** 世界のGDP比較（/world）のデータ形式・検証・計算。画面の部品は WorldGdpPage.tsx が持ちます。 */
/** 配布ファイルに入っている系列。 */
export const FILE_METRICS = ['nominalUsd', 'realGrowth', 'perCapitaPpp'] as const;
/** 画面で選べる指標。realGdp は realGrowth（年ごとの実質成長率）を積み上げて作る指数で、ファイルには入っていません。 */
export const WORLD_METRICS = [...FILE_METRICS, 'realGdp'] as const;
export type WorldMetric = typeof WORLD_METRICS[number];
export type YearValue = [number, number];
export type WorldCountry = {
  code: string;
  name: string;
  provider: string;
  sourceUrls: Partial<Record<WorldMetric, string>>;
  series: Partial<Record<WorldMetric, YearValue[]>>;
};
export type WorldGdpSnapshot = { schemaVersion: 'world-gdp/v1'; fetchedAt: string; notes: string[]; countries: WorldCountry[] };

export const distributionWorldGdpUrl = '/distribution/world-gdp.json';
const SOURCE_HOSTS = new Set(['api.worldbank.org', 'www.imf.org']);
const prose = (value: unknown, limit = 2000) => typeof value === 'string' && value.trim().length > 0 && value.length <= limit;
const plainObject = (value: unknown): value is Record<string, unknown> => !!value && typeof value === 'object' && !Array.isArray(value);

function checkSourceUrl(text: unknown) {
  if (typeof text !== 'string') throw new Error('出典の URL が不正です。');
  const url = new URL(text);
  if (url.protocol !== 'https:' || !SOURCE_HOSTS.has(url.hostname) || url.username || url.password || url.port) throw new Error('出典の URL が不正です。');
}

function checkPoints(metric: WorldMetric, points: unknown) {
  if (!Array.isArray(points) || points.length === 0) throw new Error('年次の値が不正です。');
  let previous = -Infinity;
  for (const point of points) {
    if (!Array.isArray(point) || point.length !== 2) throw new Error('年次の値が不正です。');
    const [year, value] = point as unknown[];
    if (!Number.isSafeInteger(year) || (year as number) < 1900 || (year as number) > 2100 || (year as number) <= previous) throw new Error('年の並びが不正です。');
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('年次の値が不正です。');
    if (metric === 'realGrowth' ? value <= -100 || value >= 100 : value <= 0) throw new Error('年次の値が範囲外です。');
    previous = year as number;
  }
}

/** 公開配布の world-gdp.json を読みます。形式・出典・年・値のどれかが不正なら、全体を読み込みません。 */
export function parseWorldGdp(text: string): WorldGdpSnapshot {
  if (text.length > 2_000_000) throw new Error('世界のGDPデータが大きすぎます。');
  const value = JSON.parse(text) as WorldGdpSnapshot;
  if (!plainObject(value) || value.schemaVersion !== 'world-gdp/v1' || Object.keys(value).some(key => !['schemaVersion', 'fetchedAt', 'notes', 'countries'].includes(key))) throw new Error('世界のGDPデータの形式が不正です。');
  if (typeof value.fetchedAt !== 'string' || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$/.test(value.fetchedAt) || Number.isNaN(Date.parse(value.fetchedAt))) throw new Error('取得日時が不正です。');
  if (!Array.isArray(value.notes) || !value.notes.every(note => prose(note))) throw new Error('注記が不正です。');
  if (!Array.isArray(value.countries) || value.countries.length === 0) throw new Error('国の一覧が不正です。');
  const codes = new Set<string>();
  for (const country of value.countries) {
    if (!plainObject(country) || Object.keys(country).some(key => !['code', 'name', 'provider', 'sourceUrls', 'series'].includes(key))) throw new Error('国の項目が不正です。');
    if (typeof country.code !== 'string' || !/^[A-Z]{3}$/.test(country.code) || codes.has(country.code) || !prose(country.name, 40) || !prose(country.provider, 200)) throw new Error('国の項目が不正です。');
    codes.add(country.code);
    if (!plainObject(country.series) || !plainObject(country.sourceUrls)) throw new Error('系列が不正です。');
    const seriesKeys = Object.keys(country.series);
    if (seriesKeys.length === 0 || seriesKeys.some(key => !(FILE_METRICS as readonly string[]).includes(key))) throw new Error('系列が不正です。');
    if (Object.keys(country.sourceUrls).some(key => !seriesKeys.includes(key))) throw new Error('出典の対応が不正です。');
    for (const metric of seriesKeys as WorldMetric[]) {
      checkSourceUrl(country.sourceUrls[metric]);
      checkPoints(metric, country.series[metric]);
    }
  }
  if (!codes.has('JPN')) throw new Error('日本の系列がありません。');
  return withRealGdp(value);
}

/**
 * 年ごとの実質成長率（％）を積み上げて、実質GDPの指数にします。最初の成長率の前年を100とします。
 * 水準ではなく伸びの積み上げなので、国どうしの「大きさ」は比べられません（初期年=100の比較専用）。
 */
export function cumulateGrowth(points: YearValue[] | undefined): YearValue[] | undefined {
  if (!points?.length) return undefined;
  let level = 100;
  const result: YearValue[] = [[points[0][0] - 1, level]];
  let previous = points[0][0] - 1;
  for (const [year, rate] of points) {
    if (year !== previous + 1) break; // 年が飛ぶ所で打ち切る（欠けた年を0％で埋めない）
    level *= 1 + rate / 100;
    result.push([year, level]);
    previous = year;
  }
  return result;
}

/** 各国に実質GDPの指数（realGdp）を足した写しを返します。 */
export function withRealGdp(snapshot: WorldGdpSnapshot): WorldGdpSnapshot {
  return { ...snapshot, countries: snapshot.countries.map(country => {
    const realGdp = cumulateGrowth(country.series.realGrowth);
    return realGdp ? { ...country, series: { ...country.series, realGdp }, sourceUrls: { ...country.sourceUrls, realGdp: country.sourceUrls.realGrowth } } : country;
  }) };
}

export const WORLD_PERIODS = ['all', '1960', '1970', '1980', '1990', '2000', '2010', '2015', '2020', '2023'] as const;
export type WorldPeriod = typeof WORLD_PERIODS[number];
export const periodLabel = (period: WorldPeriod) => period === 'all' ? '全期間' : `${period}年以降`;
/** 左の選択肢に出す短い表記。 */
export const periodShort = (period: WorldPeriod) => period === 'all' ? '全期間' : `${period}年〜`;

/** 全系列の最初と最後の年。 */
export function yearSpan(snapshot: WorldGdpSnapshot, metric: WorldMetric): { first: number; last: number } | null {
  const years = snapshot.countries.flatMap(country => (country.series[metric] ?? []).map(([year]) => year));
  return years.length ? { first: Math.min(...years), last: Math.max(...years) } : null;
}

/** 期間の開始年と終了年。全期間はその指標の最初の年から。 */
export function periodRange(snapshot: WorldGdpSnapshot, metric: WorldMetric, period: WorldPeriod): { from: number; to: number } | null {
  const span = yearSpan(snapshot, metric);
  if (!span) return null;
  const from = period === 'all' ? span.first : Math.max(Number(period), span.first);
  return from <= span.last ? { from, to: span.last } : null;
}

export function pointsInRange(points: YearValue[] | undefined, from: number, to: number): YearValue[] {
  return (points ?? []).filter(([year]) => year >= from && year <= to);
}

export type AverageGrowth = { value: number; from: number; to: number; years: number };

/** 実質成長率（％）の年平均。複利で平均します（各年の伸びを掛け合わせて年数で割り戻す）。 */
export function averageGrowth(points: YearValue[] | undefined, from: number, to: number): AverageGrowth | null {
  const inRange = pointsInRange(points, from, to);
  if (!inRange.length) return null;
  const product = inRange.reduce((total, [, rate]) => total * (1 + rate / 100), 1);
  return { value: (Math.pow(product, 1 / inRange.length) - 1) * 100, from: inRange[0][0], to: inRange[inRange.length - 1][0], years: inRange.length };
}

/** 水準の系列（一人あたりGDPなど）から、期間の最初と最後の年の年平均伸び率（％）を求めます。 */
export function levelGrowth(points: YearValue[] | undefined, from: number, to: number): AverageGrowth | null {
  const inRange = pointsInRange(points, from, to);
  if (inRange.length < 2) return null;
  const [firstYear, firstValue] = inRange[0], [lastYear, lastValue] = inRange[inRange.length - 1];
  return { value: (Math.pow(lastValue / firstValue, 1 / (lastYear - firstYear)) - 1) * 100, from: firstYear, to: lastYear, years: lastYear - firstYear };
}

export type GrowthBasis = 'real' | 'perCapita';
export type GrowthRow = { code: string; name: string; rank: number; growth: AverageGrowth };

/** 選んだ期間の年平均成長率の順位。値の無い国は順位に入れません。 */
export function growthRanking(snapshot: WorldGdpSnapshot, from: number, to: number, basis: GrowthBasis = 'real'): GrowthRow[] {
  const rows = snapshot.countries.flatMap(country => {
    const growth = basis === 'real' ? averageGrowth(country.series.realGrowth, from, to) : levelGrowth(country.series.perCapitaPpp, from, to);
    return growth ? [{ code: country.code, name: country.name, growth }] : [];
  });
  return rows.sort((a, b) => b.growth.value - a.growth.value || a.code.localeCompare(b.code)).map((row, index) => ({ ...row, rank: index + 1 }));
}

export type LatestRow = { code: string; name: string; rank: number; year: number; value: number };

/** 各国の最新年の値の順位。国ごとに最新年が違うときは、その年を併記します。 */
export function latestRanking(snapshot: WorldGdpSnapshot, metric: WorldMetric): LatestRow[] {
  const rows = snapshot.countries.flatMap(country => {
    const points = country.series[metric];
    if (!points?.length) return [];
    const [year, value] = points[points.length - 1];
    return [{ code: country.code, name: country.name, year, value }];
  });
  return rows.sort((a, b) => b.value - a.value || a.code.localeCompare(b.code)).map((row, index) => ({ ...row, rank: index + 1 }));
}

/** 軸の目盛り（線形）。 */
export function linearTicks(min: number, max: number, count = 5): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [];
  if (min === max) return [min];
  const rough = (max - min) / count;
  const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
  const step = [1, 2, 2.5, 5, 10].map(m => m * magnitude).find(s => s >= rough) ?? magnitude * 10;
  const ticks: number[] = [];
  for (let tick = Math.ceil(min / step) * step; tick <= max + step * 1e-9; tick += step) ticks.push(Math.round(tick / step) * step);
  return ticks;
}

/** 軸の目盛り（対数）。10の累乗と、間が広いときは2倍・5倍も入れます。 */
export function logTicks(min: number, max: number): number[] {
  if (!(min > 0) || !(max > 0) || min > max) return [];
  const low = Math.floor(Math.log10(min)), high = Math.ceil(Math.log10(max));
  const multipliers = high - low <= 2 ? [1, 2, 5] : [1];
  const ticks: number[] = [];
  for (let power = low; power <= high; power++) for (const m of multipliers) {
    const tick = m * Math.pow(10, power);
    if (tick >= min && tick <= max) ticks.push(tick);
  }
  return ticks;
}

export function formatUsd(value: number): string {
  const n = (v: number, digits: number) => new Intl.NumberFormat('ja-JP', { maximumFractionDigits: digits }).format(v);
  if (value >= 1e12) return `${n(value / 1e12, value >= 1e13 ? 1 : 2)}兆ドル`;
  if (value >= 1e8) return `${n(value / 1e8, 0)}億ドル`;
  return `${n(value / 1e4, 0)}万ドル`;
}
export const formatPpp = (value: number) => `${new Intl.NumberFormat('ja-JP', { maximumFractionDigits: 0 }).format(value)}国際ドル`;
export const formatRate = (value: number) => `${value > 0 ? '+' : value < 0 ? '−' : ''}${Math.abs(value).toFixed(1)}％`;
export function formatMetric(metric: WorldMetric, value: number): string {
  return metric === 'nominalUsd' ? formatUsd(value) : metric === 'perCapitaPpp' ? formatPpp(value) : metric === 'realGdp' ? value.toFixed(0) : formatRate(value);
}

export type GrowthCauseSource = { title: string; url: string };
export type GrowthCauseClaim = { id: string; factor: string; claim: string; japanContrast: string; sources: GrowthCauseSource[] };
export type GrowthCauseCountry = { code: string; name: string; summary: string; claims: GrowthCauseClaim[] };
export type GrowthCauses = { countries: GrowthCauseCountry[]; method: string };

const httpsOnly = (text: unknown) => {
  if (typeof text !== 'string') return false;
  try { const url = new URL(text); return url.protocol === 'https:' && !url.username && !url.password; } catch { return false; }
};

/** 成長要因の調査結果を読みます。形が崩れていれば拒否し、https 以外の出典は表示から外します。 */
export function parseGrowthCauses(value: unknown): GrowthCauses {
  if (!plainObject(value) || !Array.isArray(value.countries) || typeof value.method !== 'string') throw new Error('成長要因の形式が不正です。');
  const ids = new Set<string>();
  const countries = value.countries.map(country => {
    if (!plainObject(country) || typeof country.code !== 'string' || !/^[A-Z]{3}$/.test(country.code) || !prose(country.name, 40) || !prose(country.summary, 4000) || !Array.isArray(country.claims)) throw new Error('成長要因の国の項目が不正です。');
    const claims = country.claims.map(claim => {
      if (!plainObject(claim) || ![claim.id, claim.factor, claim.claim].every(item => prose(item, 4000)) || typeof claim.japanContrast !== 'string' || claim.japanContrast.length > 4000 || ids.has(claim.id as string) || !Array.isArray(claim.sources)) throw new Error('成長要因の主張が不正です。');
      ids.add(claim.id as string);
      const sources = claim.sources.filter((source): source is GrowthCauseSource => plainObject(source) && prose(source.title, 500) && httpsOnly(source.url));
      return { id: claim.id as string, factor: claim.factor as string, claim: claim.claim as string, japanContrast: (claim.japanContrast as string).trim(), sources };
    });
    return { code: country.code, name: country.name as string, summary: country.summary as string, claims };
  });
  return { countries, method: value.method };
}
