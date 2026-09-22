import { useMemo, useState } from 'react';
import { BookOpen, ChevronRight, Info, Scale, SlidersHorizontal } from 'lucide-react';
import { DOMAINS, RANKING_VERSION, rankPeople, type Domain } from './ranking';
import { rankingDataset as data } from './ranking-data';
import { evidenceLabel } from './scoring';

const labels: Record<Domain, string> = { productivity: '生産性', income: '所得', fiscal: '財政' };
const initialWeights = { productivity: 1, income: 1, fiscal: 1 };
const years = Array.from({ length: 51 }, (_, i) => 1976 + i);
const scoreText = (score: number | null) => score === null ? '未評価' : score.toFixed(2);

function App() {
  const [weights, setWeights] = useState(initialWeights);
  const [fromYear, setFromYear] = useState(1976);
  const [toYear, setToYear] = useState(2026);
  const [query, setQuery] = useState('');
  const [personId, setPersonId] = useState(data.people[0].id);
  const [policyId, setPolicyId] = useState(data.policies[0].id);
  const rows = useMemo(() => rankPeople(data, { weights, fromYear, toYear }), [weights, fromYear, toYear]);
  const baseline = useMemo(() => rankPeople(data, { weights: initialWeights, fromYear, toYear }), [fromYear, toYear]);
  const visible = rows.filter(row => row.person.name.includes(query.trim()));
  const selected = visible.find(row => row.person.id === personId) ?? visible[0];
  const related = data.involvements.filter(i => i.personId === selected?.person.id).map(involvement => ({ involvement, policy: data.policies.find(p => p.id === involvement.policyId)! })).filter(({ policy }) => policy.year >= fromYear && policy.year <= toYear).sort((a, b) => a.policy.year - b.policy.year);
  const detail = related.find(item => item.policy.id === policyId) ?? related[0];
  const evidenceIds = new Set(detail ? [...detail.policy.evidenceIds, ...detail.involvement.evidenceIds] : []);
  const evidence = data.evidence.filter(item => evidenceIds.has(item.id));
  const total = DOMAINS.reduce((sum, domain) => sum + weights[domain], 0);
  const contribution = selected?.contributions.find(item => item.policyId === detail?.policy.id);

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="#top"><span className="brand-mark"><Scale size={19} /></span>公益レンズ<span className="prototype-label">架空データ版</span></a>
      <nav aria-label="主要ナビゲーション"><a href="#ranking">人物ランキング</a><a href="#axes">評価の重み</a><a href="#evidence">政策と根拠</a><a href="#method">算定方法</a></nav>
    </header>
    <main id="top">
      <section className="hero"><div><p className="eyebrow">国会・立法の検証へ</p><h1>政策の結果と、<br />人物の責任をたどる。</h1></div><div className="hero-note"><Info size={22} /><p><strong>全員・全政策・全資料が架空です。</strong><br />人物ワーストランキングの動作検証版です。数値も仮置きで、実在議員の評価や日本の停滞原因を示すものではありません。</p></div></section>
      <section className="panel scope-controls" aria-label="ランキング対象の絞り込み">
        <label>開始年<select value={fromYear} onChange={e => { const year = Number(e.target.value); setFromYear(year); if (year > toYear) setToYear(year); }}>{years.map(year => <option key={year}>{year}</option>)}</select></label>
        <label>終了年<select value={toYear} onChange={e => { const year = Number(e.target.value); setToYear(year); if (year < fromYear) setFromYear(year); }}>{years.map(year => <option key={year}>{year}</option>)}</select></label>
        <label className="search-control">人物名で検索<input type="search" value={query} onChange={e => setQuery(e.target.value)} placeholder="架空議員の名前" /></label>
        <p>期間は政策年に適用。検索は表示のみを絞り、順位は変えません。</p>
      </section>
      <section id="ranking" className="dashboard-grid ranking-grid">
        <section className="panel comparison-panel"><div className="panel-heading"><div><p className="section-kicker">個人別・悪影響への関与</p><h2>人物ワーストランキング</h2></div><span className="updated">{fromYear}〜{toYear}年</span></div>
          <div className="table-wrap"><table><caption className="sr-only">累積責任スコアが高い順。未評価は責任なしを意味しません。</caption><thead><tr><th scope="col">順位</th><th scope="col">人物</th><th scope="col">累積スコア</th><th scope="col">均等重み順位</th><th scope="col">算定対象 / 対象政策</th></tr></thead><tbody>{visible.map(row => <tr key={row.person.id} className={selected?.person.id === row.person.id ? 'selected-row' : ''}><td>{row.rank ?? '—'}</td><td><button className="person-select" aria-pressed={selected?.person.id === row.person.id} onClick={() => setPersonId(row.person.id)}>{row.person.name}</button></td><td><span className="score">{scoreText(row.score)}</span></td><td>{baseline.find(b => b.person.id === row.person.id)?.rank ?? '未評価'}</td><td>{row.eligibleCount} / {row.eligibleCount + row.omittedCount}<small>証拠・レビュー不足 {row.omittedCount}件</small></td></tr>)}</tbody></table></div>
          {!visible.length && <p className="empty-state" role="status">該当する人物がいません。検索条件を変更してください。</p>}
          <p className="method-note">高いほど悪影響への関与が大きいという仮定の計算です。対象件数は収録した関与政策のみで、全国の網羅率ではありません。同点は同順位。</p>
          {total === 0 && <p className="empty-state" role="status">重みがすべて0のため、全員未評価です。</p>}
        </section>
        <aside id="axes" className="panel weights-panel"><div className="panel-heading"><div><p className="section-kicker">感度分析</p><h2>重みを調整</h2></div><SlidersHorizontal size={19} /></div><p className="panel-description">均等重みの順位と比較できます。表示する割合は入力値の合計で正規化した構成比です。</p>{DOMAINS.map(domain => <label className="weight-control" key={domain}><span><strong>{labels[domain]}</strong><output>{total ? (weights[domain] / total * 100).toFixed(1) + '%' : '割合なし'}</output></span><input aria-label={`${labels[domain]}の重み`} type="range" min="0" max="100" value={weights[domain]} onChange={e => setWeights({ ...weights, [domain]: Number(e.target.value) })} /><small>入力値 {weights[domain]} / 100</small></label>)}<button className="reset-button" onClick={() => setWeights({ ...initialWeights })}>均等重みに戻す</button>{selected && <div className="selected-score"><span>{selected.person.name}</span><strong>{scoreText(selected.score)}</strong></div>}</aside>
      </section>
      <section id="evidence" className="evidence-section"><div className="section-title-row"><div><p className="section-kicker">政策単位で根拠を確認</p><h2>{selected ? selected.person.name + 'の政策と根拠' : '政策と根拠'}</h2></div></div>
        {!detail ? <p className="panel empty-state">選択条件に対応する政策がありません。政策がないことは責任がない証明ではありません。</p> : <div className="evidence-grid policy-grid">
          <aside className="panel evidence-list" aria-label="選択人物の政策">{related.map(({ policy, involvement }) => <button key={policy.id} className={detail.policy.id === policy.id ? 'selected' : ''} aria-pressed={detail.policy.id === policy.id} onClick={() => setPolicyId(policy.id)}><BookOpen size={20} /><span className="evidence-copy"><small>{policy.year}年 · {labels[policy.domain]}</small><strong>{policy.title}</strong><span>{involvement.role}</span></span><ChevronRight size={16} /></button>)}</aside>
          <article className="panel evidence-detail"><div className="detail-meta"><span className="status-badge computed">機械計算・架空設定</span><span>{detail.policy.year}年</span></div><h3>{detail.policy.title}</h3><p>{detail.policy.rationale}</p><dl className="policy-metrics"><div><dt>悪影響度（仮置き）</dt><dd>{detail.policy.harm}</dd></div><div><dt>因果係数（人間設定）</dt><dd>{detail.policy.causalConfidence}</dd></div><div><dt>帰属係数（人間設定）</dt><dd>{detail.involvement.attribution}</dd></div><div><dt>この政策の寄与点</dt><dd>{total === 0 ? '重み未設定' : contribution ? contribution.score.toFixed(2) : '算定対象外'}</dd></div></dl><p><strong>関与：</strong>{detail.involvement.role}</p><p><strong>レビュー：</strong>{detail.policy.reviewStatus === 'reviewed' ? '架空シナリオ内でレビュー済み' : '未レビュー'}</p><p><strong>反証：</strong>{detail.policy.counterEvidence}</p><p><strong>別の説明：</strong>{detail.policy.alternativeExplanation}</p>{!contribution && <p className="exclusion-note">証拠またはレビューが不足しているため算定対象外です。「責任なし」の評価ではありません。</p>}
          </article>
          <aside className="panel timeline-panel"><p className="section-kicker">出典までたどる</p><h3>選択政策・人物の根拠</h3>{evidence.map(item => <article className="source-card" key={item.id}><span className={`status-badge ${item.kind}`}>{evidenceLabel(item.kind)}（架空設定）</span><strong>{item.title}</strong><small>{item.date}</small><p>{item.summary}</p><code>{item.source}</code></article>)}<p className="timeline-note">すべてローカルの創作資料です。確認済み分類も架空シナリオ内の状態で、実在する原資料へのリンクではありません。</p></aside>
        </div>}
      </section>
      <section id="method" className="panel method-panel"><p className="section-kicker">算定方法と限界</p><h2>政策から人物へ、同じ政策を一度だけ集計</h2><p>累積責任スコア = Σ（悪影響度 × 因果係数 × 人物への帰属係数 × 分野の重み / 全分野の重み合計）。合計後に小数第2位へ丸め、その表示点で降順・同点同順位にします。累積値に100点の上限はありません。</p><p>人間レビュー済みの政策と個人の関与が、いずれも確認済み分類の資料で裏付けられた場合のみ算定します。AI解釈・未確認・機械計算だけの資料では算定せず、発言回数を政策数に置き換えません。</p><p>因果係数と帰属係数は人間が置く仮定で、統計的な確率でも因果関係の証明でもありません。対象期間・資料の不足・代替要因によって評価は変わります。実在データの調査、評価基準の妥当性検証、人間レビューと公開承認は未実施です。</p><p className="version">算定版：{RANKING_VERSION}</p></section>
    </main>
    <footer><span><Scale size={16} />公益レンズ — 人物の評価と根拠を公開情報から検証する。</span><span>架空データによる動作検証版</span></footer>
  </div>;
}
export default App;
