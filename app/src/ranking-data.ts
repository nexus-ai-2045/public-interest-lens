import type { RankingDataset } from './ranking';

/** UIと算定契約の確認専用。人物・政策・資料は全て創作。 */
export const rankingDataset: RankingDataset = {
  schemaVersion: 'ranking-dataset/v1',
  fictional: true,
  asOf: '2026-09-24',
  coverage: { scope: '架空の候補者4人・政策4件のみ', assessedPeople: 3, targetPeople: null, sourceStatus: '全資料が創作。実在資料は未接続' },
  people: [
    { id: 'fiction-a', name: '架空議員あおい', house: '衆議院', district: '架空第1区', electionIds: ['fiction-election-1'], roleClass: '一般議員' },
    { id: 'fiction-b', name: '架空議員べに', house: '参議院', district: '架空選挙区', electionIds: ['fiction-election-2'], roleClass: '一般議員' },
    { id: 'fiction-c', name: '架空議員こはく', house: '衆議院', district: '架空第2区', electionIds: ['fiction-election-1'], roleClass: '大臣' },
    { id: 'fiction-d', name: '架空候補だいだい', house: '衆議院', district: '架空第3区', electionIds: ['fiction-election-1'], roleClass: '非在職' },
  ],
  evidence: [
    { id: 'e-impact-e', title: '架空の経済影響検証', date: '2024-05-01', kind: 'verified', source: 'fixture:economy-impact', summary: '創作上の影響評価。実在の研究・統計ではありません。' },
    { id: 'e-impact-t', title: '架空の技術影響検証', date: '2025-01-01', kind: 'verified', source: 'fixture:technology-impact', summary: '創作上の技術影響評価。' },
    { id: 'e-action-a', title: '架空の法案提出記録', date: '2024-05-02', kind: 'verified', source: 'fixture:action-a', summary: '架空人物の提出行動を確認した設定。' },
    { id: 'e-action-a-vote', title: '架空の個人採決記録（二件目）', date: '2025-01-02', kind: 'verified', source: 'fixture:action-a-vote', summary: '同じ架空政策について、別の日に個人採決で賛成した設定。' },
    { id: 'e-action-b', title: '架空の政策決定記録', date: '2024-06-02', kind: 'verified', source: 'fixture:action-b', summary: '架空人物の政策決定を確認した設定。' },
    { id: 'e-action-c', title: '架空の個人採決記録', date: '2025-02-02', kind: 'verified', source: 'fixture:action-c', summary: '架空人物の個人賛否を確認した設定。' },
    { id: 'e-unknown', title: '架空の未確認情報', date: '2025-03-02', kind: 'unknown', source: 'fixture:unknown', summary: '確認不能のため採点しない設定。' },
  ],
  policies: [
    { id: 'policy-harm-e', title: '架空の設備投資制限制', domain: 'economy', direction: 'harm', impact: 3, reviewStatus: 'reviewed', rationale: '創作上、民間設備投資への悪影響を検討。', counterEvidence: '一部業種への便益もある設定。', alternativeExplanation: '海外需要の低下も考えられる設定。', evidenceIds: ['e-impact-e'] },
    { id: 'policy-good-e', title: '架空の新規参入支援策', domain: 'economy', direction: 'benefit', impact: 2, reviewStatus: 'reviewed', rationale: '創作上、新規参入の促進を検討。', counterEvidence: '既存事業者の負担もある設定。', alternativeExplanation: '景気循環も影響する設定。', evidenceIds: ['e-impact-e'] },
    { id: 'policy-good-t', title: '架空の研究開発促進策', domain: 'technology', direction: 'benefit', impact: 3, reviewStatus: 'reviewed', rationale: '創作上、研究開発への寄与を検討。', counterEvidence: '短期の費用増もある設定。', alternativeExplanation: '海外技術の流入も影響する設定。', evidenceIds: ['e-impact-t'] },
    { id: 'policy-hold', title: '架空の影響未検証策', domain: 'economy', direction: 'harm', impact: 1, reviewStatus: 'pending', rationale: '影響根拠が不足した設定。', counterEvidence: '反証未検証。', alternativeExplanation: '代替要因未検証。', evidenceIds: ['e-unknown'] },
  ],
  involvements: [
    { personId: 'fiction-a', policyId: 'policy-harm-e', actionDate: '2024-09-24', role: 'lead', description: '架空の法案を主導して提出', evidenceIds: ['e-action-a'] },
    { personId: 'fiction-a', policyId: 'policy-harm-e', actionDate: '2025-01-01', role: 'vote', description: '架空の個人採決で賛成', evidenceIds: ['e-action-a-vote'] },
    { personId: 'fiction-b', policyId: 'policy-good-e', actionDate: '2024-10-01', role: 'lead', description: '架空の政策決定に関与', evidenceIds: ['e-action-b'] },
    { personId: 'fiction-c', policyId: 'policy-good-t', actionDate: '2025-02-01', role: 'vote', description: '架空の個人採決で賛成', evidenceIds: ['e-action-c'] },
    { personId: 'fiction-d', policyId: 'policy-hold', actionDate: '2025-03-01', role: 'context', description: '架空の団体所属のみ', evidenceIds: ['e-unknown'] },
  ],
};
