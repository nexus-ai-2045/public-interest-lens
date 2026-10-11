import { useEffect, useState, type KeyboardEvent } from 'react';
import { ProductHeader } from './ProductHeader';
import { distributionCaseUrl, parsePublicCase, type PublicCase } from './public-distribution';

const steps = [
  { id: 'implementation', label: '実施' },
  { id: 'observation', label: '観測された結果' },
  { id: 'comparison', label: '比較と反証' },
  { id: 'actors', label: '誰が何をしたか' },
  { id: 'missing', label: '不足している資料' },
] as const;
type StepId = typeof steps[number]['id'];

export function CaseChain({ initialStep = 'implementation' }: { initialStep?: StepId }) {
  const [record, setRecord] = useState<PublicCase | null>(null);
  const [error, setError] = useState('');
  const [step, setStep] = useState<StepId>(initialStep);
  const edition = new URLSearchParams(window.location.search).get('edition') ?? '';
  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      try {
        const response = await fetch(distributionCaseUrl(edition), { signal: controller.signal, cache: 'no-store' });
        if (!response.ok) throw new Error('missing');
        const value = parsePublicCase(await response.text());
        if (edition && value.snapshotId !== edition) throw new Error('mismatch');
        if (!controller.signal.aborted) { setRecord(value); setError(''); }
      } catch {
        if (!controller.signal.aborted) { setRecord(null); setError(edition ? '指定された配布版を読めませんでした。別の版へは置き換えません。' : '公開の政策事例を読み込めませんでした。'); }
      }
    })();
    return () => controller.abort();
  }, [edition]);
  const move = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    const next = event.key === 'ArrowRight' ? (index + 1) % steps.length : event.key === 'ArrowLeft' ? (index + steps.length - 1) % steps.length : event.key === 'Home' ? 0 : event.key === 'End' ? steps.length - 1 : null;
    if (next === null) return;
    event.preventDefault();
    setStep(steps[next].id);
    document.getElementById(`case-tab-${steps[next].id}`)?.focus();
  };
  if (error) return <p role="alert">{error}</p>;
  if (!record) return <p>政策事例を読み込んでいます。</p>;
  return <article className="case-chain" aria-labelledby="case-title">
    <p className="state-banner">公開配布版です。非公開の原本には接続していません。採点は0件で、影響の規模は保留です。</p>
    <h3 id="case-title">{record.title}</h3>
    <p>{record.periodNote}</p>
    <p>{record.holdReason}</p>
    <div className="case-steps" role="tablist" aria-label="政策の調べ方">
      {steps.map((item, index) => <button key={item.id} id={`case-tab-${item.id}`} type="button" role="tab" aria-selected={step === item.id} tabIndex={step === item.id ? 0 : -1} onKeyDown={event => move(event, index)} onClick={() => setStep(item.id)}>{item.label}</button>)}
    </div>
    <div role="tabpanel" aria-labelledby={`case-tab-${step}`}>
      {step === 'implementation' && record.implementations.map(item => <section key={item.id}><h4>{item.date}</h4><p>{item.text}</p></section>)}
      {step === 'observation' && <>{record.observations.map(item => <section key={item.id}><p>{item.text}</p><p className="fine-note">{item.method === 'before_after_not_causal' ? '前後の変化です。それだけでは実績点にしません。' : '資料に書かれた数値です。この画面では計算し直していません。'}</p></section>)}</>}
      {step === 'comparison' && <><h4>どこまで比べられたか</h4><p>{record.comparison}</p><h4>まだ潰せていない説明</h4><ul>{record.counterEvidence.map(item => <li key={item}>{item}</li>)}</ul><h4>原因候補（未確立）</h4><ul>{record.causeCandidates.map(item => <li key={item.id}>{item.label}</li>)}</ul><p>{record.statisticLink.note}</p><a href="/history?years=40">40年の統計に戻る</a></>}
      {step === 'actors' && <>
        <h4>資料にある行動</h4>
        <ul>{record.actors.map(actor => <li key={actor.id}><strong>{actor.label}</strong>（{actor.date}）<p>{actor.action}</p><p className="fine-note">{actor.identityNote} 点数は付けていません。</p></li>)}</ul>
        <h4>機関・集団</h4>
        <ul>{record.organizations.map(org => <li key={org.id}><strong>{org.name}</strong><p>{org.relation}</p></li>)}</ul>
        <h4>名簿にあるだけで、行動としては未確認</h4>
        <ul>{record.contextMentions.map(item => <li key={item.id}>{item.label}。{item.basis}</li>)}</ul>
      </>}
      {step === 'missing' && <ul>{record.missingMaterials.map(item => <li key={item}>{item}</li>)}</ul>}
    </div>
    <details><summary>出典と引用箇所</summary><ul>{record.citations.map(item => <li key={item.id}><a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a><p>{item.locator}</p><blockquote>{item.quote}</blockquote><p className="fine-note">{item.license}</p></li>)}</ul><p className="fine-note">配布版の識別子は詳細に置きます。</p><code>{record.snapshotId}</code></details>
  </article>;
}

export function ActorsPage() {
  useEffect(() => { document.title = '人物と団体｜国賊／国士ランキング'; }, []);
  return <div className="app-shell research-page" data-theme="light"><ProductHeader title="人物と団体" label="採点していません"><nav aria-label="主なページ"><a href="/history">長期推移</a><a href="/policies">政策と結果</a><a href="/actors">人物・団体</a><a href="/evaluation">保存評価版</a><a href="/ranking">架空ランキング</a></nav></ProductHeader><main><h2>資料に残った行動と、点数にしない関係</h2><p>所属、名簿、会見での説明は、影響の点数ではありません。保存済みの評価版は別の入口です。</p><CaseChain initialStep="actors" /></main></div>;
}
