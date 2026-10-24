export type EconomicSeries = {
    id: string;
    label: string;
    unit: string;
    basis: string;
    sourceUrl: string;
    points: {
        year: number;
        value: number | null;
    }[];
};
export type OutcomeCandidate = {
    id: string;
    title: string;
    observationFrom: string;
    observationTo: string;
    implementation: string;
    observedResult: string;
    contribution: string;
    counterEvidence: string;
    reviewStatus: 'draft';
    impact: null;
    actors: {
        name: string;
        action: string;
        attributionStatus: 'source_mention_not_individual_impact';
    }[];
    sources: {
        title: string;
        url: string;
    }[];
};
export type EconomicSnapshot = {
    schemaVersion: 'economic-series/v1';
    observedAt: string;
    provider: string;
    country: 'JPN';
    series: EconomicSeries[];
    unavailable: string[];
    note: string;
    outcomes?: OutcomeCandidate[];
    snapshotId?: string;
};
export declare function parseEconomicSnapshot(text: string): EconomicSnapshot;
export declare function selectEconomicPeriod(series: EconomicSeries, period: string, from?: number, to?: number): {
    year: number;
    value: number | null;
}[];
