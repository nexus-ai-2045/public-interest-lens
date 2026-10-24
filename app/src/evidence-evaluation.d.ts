import { type Direction, type Involvement, type Person, type RankingOptions, type RankingRow } from './ranking';
export type ActionIdentity = {
    namespace: string;
    sourceActionId: string;
    sourceActorId: string;
    policyId: string;
};
export declare function sha256(text: string): Promise<string>;
export declare const actionIdentity: (action: ActionIdentity) => Promise<string>;
export declare const actionRevision: (semanticContent: unknown) => Promise<string>;
export type QuoteRef = {
    materialId: string;
    start: number;
    end: number;
    text: string;
};
export type Material = {
    id: string;
    url: string;
    originalHash: string;
    contentHash: string;
    observedAt: string;
    publishedAt: string | null;
};
export type EvidenceAction = ActionIdentity & {
    actionId: string;
    revisionId: string;
    personId: string;
    policyVersion: string;
    actionDate: string;
    role: Involvement['role'];
    position: 'for' | 'against' | 'not_voted' | 'unknown';
    description: string;
    quotes: QuoteRef[];
    interventionId?: string;
    outcomeId?: string;
};
export type PositionAssessment = {
    id: string;
    policyId: string;
    policyVersion: string;
    position: 'for' | 'against';
    domain: 'economy' | 'technology';
    direction: Direction;
    impact: 1 | 2 | 3;
    rationale: string;
    counterEvidence: string;
    alternativeExplanation: string;
    criterionVersion: string;
    analysisVersion: string;
    evaluatedAt: string;
    quotes: QuoteRef[];
    outcomeId?: string;
    observationFrom?: string;
    observationTo?: string;
    implementationStatus?: 'implemented' | 'not_implemented';
    evaluationKind?: 'observed' | 'forecast';
    evidenceMethod?: 'quantitative' | 'contribution_analysis' | 'association';
    scopeReason?: string;
    durationReason?: string;
    magnitudeReason?: string;
};
export type EvidenceEvaluationInput = {
    schemaVersion: 'evidence-evaluation/v1';
    mode: 'real' | 'test-only';
    options: RankingOptions;
    people: Person[];
    materials: Material[];
    actions: EvidenceAction[];
    assessments: PositionAssessment[];
};
export type TrustedContext = {
    readMaterial: (id: string) => Promise<({
        text: string;
    } & Omit<Material, 'id'>) | null>;
    resolvedPersonIds: ReadonlySet<string>;
    verifiedActionIds: ReadonlySet<string>;
    verifiedAssessmentIds: ReadonlySet<string>;
    verifiedActionRevisions: ReadonlyMap<string, string>;
    verifiedAssessmentRevisions: ReadonlyMap<string, string>;
};
export type HeldReason = {
    personId?: string;
    policyId?: string;
    actionId?: string;
    reason: string;
};
export type EvidenceEvaluationResult = {
    mode: 'real' | 'test-only';
    rows: RankingRow[];
    held: HeldReason[];
    coverage: {
        inputActions: number;
        assessedActions: number;
        readableMaterials: number;
    };
    publicationStatus: 'requires_human_review';
};
export declare const assessmentRevision: (assessment: PositionAssessment) => Promise<string>;
export declare function evaluateEvidence(input: EvidenceEvaluationInput, trusted: TrustedContext): Promise<EvidenceEvaluationResult>;
