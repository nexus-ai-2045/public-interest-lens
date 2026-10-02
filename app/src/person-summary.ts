import { rankPeople, type RankingDataset, type RankingOptions } from './ranking';

export type PersonSummary = {
  benefit: number | null;
  harm: number | null;
  trend: 'benefit_lead' | 'harm_lead' | 'balanced' | 'benefit_only' | 'harm_only' | 'insufficient';
  label: string;
};

/** 独立算定済みの貢献・悪影響を並べる表示要約。差引点数や別順位は作らない。 */
export function getPersonSummaries(data: RankingDataset, options: RankingOptions, assessment: 'actions' | 'outlook' = 'actions'): Map<string, PersonSummary> {
  const benefitRows = rankPeople(data, { ...options, direction: 'benefit' });
  const harmRows = rankPeople(data, { ...options, direction: 'harm' });
  const benefits = new Map(benefitRows.map(row => [row.person.id, row.score]));
  const harms = new Map(harmRows.map(row => [row.person.id, row.score]));
  return new Map(data.people.map(person => {
    const benefit = assessment === 'outlook' ? null : benefits.get(person.id) ?? null;
    const harm = assessment === 'outlook' ? null : harms.get(person.id) ?? null;
    let trend: PersonSummary['trend'];
    let label: string;
    if (benefit === null && harm === null) { trend = 'insufficient'; label = '判断材料不足'; }
    else if (harm === null) { trend = 'benefit_only'; label = '貢献の記録あり・悪影響は未評価'; }
    else if (benefit === null) { trend = 'harm_only'; label = '悪影響の記録あり・貢献は未評価'; }
    else if (benefit > harm) { trend = 'benefit_lead'; label = '貢献優勢'; }
    else if (benefit < harm) { trend = 'harm_lead'; label = '悪影響優勢'; }
    else { trend = 'balanced'; label = '同程度'; }
    return [person.id, { benefit, harm, trend, label }];
  }));
}
