CREATE TABLE releases (
    releaseId TEXT PRIMARY KEY,
    originalSha256 TEXT NOT NULL
);
CREATE TABLE policies (
    policyId TEXT PRIMARY KEY,
    formalTitle TEXT NOT NULL,
    summary TEXT NOT NULL,
    officialUrl TEXT NOT NULL,
    originalSha256 TEXT NOT NULL
);
CREATE TABLE people (
    personId TEXT PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE source_materials (
    materialId TEXT PRIMARY KEY,
    officialUrl TEXT NOT NULL,
    originalSha256 TEXT NOT NULL,
    contentSha256 TEXT NOT NULL
);
CREATE TABLE actions (
    releaseId TEXT NOT NULL REFERENCES releases,
    actionId TEXT NOT NULL,
    personId TEXT NOT NULL REFERENCES people,
    policyId TEXT NOT NULL REFERENCES policies,
    date TEXT NOT NULL,
    position TEXT NOT NULL,
    PRIMARY KEY (releaseId, actionId)
);
CREATE TABLE action_sources (
    releaseId TEXT NOT NULL,
    actionId TEXT NOT NULL,
    materialId TEXT NOT NULL REFERENCES source_materials,
    PRIMARY KEY (releaseId, actionId, materialId),
    FOREIGN KEY (releaseId, actionId) REFERENCES actions
);
CREATE TABLE policy_originals (
    policyId TEXT PRIMARY KEY REFERENCES policies,
    recordPath TEXT NOT NULL,
    originalPath TEXT NOT NULL,
    originalSha256 TEXT NOT NULL
);
CREATE TABLE policy_text (
    policyId TEXT PRIMARY KEY REFERENCES policies,
    summaryStatus TEXT NOT NULL,
    sourceExcerpt TEXT
);
