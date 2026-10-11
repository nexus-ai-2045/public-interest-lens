"""公開統計と、点数を付けない政策事例を配布版へ再生成する。

非公開の `.local` は読まない。入力は公開取得済みの世界銀行JSONと、引用付きの事例源だけ。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
from pathlib import Path

from scripts.build_economy_snapshot import build_snapshot

HASH = re.compile(r"[0-9a-f]{64}\Z")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
BANNED = {"score", "gdploss", "responsibilityshare", "impact", "impactscale", "recordpath", "internallog"}
ACTION_KINDS = {"announcement", "explanation", "progress_statement"}
ORG_KINDS = {"publisher", "advisory_context", "observed_aggregate"}
METHODS = {"before_after_not_causal", "stated_figure_not_recomputed"}


def select_years(points: list[dict], period: int) -> list[dict]:
    if period not in {2, 4, 8, 30, 40}:
        raise ValueError("期間が不正です")
    years = [point["year"] for point in points]
    if not years:
        raise ValueError("統計点がありません")
    latest = max(years)
    indexed = {point["year"]: point["value"] for point in points}
    return [{"year": year, "value": indexed.get(year)} for year in range(latest - period + 1, latest + 1)]


def _text(value: dict, key: str, limit: int = 4000) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result.strip() or len(result) > limit:
        raise ValueError(f"事例の文章が不正です: {key}")
    return result


def _walk_banned(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in BANNED:
                raise ValueError("点数・損失額・私的パスは配布版に置けません")
            _walk_banned(item)
    elif isinstance(value, list):
        for item in value:
            _walk_banned(item)


def _citation_map(case: dict) -> dict[str, dict]:
    rows = {}
    for item in case["citations"]:
        if not isinstance(item, dict):
            raise ValueError("出典が不正です")
        identifier = _text(item, "id", 80)
        if identifier in rows:
            raise ValueError("出典IDが重複しています")
        url = _text(item, "url", 500)
        parsed_host = url.split("/")[2] if url.startswith("https://") else ""
        if parsed_host != "www.fsa.go.jp" or "@" in url:
            raise ValueError("出典URLが不正です")
        rows[identifier] = item
        _text(item, "title", 300)
        _text(item, "license", 500)
        _text(item, "locator", 300)
        _text(item, "quote", 500)
    if len(rows) < 3:
        raise ValueError("出典が不足しています")
    return rows


def _refs(item: dict, citations: dict[str, dict]) -> list[str]:
    refs = item.get("citationIds")
    if not isinstance(refs, list) or not refs or any(not isinstance(ref, str) or ref not in citations for ref in refs):
        raise ValueError("出典参照が不正です")
    if len(refs) != len(set(refs)):
        raise ValueError("出典参照が重複しています")
    return refs


def load_case(path: Path) -> dict:
    case = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(case, dict):
        raise ValueError("事例の形式が不正です")
    _walk_banned(case)
    _text(case, "caseId", 80)
    _text(case, "title", 200)
    if not DATE.fullmatch(case.get("observationFrom", "")) or not DATE.fullmatch(case.get("observationTo", "")) or case["observationFrom"] > case["observationTo"]:
        raise ValueError("観測期間が不正です")
    _text(case, "holdReason")
    _text(case, "periodNote")
    _text(case, "comparison")
    citations = _citation_map(case)
    for key in ("implementations", "observations", "counterEvidence", "actors", "organizations", "contextMentions", "missingMaterials", "causeCandidates"):
        if not isinstance(case.get(key), list) or not case[key]:
            raise ValueError(f"事例の項目が不足しています: {key}")
    seen_actions = set()
    for action in case["actors"]:
        _text(action, "id", 80)
        _text(action, "label", 200)
        if not DATE.fullmatch(action.get("date", "")) or action.get("actionKind") not in ACTION_KINDS:
            raise ValueError("人物の行動が不正です")
        _text(action, "action")
        _text(action, "identityNote")
        _refs(action, citations)
        key = (action["label"], action["date"], action["actionKind"])
        if key in seen_actions:
            raise ValueError("同一人物・日付・行動種別の経路が重複しています")
        seen_actions.add(key)
    if len({action["label"] for action in case["actors"]}) < 3:
        raise ValueError("複数人物の行動が不足しています")
    for item in case["implementations"]:
        _text(item, "id", 80)
        if not DATE.fullmatch(item.get("date", "")):
            raise ValueError("実施日が不正です")
        _text(item, "text")
        _refs(item, citations)
    for item in case["observations"]:
        _text(item, "id", 80)
        _text(item, "text")
        if item.get("method") not in METHODS:
            raise ValueError("観測の方法が不正です")
        _refs(item, citations)
    for item in case["counterEvidence"]:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("反証が不正です")
    for item in case["organizations"]:
        _text(item, "id", 80)
        _text(item, "name", 200)
        if item.get("relationKind") not in ORG_KINDS:
            raise ValueError("団体の関係が不正です")
        _text(item, "relation")
    for item in case["contextMentions"]:
        _text(item, "id", 80)
        _text(item, "label", 300)
        _text(item, "basis")
        _refs(item, citations)
    for item in case["missingMaterials"]:
        if not isinstance(item, str) or len(item.strip()) < 8:
            raise ValueError("不足資料が不正です")
    for item in case["causeCandidates"]:
        _text(item, "id", 80)
        _text(item, "label")
    link = case.get("statisticLink")
    if not isinstance(link, dict) or link.get("seriesId") != "real_gdp" or link.get("relation") != "temporal_overlap_not_attribution":
        raise ValueError("統計との関係が不正です")
    _text(link, "note")
    return case


def _outcome(case: dict) -> dict:
    grouped: dict[str, list[str]] = {}
    for action in case["actors"]:
        grouped.setdefault(action["label"], []).append(f"{action['date']} {action['action']}")
    return {
        "id": case["caseId"],
        "title": case["title"],
        "observationFrom": case["observationFrom"],
        "observationTo": case["observationTo"],
        "implementation": " ".join(item["text"] for item in case["implementations"]),
        "observedResult": " ".join(item["text"] for item in case["observations"]),
        "contribution": case["holdReason"],
        "counterEvidence": " ".join(case["counterEvidence"]),
        "reviewStatus": "draft",
        "impact": None,
        "actors": [{"name": name, "action": " ".join(actions), "attributionStatus": "source_mention_not_individual_impact"} for name, actions in grouped.items()],
        "sources": [{"title": item["title"], "url": item["url"]} for item in case["citations"] if item["id"] != "fsaRules"],
    }


def public_case(case: dict, snapshot_id: str) -> dict:
    return {
        "schemaVersion": "public-case/v1",
        "snapshotId": snapshot_id,
        "caseId": case["caseId"],
        "title": case["title"],
        "scoringStatus": "held",
        "impactScale": None,
        "gdpLoss": None,
        "responsibilityShare": None,
        "holdReason": case["holdReason"],
        "periodNote": case["periodNote"],
        "observationFrom": case["observationFrom"],
        "observationTo": case["observationTo"],
        "implementations": [{"id": item["id"], "date": item["date"], "text": item["text"]} for item in case["implementations"]],
        "observations": [{"id": item["id"], "text": item["text"], "method": item["method"]} for item in case["observations"]],
        "comparison": case["comparison"],
        "counterEvidence": case["counterEvidence"],
        "actors": [{"id": item["id"], "label": item["label"], "date": item["date"], "action": item["action"], "identityNote": item["identityNote"], "citationIds": item["citationIds"]} for item in case["actors"]],
        "organizations": [{"id": item["id"], "name": item["name"], "relation": item["relation"]} for item in case["organizations"]],
        "contextMentions": [{"id": item["id"], "label": item["label"], "basis": item["basis"]} for item in case["contextMentions"]],
        "missingMaterials": case["missingMaterials"],
        "citations": [{"id": item["id"], "title": item["title"], "url": item["url"], "license": item["license"], "locator": item["locator"], "quote": item["quote"]} for item in case["citations"]],
        "statisticLink": case["statisticLink"],
        "causeCandidates": [{"id": item["id"], "label": item["label"], "status": "unestablished"} for item in case["causeCandidates"]],
    }


def _digest(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_suffix(path.suffix + ".pending")
    stage.write_text(text, encoding="utf-8")
    os.replace(stage, path)


def _write_database(path: Path, schema: str, release_id: str, snapshot: dict, case: dict, published: dict) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_suffix(".pending")
    if stage.exists():
        stage.unlink()
    connection = sqlite3.connect(stage)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(schema)
        connection.execute("INSERT INTO distribution_releases VALUES (?, ?)", (release_id, "public-distribution/v1"))
        for series in snapshot["series"]:
            connection.execute(
                "INSERT INTO statistic_series VALUES (?, ?, ?, ?, ?, ?)",
                (release_id, series["id"], series["label"], series["unit"], "CC BY 4.0（World Bank: World Development Indicators）", series["sourceUrl"]),
            )
            connection.executemany(
                "INSERT INTO statistic_points VALUES (?, ?, ?, ?)",
                [(release_id, series["id"], point["year"], point["value"]) for point in series["points"]],
            )
        for cause in published["causeCandidates"]:
            connection.execute("INSERT INTO cause_candidates VALUES (?, ?, ?, ?)", (release_id, cause["id"], cause["label"], "unestablished"))
        connection.execute("INSERT INTO policy_cases VALUES (?, ?, ?, ?, ?)", (release_id, case["caseId"], case["title"], "held", None))
        for item in case["implementations"]:
            connection.execute("INSERT INTO implementations VALUES (?, ?, ?, ?, ?)", (release_id, case["caseId"], item["id"], item["date"], item["text"]))
        for item in case["observations"]:
            connection.execute("INSERT INTO observations VALUES (?, ?, ?, ?, ?)", (release_id, case["caseId"], item["id"], item["text"], item["method"]))
        for index, text in enumerate(case["counterEvidence"]):
            connection.execute("INSERT INTO counterevidence VALUES (?, ?, ?, ?)", (release_id, case["caseId"], f"counter-{index}", text))
        for action in case["actors"]:
            connection.execute(
                "INSERT INTO actor_actions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (release_id, case["caseId"], action["id"], action["label"], action["date"], action["actionKind"], action["action"], None),
            )
        for org in case["organizations"]:
            connection.execute("INSERT INTO organizations VALUES (?, ?, ?)", (release_id, org["id"], org["name"]))
            connection.execute(
                "INSERT INTO organization_links VALUES (?, ?, ?, ?, ?, ?)",
                (release_id, case["caseId"], org["id"], org["relationKind"], org["relation"], None),
            )
        for mention in case["contextMentions"]:
            connection.execute("INSERT INTO context_mentions VALUES (?, ?, ?, ?, ?, ?)", (release_id, case["caseId"], mention["id"], mention["label"], mention["basis"], None))
        for citation in case["citations"]:
            connection.execute(
                "INSERT INTO citations VALUES (?, ?, ?, ?, ?, ?)",
                (release_id, citation["id"], citation["url"], citation["license"], citation["locator"], citation["quote"]),
            )
        for action in case["actors"]:
            for citation_id in action["citationIds"]:
                connection.execute("INSERT INTO action_citations VALUES (?, ?, ?)", (release_id, action["id"], citation_id))
        for index, text in enumerate(case["missingMaterials"]):
            connection.execute("INSERT INTO missing_materials VALUES (?, ?, ?, ?)", (release_id, case["caseId"], f"missing-{index}", text))
        link = case["statisticLink"]
        connection.execute(
            "INSERT INTO series_case_links VALUES (?, ?, ?, ?, ?)",
            (release_id, case["caseId"], link["seriesId"], link["relation"], link["note"]),
        )
        connection.commit()
    finally:
        connection.close()
    os.replace(stage, path)


def build_public_distribution(input_root: Path, case_path: Path, output_root: Path, public_dir: Path | None = None) -> dict:
    case = load_case(case_path)
    snapshot = build_snapshot(input_root)
    snapshot["outcomes"] = [_outcome(case)]
    snapshot["causes"] = []
    snapshot["note"] = "統計の推移だけで、特定の政策や人物による影響とは認定しません。政策事例は別ファイルで、採点は保留です。"
    stable = {key: value for key, value in snapshot.items() if key != "observedAt"}
    release_id = _digest({"economy": stable, "case": public_case(case, "")})
    snapshot["snapshotId"] = release_id
    published = public_case(case, release_id)
    schema = (Path(__file__).resolve().parents[1] / "data" / "distribution-schema.sql").read_text(encoding="utf-8")
    generation = output_root / "generations" / release_id
    economy_path = generation / "economy.json"
    case_file = generation / "case.json"
    economy_text = json.dumps(snapshot, ensure_ascii=False, indent=2)
    case_text = json.dumps(published, ensure_ascii=False, indent=2)
    if economy_path.exists() or case_file.exists():
        if not economy_path.exists() or not case_file.exists():
            raise ValueError("世代の片側だけが存在します")
        old_economy = json.loads(economy_path.read_text(encoding="utf-8"))
        old_case = json.loads(case_file.read_text(encoding="utf-8"))
        if {key: value for key, value in old_economy.items() if key != "observedAt"} != {key: value for key, value in snapshot.items() if key != "observedAt"} or old_case != published:
            raise ValueError("同じ版識別子の内容が一致しません")
        economy_text = economy_path.read_text(encoding="utf-8")
        case_text = case_file.read_text(encoding="utf-8")
    else:
        _atomic_text(economy_path, economy_text)
        _atomic_text(case_file, case_text)
        _write_database(generation / "catalog.sqlite3", schema, release_id, snapshot, case, published)
    manifest = {
        "schemaVersion": "public-distribution-current/v1",
        "snapshotId": release_id,
        "economyPath": f"generations/{release_id}/economy.json",
        "casePath": f"generations/{release_id}/case.json",
        "databasePath": f"generations/{release_id}/catalog.sqlite3",
        "scoringStatus": "held",
        "personScores": 0,
    }
    _atomic_text(output_root / "current.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    if public_dir:
        _atomic_text(public_dir / "economy.json", economy_text)
        _atomic_text(public_dir / "case.json", case_text)
        _atomic_text(public_dir / "releases" / f"{release_id}.json", economy_text)
        _atomic_text(public_dir / "cases" / f"{release_id}.json", case_text)
    return manifest


def read_edition(output_root: Path, edition: str) -> dict:
    if not HASH.fullmatch(edition or ""):
        raise ValueError("未知の版は停止します")
    path = output_root / "generations" / edition / "economy.json"
    if not path.is_file():
        raise ValueError("未知の版は停止します")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("snapshotId") != edition:
        raise ValueError("未知の版は停止します")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--case", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--public-dir", type=Path)
    args = parser.parse_args()
    manifest = build_public_distribution(args.input_root, args.case, args.output_root, args.public_dir)
    print(json.dumps({"snapshotId": manifest["snapshotId"], "scoringStatus": manifest["scoringStatus"], "personScores": manifest["personScores"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
