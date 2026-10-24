import katex from 'katex';
import 'katex/dist/katex.min.css';
import './numbers.css';
import { SPEC_DATE, SPEC_SECTIONS, SPEC_VERSION, STANDARD_METHODS, methodsOf, type SpecSection } from './method-spec';

/** LaTeX を KaTeX で描く。式は app/src/method-spec.ts の正本だけを使う（テストで全式を検査済み）。 */
function Tex({ tex, display = false }: { tex: string; display?: boolean }) {
  const html = katex.renderToString(tex, { displayMode: display, throwOnError: false, strict: 'ignore', output: 'htmlAndMathml' });
  return display ? <div className="spec-tex" dangerouslySetInnerHTML={{ __html: html }} /> : <span dangerouslySetInnerHTML={{ __html: html }} />;
}

function Section({ s }: { s: SpecSection }) {
  return <details className={`spec-section ${s.status === '案' ? 'draft' : ''}`} id={`spec-${s.id}`}>
    <summary><strong>{s.title}</strong><span className="spec-version">{[s.version, ...(s.alsoVersions ?? [])].join('・')}{s.status === '案' ? '（案）' : ''}</span></summary>
    <p>{s.lead}</p>
    {methodsOf(s.id).length > 0 && <p className="fine-note">定番の手法：{methodsOf(s.id).map(m => m.name).join('・')}</p>}
    {s.formulas.map((f, i) => <figure key={i} className="spec-formula">{f.note && <figcaption>{f.note}</figcaption>}<Tex tex={f.tex} display /></figure>)}
    {s.symbols.length > 0 && <table className="spec-symbols"><thead><tr><th scope="col">記号</th><th scope="col">意味</th></tr></thead>
      <tbody>{s.symbols.map(([sym, meaning]) => <tr key={sym}><td><Tex tex={sym} /></td><td>{meaning}</td></tr>)}</tbody></table>}
    {s.rules.length > 0 && <ul>{s.rules.map(r => <li key={r}>{r}</li>)}</ul>}
    <p className="fine-note">実装：{s.code.join('、')}</p>
  </details>;
}

export default function MethodFormulas() {
  return <section className="spec" aria-labelledby="formulas">
    <h3 id="formulas">6. 式（計算方法の仕様 {SPEC_VERSION}、{SPEC_DATE}）</h3>
    <p>上の手順を、記号の定義つきの式にしたものです。計算の仕方は版で固定し、変えるときは版を上げて、変えた理由と影響（上位がどう動くか）を<a href="https://github.com/nexus-ai-2045/public-interest-lens/blob/main/docs/adr/0013-calculation-spec-versioning.md" target="_blank" rel="noopener noreferrer">設計決定0013</a>に記録します。「案」は見直し中の式で、まだ計算に使っていません。</p>
    <h4 id="standard-methods">使っている定番の手法</h4>
    <p>この計算は、経済学・統計学・政治学で広く使われている次の6つの手法でできています。これ以外の独自の式は使っていません。</p>
    <table className="spec-symbols">
      <thead><tr><th scope="col">手法</th><th scope="col">何に使うか</th><th scope="col">出典</th><th scope="col">式</th></tr></thead>
      <tbody>{STANDARD_METHODS.map(m => <tr key={m.name}><td>{m.name}</td><td>{m.use}</td><td>{m.refs.join('／')}</td>
        <td>{m.sections.map((id, i) => <span key={id}>{i > 0 && '・'}<a href={`#spec-${id}`}>{SPEC_SECTIONS.find(x => x.id === id)?.title.replace(/（.*$/, '') ?? id}</a></span>)}</td></tr>)}</tbody>
    </table>
    {SPEC_SECTIONS.map(s => <Section key={s.id} s={s} />)}
  </section>;
}
