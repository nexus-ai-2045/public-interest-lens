import { DEFAULT_ROLE_RATIO, buildExposureRanking, type ExposureGroup, type ExposureRanking, type Involvement } from './exposure-ranking';
import { SCORING_CONSTANTS } from './scoring-constants';

/**
 * 画面部品の確認用の架空データ。実在の人・会派・法律・額ではない。
 * テストと手元の画面確認だけで使い、公開データには混ぜない。
 */
const CHO = 1e12;
export const SAMPLE_GROUPS: ExposureGroup[] = [
  { kind: 'group-diff', id: 'G-info-2001', group: '架空の情報通信', window: '2001〜2010年', diff: { low: 20 * CHO, median: 30 * CHO, high: 42 * CHO }, benchmark: '架空の比較', lawCount: 6 },
  { kind: 'group-diff', id: 'G-retail-2011', group: '架空の小売', window: '2011〜2020年', diff: { low: 4 * CHO, median: 9 * CHO, high: 15 * CHO }, benchmark: '架空の比較', lawCount: 5 },
  { kind: 'group-diff', id: 'G-machine-2001', group: '架空の機械', window: '2001〜2010年', diff: { low: -12 * CHO, median: -8 * CHO, high: -3 * CHO }, benchmark: '架空の比較', lawCount: 6 },
  { kind: 'group-diff', id: 'G-empty-2011', group: '架空の運輸', window: '2011〜2020年', diff: { low: 1 * CHO, median: 2 * CHO, high: 3 * CHO }, benchmark: '架空の比較', lawCount: 3 },
];
export const SAMPLE_PERSON_NAMES: Record<string, string> = {
  P01: '架空 一郎', P02: '架空 二葉', P03: '架空 三奈', P04: '架空 四季', P05: '架空 五月', P06: '架空 六花', P07: '架空 七海',
};
export const SAMPLE_PARTY_NAMES: Record<string, string> = { A: '架空の会A', B: '架空の会B', C: '架空の会C', D: '架空の会D' };

function sampleInvolvements(): Involvement[] {
  const out: Involvement[] = [];
  const person = (actorId: string, groupId: string, lawId: string, role: Involvement['role'], weight = 1) => out.push({ actorKind: 'person', actorId, groupId, lawId, role, weight, house: 'upper' });
  const party = (actorId: string, groupId: string, lawId: string, role: Involvement['role'], weight = 1) => out.push({ actorKind: 'party', actorId, groupId, lawId, role, weight, house: 'lower' });
  for (let i = 1; i <= 6; i++) {
    const law = `info-${i}`;
    person('P01', 'G-info-2001', law, 'cabinet');
    person('P02', 'G-info-2001', law, 'cabinet');
    person(i <= 4 ? 'P01' : 'P03', 'G-info-2001', law, 'proposer');
    party('A', 'G-info-2001', law, 'yes', 3);
    party('B', 'G-info-2001', law, 'yes', 1);
    party('C', 'G-info-2001', law, 'no');
  }
  for (let i = 1; i <= 5; i++) {
    const law = `retail-${i}`;
    person('P03', 'G-retail-2011', law, 'proposer');
    person('P04', 'G-retail-2011', law, 'cabinet');
    person('P05', 'G-retail-2011', law, 'yes');
    party('A', 'G-retail-2011', law, 'yes', 2);
    if (i <= 2) party('D', 'G-retail-2011', law, 'yes', 1);
    if (i <= 2) person('P07', 'G-retail-2011', law, 'no');
    else party('C', 'G-retail-2011', law, 'no');
  }
  for (let i = 1; i <= 6; i++) {
    const law = `machine-${i}`;
    person('P06', 'G-machine-2001', law, 'proposer');
    person(i <= 3 ? 'P04' : 'P05', 'G-machine-2001', law, 'cabinet');
    party('B', 'G-machine-2001', law, 'yes');
    if (i <= 5) party('C', 'G-machine-2001', law, 'no');
  }
  return out;
}

export function sampleExposureRanking(): ExposureRanking {
  return buildExposureRanking(SAMPLE_GROUPS, sampleInvolvements(), { roleRatio: DEFAULT_ROLE_RATIO, minLaws: SCORING_CONSTANTS.minContributingLaws, topThreeShareCap: 1 /* 見本は法律が少ないので、占有率の条件は掛けない（画面部品の確認が目的） */ });
}
