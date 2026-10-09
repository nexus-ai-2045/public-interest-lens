import { useEffect, useState } from 'react';
import { ProductHeader } from './ProductHeader';
import { CaseChain } from './CaseChain';
import { parsePolicyCatalog, type PolicyCatalog } from './policy-context';
import { parseRealRelease, type RealRelease } from './real-release-view';

export function PoliciesPage() {
  useEffect(() => { document.title = '政策と結果｜国賊／国士ランキング'; }, []);
  const [catalog, setCatalog] = useState<PolicyCatalog | null>(null);
  const [release, setRelease] = useState<RealRelease | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    const requested = new URLSearchParams(window.location.search).get('release');
    void (async () => {
      try {
        const response = await fetch(`/__local__/evaluation${requested ? `?release=${encodeURIComponent(requested)}` : ''}`, { signal: controller.signal });
        if (!response.ok) throw new Error();
        const version = await parseRealRelease(await response.text());
        if (requested && requested !== version.releaseId) throw new Error();
        const context = await fetch(`/__local__/policy-context?release=${version.releaseId}`, { signal: controller.signal });
        if (!context.ok) throw new Error();
        const policies = parsePolicyCatalog(await context.text(), version.releaseId);
        if (!controller.signal.aborted) { setCatalog(policies); setRelease(version); }
      } catch { if (!controller.signal.aborted) setError('議案と評価版を読み込めませんでした。指定された版は別版に置き換えません。'); }
    })();
    return () => controller.abort();
  }, []);
  return <div className="app-shell research-page" data-theme="light"><ProductHeader title="政策と結果" label="何が変わり、どうなったか"><nav aria-label="主なページ"><a href="/history">長期推移</a><a href="/policies">政策と結果</a><a href="/actors">人物・団体</a><a href="/ranking">ランキング</a></nav></ProductHeader><main><h2>一つの施策で、実施から人物の行動まで</h2><p>法律の成立、実施、観測された変化、比較できない部分は別に確認します。下の公開事例は採点済みではありません。</p><CaseChain />{error && <p role="status">保存済みの国会評価版は、この環境では読めません。上の公開事例は、その代わりではありません。</p>}{catalog?.policies.map(policy => {
    const actions = release?.input.evidenceEvaluation.actions.filter(action => action.policyId === policy.policyId) ?? [];
    const assessments = release?.input.evidenceEvaluation.assessments.filter(assessment => assessment.policyId === policy.policyId) ?? [];
    return <article key={policy.policyId} className="lower-panel"><h3>{policy.formalTitle}</h3><p>{policy.summary}</p>{policy.summaryStatus === 'unverified_explanation' && <p className="fine-note">短い説明は内容確認中の説明候補です。下の公式要旨と区別してください。</p>}{policy.sourceExcerpt ? <details open><summary>公式資料の議案要旨</summary><blockquote style={{ whiteSpace: 'pre-wrap' }}>{policy.sourceExcerpt}</blockquote></details> : <p>公式要旨はまだ収録されていません。</p>}<h4>誰がどう投票しましたか？</h4><p>この保存版にある行動記録：{actions.length}件。</p>{actions.length > 0 && <a href={`/evaluation?release=${catalog.releaseId}`}>人物ごとの投票を調べる</a>}<h4>実際の効果は確認できていますか？</h4>{assessments.length ? assessments.map(assessment => <section key={assessment.id}><h5>保存された分析候補・内容未確認</h5><p>{assessment.evaluationKind === 'forecast' ? '将来の見込みです。実績ではありません。' : assessment.evaluationKind === 'observed' ? '観測結果を扱う分析候補です。独立検証の完了をこの画面では認定しません。' : '予測か実績かの区分は、この旧保存記録にはありません。'}</p><p>{assessment.rationale}</p><p>反証：{assessment.counterEvidence}</p><p>ほかの説明：{assessment.alternativeExplanation}</p></section>) : <p>実際の効果を採点できる分析は、まだこの保存版にありません。成立や賛成票だけで「良い政策」とは判定しません。</p>}<a href={policy.officialUrl} target="_blank" rel="noopener noreferrer">国会の公式資料を開く</a></article>;
  })}</main></div>;
}
