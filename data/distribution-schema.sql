CREATE TABLE distribution_releases (
    releaseId TEXT PRIMARY KEY,
    schemaVersion TEXT NOT NULL
);
CREATE TABLE statistic_series (
    releaseId TEXT NOT NULL REFERENCES distribution_releases(releaseId),
    seriesId TEXT NOT NULL,
    label TEXT NOT NULL,
    unit TEXT NOT NULL,
    license TEXT NOT NULL,
    sourceUrl TEXT NOT NULL,
    PRIMARY KEY (releaseId, seriesId)
);
CREATE TABLE statistic_points (
    releaseId TEXT NOT NULL,
    seriesId TEXT NOT NULL,
    year INTEGER NOT NULL,
    value REAL,
    PRIMARY KEY (releaseId, seriesId, year),
    FOREIGN KEY (releaseId, seriesId) REFERENCES statistic_series(releaseId, seriesId)
);
CREATE TABLE cause_candidates (
    releaseId TEXT NOT NULL REFERENCES distribution_releases(releaseId),
    causeId TEXT NOT NULL,
    label TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status = 'unestablished'),
    PRIMARY KEY (releaseId, causeId)
);
CREATE TABLE policy_cases (
    releaseId TEXT NOT NULL REFERENCES distribution_releases(releaseId),
    caseId TEXT NOT NULL,
    title TEXT NOT NULL,
    scoringStatus TEXT NOT NULL CHECK (scoringStatus = 'held'),
    impactScale TEXT CHECK (impactScale IS NULL),
    PRIMARY KEY (releaseId, caseId)
);
CREATE TABLE implementations (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    itemId TEXT NOT NULL,
    statedOn TEXT NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (releaseId, itemId),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId)
);
CREATE TABLE observations (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    observationId TEXT NOT NULL,
    summary TEXT NOT NULL,
    method TEXT NOT NULL,
    PRIMARY KEY (releaseId, observationId),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId)
);
CREATE TABLE counterevidence (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    itemId TEXT NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (releaseId, itemId),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId)
);
CREATE TABLE actor_actions (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    actionId TEXT NOT NULL,
    actorLabel TEXT NOT NULL,
    actionDate TEXT NOT NULL,
    actionKind TEXT NOT NULL,
    summary TEXT NOT NULL,
    score REAL CHECK (score IS NULL),
    PRIMARY KEY (releaseId, actionId),
    UNIQUE (releaseId, caseId, actorLabel, actionDate, actionKind),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId)
);
CREATE TABLE organizations (
    releaseId TEXT NOT NULL REFERENCES distribution_releases(releaseId),
    orgId TEXT NOT NULL,
    name TEXT NOT NULL,
    PRIMARY KEY (releaseId, orgId)
);
CREATE TABLE organization_links (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    orgId TEXT NOT NULL,
    relationKind TEXT NOT NULL CHECK (relationKind IN ('publisher', 'advisory_context', 'observed_aggregate')),
    summary TEXT NOT NULL,
    score REAL CHECK (score IS NULL),
    PRIMARY KEY (releaseId, caseId, orgId, relationKind),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId),
    FOREIGN KEY (releaseId, orgId) REFERENCES organizations(releaseId, orgId)
);
CREATE TABLE context_mentions (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    mentionId TEXT NOT NULL,
    label TEXT NOT NULL,
    basis TEXT NOT NULL,
    score REAL CHECK (score IS NULL),
    PRIMARY KEY (releaseId, mentionId),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId)
);
CREATE TABLE citations (
    releaseId TEXT NOT NULL REFERENCES distribution_releases(releaseId),
    citationId TEXT NOT NULL,
    url TEXT NOT NULL,
    license TEXT NOT NULL,
    locator TEXT NOT NULL,
    quote TEXT NOT NULL,
    PRIMARY KEY (releaseId, citationId)
);
CREATE TABLE action_citations (
    releaseId TEXT NOT NULL,
    actionId TEXT NOT NULL,
    citationId TEXT NOT NULL,
    PRIMARY KEY (releaseId, actionId, citationId),
    FOREIGN KEY (releaseId, actionId) REFERENCES actor_actions(releaseId, actionId),
    FOREIGN KEY (releaseId, citationId) REFERENCES citations(releaseId, citationId)
);
CREATE TABLE missing_materials (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    itemId TEXT NOT NULL,
    summary TEXT NOT NULL,
    PRIMARY KEY (releaseId, itemId),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId)
);
CREATE TABLE series_case_links (
    releaseId TEXT NOT NULL,
    caseId TEXT NOT NULL,
    seriesId TEXT NOT NULL,
    relationKind TEXT NOT NULL CHECK (relationKind = 'temporal_overlap_not_attribution'),
    note TEXT NOT NULL,
    PRIMARY KEY (releaseId, caseId, seriesId, relationKind),
    FOREIGN KEY (releaseId, caseId) REFERENCES policy_cases(releaseId, caseId),
    FOREIGN KEY (releaseId, seriesId) REFERENCES statistic_series(releaseId, seriesId)
);
