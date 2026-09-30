import { FileText } from 'lucide-react';
import { actionKey, actionMatchesView, type Involvement, type Policy, type RankingDataset, type RankingEvidence, type RankingOptions } from './ranking';
import type { ViewState } from './view-state';

type PolicyFlowProps = {
  data: RankingDataset;
  related: { action: Involvement; policy: Policy }[];
  options?: RankingOptions;
  selectedActionKey: string;
  selectedPolicyId: string;
  selectedEvidenceId: string;
  onSelect: (patch: Partial<ViewState>) => void;
};

const roleLabels: Record<Involvement['role'], string> = {
  lead: '主導・決定', coauthor: '共同提出・具体的修正',
  vote: '確認できる個人の賛否', context: '関係情報のみ',
};

function EvidenceButton({ evidence, selected, onSelect }: {
  evidence: RankingEvidence; selected: boolean; onSelect: () => void;
}) {
  return <button className="flow-source" aria-label={`根拠ノードを選択：${evidence.title}`} aria-pressed={selected} onClick={onSelect}>
    <FileText size={18} aria-hidden="true" />
    <strong>{evidence.title}</strong>
    <span className="flow-date">資料公開日 {evidence.date}</span>
  </button>;
}

/** 記録済みの政策・各行動・各根拠を分ける。採点の重複排除とは独立した履歴表示。 */
export function PolicyFlow({ data, related, options, selectedActionKey, selectedPolicyId, selectedEvidenceId, onSelect }: PolicyFlowProps) {
  const policies = [...new Map(related.map(item => [item.policy.id, item.policy])).values()];
  const evidenceById = new Map(data.evidence.map(item => [item.id, item]));
  const references = (ids: string[]) => ids.flatMap(id => {
    const evidence = evidenceById.get(id);
    return evidence ? [evidence] : [];
  });

  return <section className="policy-flow" aria-label="政策と行動のつながり">
    <div className="flow-heading"><h3>政策と行動のつながり</h3></div>
    {policies.map(policy => {
      const actions = related.filter(item => item.policy.id === policy.id).map(item => item.action).sort((a, b) => a.actionDate.localeCompare(b.actionDate));
      return <section className="flow-group" key={policy.id} aria-label={`${policy.title}の記録`}>
        <button className="flow-policy" aria-label={`政策ノードを選択：${policy.title}`} aria-pressed={selectedPolicyId === policy.id} onClick={() => onSelect({ selectedPolicyId: policy.id, selectedActionKey: actionKey(actions[0]), selectedEvidenceId: '', tab: 'policy' })}>
          <span className="flow-label">政策</span><strong>{policy.title}</strong>
          <span className="review-state">{policy.reviewStatus === 'reviewed' ? '架空設定内で評価可能' : '評価保留'}</span>
        </button>
        <svg className="flow-join" viewBox="0 0 100 28" preserveAspectRatio="none" aria-hidden="true"><path d={actions.length === 2 ? 'M50 0V14M25 28V14H75V28' : 'M50 0V28'} /></svg>
        <div className={`flow-branches ${actions.length === 2 ? '' : 'single-flow'}`}>
          {actions.map(action => <div className="flow-branch" key={actionKey(action)}>
            <button className={`flow-action ${selectedActionKey === actionKey(action) ? 'selected' : ''}`} aria-pressed={selectedActionKey === actionKey(action)} onClick={() => onSelect({ selectedActionKey: actionKey(action), selectedPolicyId: policy.id, selectedEvidenceId: '', tab: 'actions' })}>
              <span className="flow-meta"><span className="flow-label">行動</span><span className="flow-date">{action.actionDate}</span></span>
              <strong>{roleLabels[action.role]}</strong>
              <span className="sr-only">{policy.title}</span><span>{action.description}</span>
              {options && !actionMatchesView(action, policy, options) && <span className="outside-view-note">現在の条件外</span>}
            </button>
            <div className="flow-evidence" aria-label="この行動の根拠">
              <span className="flow-label">行動の根拠</span>
              {references(action.evidenceIds).map(evidence => <EvidenceButton key={evidence.id} evidence={evidence} selected={selectedEvidenceId === evidence.id} onSelect={() => onSelect({ selectedActionKey: actionKey(action), selectedPolicyId: policy.id, selectedEvidenceId: evidence.id, tab: 'evidence' })} />)}
              {!action.evidenceIds.length && <p>行動の根拠は未収録です。</p>}
            </div>
          </div>)}
        </div>
        <div className="flow-evidence flow-evidence-policy" aria-label="政策影響の根拠">
          <span className="flow-label">政策影響の根拠</span>
          {references(policy.evidenceIds).map(evidence => <EvidenceButton key={evidence.id} evidence={evidence} selected={selectedEvidenceId === evidence.id} onSelect={() => onSelect({ selectedPolicyId: policy.id, selectedActionKey: selectedPolicyId === policy.id ? selectedActionKey : actionKey(actions[0]), selectedEvidenceId: evidence.id, tab: 'evidence' })} />)}
        </div>
      </section>;
    })}
  </section>;
}
