export type LocalInspection = {
    readableEvidence?: ReadableEvidence;
    policySelection?: PolicySelection;
    asOf: string;
    scope: string;
    assessedPeople: number;
    sourceRecords: number | null;
    sourceStatus: 'capped' | 'query_exhausted' | 'pages_captured';
    held: {
        id: string;
        reason: string;
        sourceSpeechId: string | null;
        title: string | null;
        submittedAt: string | null;
        sourceUrl: string | null;
        voteUrl: string | null;
        observedAt: string | null;
        sha256: string | null;
    }[];
};
export type SelectedPolicy = {
    id: string;
    billId?: string;
    title: string;
    submittedAt: string;
    sourceUrl: string;
};
export type PolicySelection = {
    criterionVersion: 'research-digital-registered-pilot-v1';
    inventoryCompleteness: 'registered_candidates_only';
    asOf: string;
    scope: string;
    policies: SelectedPolicy[];
};
type SourceRecord = {
    id: string;
    date: string;
    text: string;
    sourceUrl: string;
    observedAt: string;
    sha256: string;
    locator: string;
};
export type ReadableEvidence = {
    verificationState: 'unverified';
    selectionScope: string;
    speeches: (SourceRecord & {
        speakerName: string;
    })[];
    votes: (SourceRecord & {
        nameText: string;
        position: 'for' | 'against' | 'not_voted' | 'unknown';
        title: string;
        policyId: string;
    })[];
    counts: {
        savedRecords: number;
        readableSpeechBodies: number;
        sourceVoteRows: number;
        confirmedActionEvidence: 0;
    };
};
/** 送信や評価をせず、表示に必要な公式資料メタデータだけを取り出す。 */
export declare function parseLocalInspection(text: string): LocalInspection;
export {};
