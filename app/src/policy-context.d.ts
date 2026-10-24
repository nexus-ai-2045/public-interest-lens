export type PolicyContext = {
    policyId: string;
    formalTitle: string;
    summary: string;
    officialUrl: string;
    originalSha256: string;
    sourceExcerpt?: string;
    summaryStatus?: 'unverified_explanation';
};
export type PolicyCatalog = {
    schemaVersion: 'policy-context/v1';
    releaseId: string;
    policies: PolicyContext[];
};
export declare function parsePolicyCatalog(text: string, expectedRelease: string): PolicyCatalog;
