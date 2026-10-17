import growthCausesData from './growth-causes.json';
import { parseGrowthCauses, type GrowthCauses as GrowthCausesData } from './world-gdp';

function load(): GrowthCausesData | null {
  try { return parseGrowthCauses(growthCausesData); } catch { return null; }
}

/** 伸びている国の要因と、日本との違い。調査結果が空のあいだは何も表示しません。 */
export function GrowthCauses({ data = load() }: { data?: GrowthCausesData | null }) {
  if (!data || !data.countries.length) return null;
  return <div className="growth-causes">
    <h3>伸びている国は、なぜ伸びたのか</h3>
    {data.method && <p className="fine-note growth-causes-method">{data.method}</p>}
    {data.countries.map(country => <article key={country.code} className="growth-cause-country">
      <h4>{country.name}</h4>
      <p className="growth-cause-summary">{country.summary}</p>
      {country.claims.map(claim => <section key={claim.id} className="growth-cause-claim" aria-label={`${country.name}：${claim.factor}`}>
        <h5>{claim.factor}</h5>
        <p>{claim.claim}</p>
        {claim.japanContrast && <p className="growth-cause-japan"><strong>日本では：</strong>{claim.japanContrast}</p>}
        {claim.sources.length > 0 && <details><summary>出典を確認する</summary><ul>{claim.sources.map(source => <li key={source.url}><a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a></li>)}</ul></details>}
      </section>)}
    </article>)}
  </div>;
}
