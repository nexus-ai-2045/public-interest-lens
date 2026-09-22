import type { RankingDataset } from './ranking';

/** 全内容が動作検証用の創作。確認済みという分類も架空シナリオ内の状態。 */
export const rankingDataset: RankingDataset = {
  fictional: true,
  people: [
    { id: 'fiction-a', name: '架空議員あおい' },
    { id: 'fiction-b', name: '架空議員べに' },
    { id: 'fiction-c', name: '架空議員こはく' },
    { id: 'fiction-d', name: '架空議員だいだい' },
  ],
  evidence: [
    { id: 'e-policy', title: '架空の政策検証記録', date: '2024-03-01', kind: 'verified', source: 'fixture:policy-review', summary: '画面検証専用の創作資料。実在する統計・国会記録ではありません。' },
    { id: 'e-action', title: '架空の関与確認記録', date: '2024-03-02', kind: 'verified', source: 'fixture:involvement-review', summary: '架空の提案・役職を確認したというテスト用設定です。' },
    { id: 'e-pending', title: '架空の未確認情報', date: '2024-03-03', kind: 'unknown', source: 'fixture:pending', summary: '根拠未確認のため算定対象から除外します。' },
  ],
  policies: [
    { id: 'policy-p', title: '架空の設備更新制度', year: 1995, domain: 'productivity', harm: 90, causalConfidence: .8, reviewStatus: 'reviewed', rationale: '架空シナリオで設備更新の遅延を評価。係数は動作検証用の仮置きです。', counterEvidence: '架空の一部業種では更新が進んだ設定です。', alternativeExplanation: '海外需要の低下も代替要因として残します。', evidenceIds: ['e-policy'] },
    { id: 'policy-i', title: '架空の所得配分制度', year: 2005, domain: 'income', harm: 80, causalConfidence: .9, reviewStatus: 'reviewed', rationale: '架空シナリオで所得への悪影響を評価。係数は仮置きです。', counterEvidence: '架空の一部世帯には利益がある設定です。', alternativeExplanation: '人口構成の変化も代替要因です。', evidenceIds: ['e-policy'] },
    { id: 'policy-f', title: '架空の財政配分制度', year: 2015, domain: 'fiscal', harm: 60, causalConfidence: .6, reviewStatus: 'reviewed', rationale: '架空シナリオで財政配分の影響を評価。係数は仮置きです。', counterEvidence: '短期的な需要増もある設定です。', alternativeExplanation: '景気循環の影響を分離できない設定です。', evidenceIds: ['e-policy'] },
  ],
  involvements: [
    { personId: 'fiction-a', policyId: 'policy-p', role: '架空の提案者', attribution: 1, evidenceIds: ['e-action'] },
    { personId: 'fiction-a', policyId: 'policy-i', role: '架空の共同提案者', attribution: .2, evidenceIds: ['e-action'] },
    { personId: 'fiction-b', policyId: 'policy-i', role: '架空の提案者', attribution: 1, evidenceIds: ['e-action'] },
    { personId: 'fiction-b', policyId: 'policy-p', role: '架空の共同提案者', attribution: .1, evidenceIds: ['e-action'] },
    { personId: 'fiction-c', policyId: 'policy-f', role: '架空の担当者', attribution: .7, evidenceIds: ['e-action'] },
    { personId: 'fiction-d', policyId: 'policy-f', role: '関与未確認', attribution: .5, evidenceIds: ['e-pending'] },
  ],
};
