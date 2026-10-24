import { type EvidenceAction, type EvidenceEvaluationInput, type EvidenceEvaluationResult } from './evidence-evaluation';
export declare const REAL_RELEASE_MAX_BYTES = 5000000;
export declare function realActionHeading(action: Pick<EvidenceAction, 'namespace' | 'policyId' | 'actionDate' | 'position' | 'description'>): string;
export type RealRelease = {
    schemaVersion: 'evidence-release/v1';
    engineHash: string;
    releaseId: string;
    input: {
        evidenceEvaluation: EvidenceEvaluationInput;
        materialRefs: {
            id: string;
            originalHash: string;
            selector: Record<string, unknown>;
        }[];
    };
    result: EvidenceEvaluationResult;
    publicationStatus: 'requires_human_review';
    verification?: unknown;
};
export type RealRoute = {
    dataset: 'real' | 'fiction';
    release: string;
    person: string;
};
/** SHAは保存版の整合性だけを検査します。独立検証や公開承認を生成しません。 */
export declare function parseRealRelease(text: string): Promise<RealRelease>;
export declare function readRealRoute(search: string, pathname?: string): RealRoute;
export declare function realRouteLocation(route: RealRoute): string;
export declare function realRouteSearch(route: RealRoute): string;
export declare const availableRealRelease: (route: RealRoute, release: RealRelease | null) => RealRelease | null;
/** 保存された照合記録の件数です。ブラウザで再検証した件数ではありません。 */
export declare function recordedIdentityCoverage(release: RealRelease): {
    matched: number;
    unresolved: number;
} | null;
/** 非同期読込の最後の選択だけを採用し、不正入力では前正常版を保ちます。 */
export declare function createReleaseLoader(onValid: (release: RealRelease) => void, onError: (message: string) => void): {
    cancel: () => void;
    load: (file: {
        size: number;
        text: () => Promise<string>;
    }, expectedRelease?: string) => Promise<void>;
};
