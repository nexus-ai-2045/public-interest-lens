from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.sangiin_bills import _Rows, _bill_id_from_url


POLICY_FIELDS = ("policyId", "formalTitle", "summary", "officialUrl", "originalSha256")
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")


def verify_release(release_bytes: bytes) -> None:
    module_url = (Path(__file__).parent / "evidence_pipeline.mjs").resolve().as_uri()
    source = (
        f"import {{ buildReviewPacket }} from {json.dumps(module_url)};"
        "let input=''; for await (const chunk of process.stdin) input += chunk;"
        "try { buildReviewPacket(JSON.parse(input)); } catch { process.exitCode=1; }"
    )
    result = subprocess.run(["node", "--input-type=module", "-e", source],
                            input=release_bytes, capture_output=True, timeout=30)
    if result.returncode:
        raise ValueError("release canonical hash or contract mismatch")


def policy_source(payload: bytes, url: str) -> tuple[dict, str | None]:
    charset = re.search(rb"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", payload[:8192], re.I)
    encoding = charset.group(1).decode("ascii") if charset else "utf-8"
    if encoding.lower().replace("_", "-") not in {"utf-8", "shift-jis", "sjis", "cp932", "euc-jp"}:
        raise ValueError("unsupported original charset")
    html = payload.decode(encoding, errors="strict")
    cleaned = re.sub(r"<(script|style|nav|header|footer)\b[^>]*>.*?</\1\s*>",
                     "", html, flags=re.I | re.S)
    expected_session, expected_number = _bill_id_from_url(url)
    source_rows = _Rows()
    source_rows.feed(cleaned)
    cells = {}
    for row in source_rows.rows:
        for index in range(len(row) - 1):
            if row[index][0] == "th" and row[index + 1][0] == "td":
                cells.setdefault(row[index][1], row[index + 1][1])
    if cells.get("提出回次") != f"{expected_session}回" or cells.get("提出番号") != expected_number:
        raise ValueError("original policy identifier mismatch")
    parsed = {"billId": f"{expected_session}-{expected_number}",
              "title": text_field(cells, "件名")}
    match = re.search(r'<table\b[^>]*\bsummary\s*=\s*[\"\']議案要旨情報[\"\'][^>]*>(.*?)</table\s*>',
                      cleaned, flags=re.I | re.S)
    if not match:
        return parsed, None
    rows = _Rows()
    rows.feed(re.sub(r"<br\s*/?>", "\n", match.group(1), flags=re.I))
    for row in rows.rows:
        if len(row) == 1 and row[0][0] == "td" and row[0][1] and not row[0][2]:
            return parsed, row[0][1][:6000]
    return parsed, None


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def text_field(value: dict, key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip():
        raise ValueError(f"missing or invalid {key}")
    return result


def hash_field(value: dict, key: str) -> str:
    result = text_field(value, key)
    if not HASH_PATTERN.fullmatch(result):
        raise ValueError(f"invalid hash: {key}")
    return result


def unique_rows(value: object, key: str) -> dict[str, dict]:
    if not isinstance(value, list):
        raise ValueError(f"array required: {key}")
    rows = {}
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"object required: {key}")
        identifier = text_field(item, key)
        if identifier in rows:
            raise ValueError(f"duplicate {key}")
        rows[identifier] = item
    return rows


