/** 表示用派生データ。実人物データは検証・公開審査済みの別経路からのみ接続する。 */
export declare const RANKING_VERSION = "fictional-actions-v1";
export declare const DOMAINS: readonly ['economy', 'technology', 'fiscal', 'security', 'governance'];
export type Domain = typeof DOMAINS[number];
export type RankedDomain = 'economy' | 'technology' | 'overall';
export type Direction = 'benefit' | 'harm';
export type Period = 2 | 4 | 8 | 30 | 40 | 'custom' | 'cumulative';
export type RankingEvidence = {
    id: string;
    title: string;
    date: string;
    kind: 'verified' | 'computed' | 'ai' | 'unknown';
    source: string;
    summary: string;
    url?: string;
    locator?: string;
    sha256?: string;
};
export type Person = {
    id: string;
    name: string;
    house?: string;
    district?: string;
    electionIds?: string[];
    roleClass?: string;
    actorType?: 'person' | 'organization';
};
export type Policy = {
    id: string;
    title: string;
    domain: Domain;
    direction: Direction;
    impact: 1 | 2 | 3;
    reviewStatus: 'reviewed' | 'pending';
    rationale: string;
    counterEvidence: string;
    alternativeExplanation: string;
    evidenceIds: string[];
};
export type Involvement = {
    id?: string;
    personId: string;
    policyId: string;
    actionDate: string;
    role: 'lead' | 'coauthor' | 'vote' | 'context';
    description: string;
    evidenceIds: string[];
};
export type RankingDataset = {
    schemaVersion: 'ranking-dataset/v1';
    fictional: boolean;
    asOf: string;
    coverage: {
        scope: string;
        assessedPeople: number;
        targetPeople: number | null;
        sourceStatus: string;
    };
    people: Person[];
    policies: Policy[];
    involvements: Involvement[];
    evidence: RankingEvidence[];
    held?: {
        personId?: string;
        policyId?: string;
        reason: string;
        sourceRefs?: string[];
    }[];
};
export type RankingOptions = {
    domain: Domain | 'overall';
    direction: Direction;
    period: Period;
    asOf: string;
    weights: {
        economy: number;
        technology: number;
    };
    dateFrom?: string;
    dateTo?: string;
    timeBasis?: 'action' | 'outcome';
    actorGroup?: 'people' | 'organizations';
};
export type RankingContribution = {
    policyId: string;
    actionKey: string;
    actionDate: string;
    role: Involvement['role'];
    score: number;
    outcomeId?: string;
};
export type RankingRow = {
    person: Person;
    score: number | null;
    rank: number | null;
    eligibleCount: number;
    heldCount: number;
    contributions: RankingContribution[];
};
export declare const ROLE_FACTOR: Record<Involvement['role'], number>;
/** 一つの政策に複数の異なる行動がある場合も選択先を区別する。 */
export declare const actionKey: (action: Involvement) => string;
/** 入力検証は呼出し側の契約で行い、集計だけを共通化する。 */
export declare const sumRounded: (values: number[]) => number | null;
export declare function assignRanks(rows: RankingRow[]): RankingRow[];
/** 表示条件への一致だけを判定する。保留・参考行動も含み、算定資格は判定しない。 */
export declare function actionMatchesView(action: Involvement, policy: Policy, options: RankingOptions): boolean;
/** 全資料が創作である表示fixtureだけを計算する。実人物への適用は別の検証済み入口が必要。 */
export declare function rankPeople(data: RankingDataset, options: RankingOptions): RankingRow[];