def verify_policy(candidate: dict, metadata_path: Path) -> tuple[dict, tuple]:
    policy = {key: text_field(candidate, key) for key in POLICY_FIELDS}
    expected_hash = hash_field(policy, "originalSha256")
    url = urlparse(policy["officialUrl"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("invalid officialUrl")
    record_path = Path(text_field(candidate, "recordPath"))
    if not record_path.is_absolute():
        record_path = metadata_path.parent / record_path
    record_path = record_path.resolve(strict=True)
    record = read_object(record_path)
    if record.get("schema_version") != "external-material/v1":
        raise ValueError("invalid original record schema")
    if record.get("sha256") != expected_hash:
        raise ValueError("original record hash mismatch")
    if record.get("source_url") != policy["officialUrl"]:
        raise ValueError("original record URL mismatch")
    saved_filename = text_field(record, "saved_filename")
    original = (record_path.parent / saved_filename).resolve(strict=True)
    if original.parent != record_path.parent or Path(saved_filename).name != saved_filename:
        raise ValueError("invalid saved_filename")
    original_bytes = original.read_bytes()
    if hashlib.sha256(original_bytes).hexdigest() != expected_hash:
        raise ValueError("original bytes hash mismatch")
    if type(record.get("bytes")) is not int or record["bytes"] != len(original_bytes):
        raise ValueError("original byte count mismatch")
    parsed, excerpt = policy_source(original_bytes, policy["officialUrl"])
    if parsed["billId"] != policy["policyId"]:
        raise ValueError("policy identifier mismatch")
    if parsed["title"] != policy["formalTitle"]:
        raise ValueError("formal title mismatch")
    policy["summaryStatus"] = "unverified_explanation"
    if excerpt is not None:
        policy["sourceExcerpt"] = excerpt
    return policy, (policy["policyId"], str(record_path), str(original), expected_hash)


def validated_catalog(release_path: Path, metadata_path: Path) -> tuple:
    release_bytes = release_path.read_bytes()
    release = json.loads(release_bytes)
    if not isinstance(release, dict) or release.get("schemaVersion") != "evidence-release/v1":
        raise ValueError("invalid release schema")
    verify_release(release_bytes)
    release_id = text_field(release, "releaseId")
    evidence = release.get("input", {}).get("evidenceEvaluation")
    if not isinstance(evidence, dict):
        raise ValueError("missing evidence evaluation")
    candidates = unique_rows(read_object(metadata_path).get("metadataCandidates"), "policyId")
    if not candidates:
        raise ValueError("empty policies")
    policies, originals = [], []
    for candidate in candidates.values():
        policy, original = verify_policy(candidate, metadata_path)
        policies.append(policy)
        originals.append(original)
    people = unique_rows(evidence.get("people"), "id")
    actions = unique_rows(evidence.get("actions"), "actionId")
    materials = unique_rows(evidence.get("materials"), "id")
    person_rows = [(identifier, text_field(person, "name"))
                   for identifier, person in people.items()]
    material_rows = [(identifier, text_field(material, "url"),
                      hash_field(material, "originalHash"), hash_field(material, "contentHash"))
                     for identifier, material in materials.items()]
    action_rows, source_rows = [], []
    for action_id, action in actions.items():
        person_id = text_field(action, "personId")
        policy_id = text_field(action, "policyId")
        if person_id not in people or policy_id not in candidates:
            raise ValueError("action references unknown person or policy")
        action_rows.append((release_id, action_id, person_id, policy_id,
                            text_field(action, "actionDate"), text_field(action, "position")))
        quotes = action.get("quotes", [])
        if not isinstance(quotes, list):
            raise ValueError("quotes array required")
        source_ids = set()
        for quote in quotes:
            source_id = text_field(quote, "materialId")
            if source_id not in materials:
                raise ValueError("action references unknown source")
            source_ids.add(source_id)
        source_rows.extend((release_id, action_id, source_id) for source_id in sorted(source_ids))
    context = {"schemaVersion": "policy-context/v1", "releaseId": release_id,
               "policies": sorted(policies, key=lambda policy: policy["policyId"])}
    return (context, hashlib.sha256(release_bytes).hexdigest(), originals,
            person_rows, material_rows, action_rows, source_rows)


def write_database(path: Path, catalog: tuple) -> None:
    context, release_hash, originals, people, materials, actions, sources = catalog
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript("""
            CREATE TABLE releases (releaseId TEXT PRIMARY KEY, originalSha256 TEXT NOT NULL);
            CREATE TABLE policies (policyId TEXT PRIMARY KEY, formalTitle TEXT NOT NULL,
                summary TEXT NOT NULL, officialUrl TEXT NOT NULL, originalSha256 TEXT NOT NULL);
            CREATE TABLE policy_originals (policyId TEXT PRIMARY KEY REFERENCES policies,
                recordPath TEXT NOT NULL, originalPath TEXT NOT NULL, originalSha256 TEXT NOT NULL);
            CREATE TABLE policy_text (policyId TEXT PRIMARY KEY REFERENCES policies,
                summaryStatus TEXT NOT NULL, sourceExcerpt TEXT);
            CREATE TABLE people (personId TEXT PRIMARY KEY, name TEXT NOT NULL);
            CREATE TABLE source_materials (materialId TEXT PRIMARY KEY, officialUrl TEXT NOT NULL,
                originalSha256 TEXT NOT NULL, contentSha256 TEXT NOT NULL);
            CREATE TABLE actions (releaseId TEXT NOT NULL REFERENCES releases,
                actionId TEXT NOT NULL, personId TEXT NOT NULL REFERENCES people,
                policyId TEXT NOT NULL REFERENCES policies, date TEXT NOT NULL,
                position TEXT NOT NULL, PRIMARY KEY (releaseId, actionId));
            CREATE TABLE action_sources (releaseId TEXT NOT NULL, actionId TEXT NOT NULL,
                materialId TEXT NOT NULL REFERENCES source_materials,
                PRIMARY KEY (releaseId, actionId, materialId),
                FOREIGN KEY (releaseId, actionId) REFERENCES actions);
        """)
        connection.execute("INSERT INTO releases VALUES (?, ?)",
                           (context["releaseId"], release_hash))
        connection.executemany("INSERT INTO policies VALUES (?, ?, ?, ?, ?)",
                               [tuple(policy[key] for key in POLICY_FIELDS)
                                for policy in context["policies"]])
        connection.executemany("INSERT INTO policy_originals VALUES (?, ?, ?, ?)", originals)
        connection.executemany("INSERT INTO policy_text VALUES (?, ?, ?)",
                               [(policy["policyId"], policy["summaryStatus"], policy.get("sourceExcerpt"))
                                for policy in context["policies"]])
        connection.executemany("INSERT INTO people VALUES (?, ?)", people)
        connection.executemany("INSERT INTO source_materials VALUES (?, ?, ?, ?)", materials)
        connection.executemany("INSERT INTO actions VALUES (?, ?, ?, ?, ?, ?)", actions)
        connection.executemany("INSERT INTO action_sources VALUES (?, ?, ?)", sources)
        connection.commit()
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("database integrity check failed")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("database relation check failed")
    finally:
        connection.close()


def build_catalog(release: Path, metadata: Path, output_root: Path) -> dict:
    catalog = validated_catalog(release, metadata)
    context = catalog[0]
    serialized = json.dumps(context, ensure_ascii=False, indent=2) + "\n"
    output_root.mkdir(parents=True, exist_ok=True)
    (output_root / "generations").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="catalog-", dir=output_root) as temporary:
        stage = Path(temporary)
        staged_generation = stage / "generation"
        staged_generation.mkdir()
        database = staged_generation / "catalog.sqlite3"
        write_database(database, catalog)
        staged_json = staged_generation / "context.json"
        staged_json.write_text(serialized, encoding="utf-8")
        database_hash = hashlib.sha256(database.read_bytes()).hexdigest()
        context_hash = hashlib.sha256(staged_json.read_bytes()).hexdigest()
        generation_id = hashlib.sha256((database_hash + context_hash).encode()).hexdigest()
        generation = output_root / "generations" / generation_id
        if generation.exists():
            for name, expected in (("catalog.sqlite3", database_hash), ("context.json", context_hash)):
                if hashlib.sha256((generation / name).read_bytes()).hexdigest() != expected:
                    raise ValueError("existing immutable generation mismatch")
        else:
            os.replace(staged_generation, generation)
        manifest = {"schemaVersion": "policy-catalog-current/v1", "releaseId": context["releaseId"],
                    "generation": generation_id,
                    "contextPath": f"generations/{generation_id}/context.json",
                    "databasePath": f"generations/{generation_id}/catalog.sqlite3",
                    "contextSha256": context_hash, "databaseSha256": database_hash}
        staged_manifest = stage / "current.json"
        staged_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        os.replace(staged_manifest, output_root / "current.json")
    return {"status": "ready", "releaseId": context["releaseId"],
            "policies": len(context["policies"]), "people": len(catalog[3]),
            "actions": len(catalog[5]), "sources": len(catalog[4]),
            "databasePath": str((generation / "catalog.sqlite3").resolve()),
            "contextPath": str((generation / "context.json").resolve()),
            "manifestPath": str((output_root / "current.json").resolve()),
            "generation": generation_id, "databaseSha256": database_hash,
            "contextSha256": context_hash}


def main() -> int:
    parser = argparse.ArgumentParser(description="保存済み資料から非公開の政策カタログを再構築します")
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build_catalog(args.release, args.metadata, args.output_root)
    except (ValueError, OSError, TypeError, AttributeError, sqlite3.Error,
            subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
