"""M4の運用手順（正常更新2回・訂正・障害復旧・前正常版への復帰）を架空データで再現する訓練。

既存の配布版生成 `build_public_distribution`（不変世代と単一 `current.json` 切替）をそのまま使う。
新しい切替機構は作らない。前正常版への復帰は、保存しておいた前正常版の入力で再生成し、
既存の不変世代検査（同じ版識別子の内容一致・データベース内容一致）を通してから切り替える。

入力はすべて架空の訓練用データ。実在の統計・人物・引用ではない。
ここでの成功は手順と検査の再現性の確認であり、`M4`の運用証跡（実データでの実測）ではない。
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_public_distribution as distribution

EVIDENCE_KIND = "synthetic_drill_not_m4_evidence"
MARK = "【架空・訓練用】"
FIXTURE_HOST_PATH = "https://www.fsa.go.jp/__synthetic-drill-fixture__/"
INDICATORS = {"NY.GDP.MKTP.KN": 500, "NY.GDP.MKTP.CN": 520, "SP.POP.TOTL": 100}
ORIGINAL_QUOTE = f"{MARK}架空の発表文です。架空人物Aが架空施策を説明した、と記す。"
CORRECTED_QUOTE = f"{MARK}架空の発表文です。架空人物Aと架空人物Bが架空施策を共同で説明した、と記す。"


class DrillError(AssertionError):
    """期待状態と実際の状態が一致しない。"""


def write_synthetic_statistics(folder: Path, last_year: int, *, first_year: int = 2015) -> Path:
    """世界銀行の応答形式だけを借りた架空の統計。値は実在の統計ではない。"""
    folder.mkdir(parents=True, exist_ok=True)
    for indicator, base in INDICATORS.items():
        rows = [
            {
                "indicator": {"id": indicator, "value": f"SYNTHETIC DRILL FIXTURE {indicator}"},
                "country": {"id": "JP", "value": "SYNTHETIC"},
                "countryiso3code": "JPN",
                "date": str(year),
                "value": base + (year - first_year),
                "unit": "",
                "obs_status": "synthetic",
                "decimal": 0,
            }
            for year in range(last_year, first_year - 1, -1)
        ]
        header = {"page": 1, "pages": 1, "per_page": 100, "total": len(rows), "sourceid": "synthetic-drill", "lastupdated": f"{last_year}-12-31"}
        (folder / f"{indicator}.json").write_text(json.dumps([header, rows], ensure_ascii=False), encoding="utf-8")
    return folder


def synthetic_case(quote: str = ORIGINAL_QUOTE) -> dict:
    """配布版の事例検査を通る最小の架空事例。人物・資料・数字はすべて架空。"""
    citations = [
        {"id": f"drill-c{index}", "url": f"{FIXTURE_HOST_PATH}c{index}", "title": f"{MARK}架空資料{index}", "license": f"{MARK}架空資料のため利用条件なし", "locator": f"{MARK}架空資料{index}の第1段落", "quote": quote if index == 1 else f"{MARK}架空の引用{index}です。"}
        for index in (1, 2, 3)
    ]
    return {
        "caseId": "synthetic-drill-case",
        "title": f"{MARK}架空施策の運用訓練",
        "observationFrom": "2015-01-01",
        "observationTo": "2016-12-31",
        "holdReason": f"{MARK}架空事例のため影響は評価しない。",
        "periodNote": f"{MARK}観測期間は架空です。",
        "comparison": f"{MARK}比較対象はない。",
        "implementations": [{"id": "drill-impl", "date": "2015-04-01", "text": f"{MARK}架空施策を実施した。", "citationIds": ["drill-c1"]}],
        "observations": [{"id": "drill-obs", "text": f"{MARK}架空の観測値。", "method": "before_after_not_causal", "citationIds": ["drill-c2"]}],
        "counterEvidence": [f"{MARK}架空の反証。"],
        "actors": [
            {"id": f"drill-actor-{name}", "label": f"架空人物{name}", "date": "2015-04-01", "actionKind": "announcement", "action": f"{MARK}架空の説明。", "identityNote": f"{MARK}実在人物ではない。", "citationIds": [f"drill-c{index}"]}
            for index, name in ((1, "A"), (2, "B"), (3, "C"))
        ],
        "organizations": [{"id": "drill-org", "name": f"{MARK}架空機関", "relationKind": "publisher", "relation": f"{MARK}架空の発表元。"}],
        "contextMentions": [{"id": "drill-mention", "label": f"{MARK}架空の会合", "basis": f"{MARK}架空の名簿。", "citationIds": ["drill-c3"]}],
        "missingMaterials": [f"{MARK}架空の未取得資料があります。"],
        "causeCandidates": [{"id": "drill-cause", "label": f"{MARK}架空の原因候補"}],
        "citations": citations,
        "statisticLink": {"seriesId": "real_gdp", "relation": "temporal_overlap_not_attribution", "note": f"{MARK}時期が重なるだけです。"},
    }


def _write_case(path: Path, case: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def observed_state(output_root: Path, public_dir: Path) -> dict:
    """現在の `current.json` が指す世代を読み直し、配信用の写しと一致するかまで確認する。"""
    manifest_bytes = (output_root / "current.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    release = manifest["snapshotId"]
    economy_bytes = (output_root / manifest["economyPath"]).read_bytes()
    case_bytes = (output_root / manifest["casePath"]).read_bytes()
    economy = json.loads(economy_bytes)
    case = json.loads(case_bytes)
    connection = sqlite3.connect(f"{(output_root / manifest['databasePath']).resolve().as_uri()}?mode=ro", uri=True)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        database_release = connection.execute("SELECT releaseId FROM distribution_releases").fetchall()
        database_quote = connection.execute("SELECT quote FROM citations WHERE citationId = 'drill-c1'").fetchone()[0]
        latest_year = connection.execute("SELECT MAX(year) FROM statistic_points WHERE seriesId = 'real_gdp'").fetchone()[0]
    finally:
        connection.close()
    return {
        "snapshotId": release,
        "manifestBytes": manifest_bytes,
        "economySnapshotId": economy.get("snapshotId"),
        "caseSnapshotId": case.get("snapshotId"),
        "databaseIntegrity": integrity,
        "databaseRelease": database_release,
        "quote": next(item["quote"] for item in case["citations"] if item["id"] == "drill-c1"),
        "databaseQuote": database_quote,
        "latestYear": latest_year,
        "publicEconomyMatches": (public_dir / "economy.json").read_bytes() == economy_bytes,
        "publicCaseMatches": (public_dir / "case.json").read_bytes() == case_bytes,
        "publicReleaseMatches": (public_dir / "releases" / f"{release}.json").read_bytes() == economy_bytes,
        "personScores": manifest["personScores"],
        "scoringStatus": manifest["scoringStatus"],
    }


def _expect(step: str, state: dict, *, latest_year: int, quote: str, snapshot_id: str | None = None) -> None:
    problems = []
    release = state["snapshotId"]
    if snapshot_id is not None and release != snapshot_id:
        problems.append(f"版 {release} != 期待 {snapshot_id}")
    if state["economySnapshotId"] != release or state["caseSnapshotId"] != release or state["databaseRelease"] != [(release,)]:
        problems.append("統計・事例・データベースの版が一致しません")
    if state["databaseIntegrity"] != [("ok",)]:
        problems.append("データベースの整合性検査に失敗しました")
    if state["latestYear"] != latest_year:
        problems.append(f"最新年 {state['latestYear']} != 期待 {latest_year}")
    if state["quote"] != quote or state["databaseQuote"] != quote:
        problems.append("引用が期待した改訂ではありません")
    if not (state["publicEconomyMatches"] and state["publicCaseMatches"] and state["publicReleaseMatches"]):
        problems.append("配信用の写しが現在版と一致しません")
    if state["personScores"] != 0 or state["scoringStatus"] != "held":
        problems.append("架空訓練で点数が作られました")
    if problems:
        raise DrillError(f"{step}: " + " / ".join(problems))


def _generation_files(output_root: Path, release: str) -> dict[str, bytes]:
    folder = output_root / "generations" / release
    return {path.name: path.read_bytes() for path in sorted(folder.iterdir()) if path.is_file()}


def run_drill(work_root: Path) -> dict:
    """訓練を実行し、各段の期待状態を検査した記録を返す。期待と違えば `DrillError`。"""
    work_root = Path(work_root)
    output_root = work_root / "out"
    public_dir = work_root / "public"
    inputs = work_root / "inputs"
    steps: list[dict] = []

    def build(statistics: Path, case: Path) -> dict:
        return distribution.build_public_distribution(statistics, case, output_root, public_dir)

    def record(step: str, **extra) -> dict:
        state = observed_state(output_root, public_dir)
        entry = {"step": step, "snapshotId": state["snapshotId"], "latestYear": state["latestYear"], **extra}
        steps.append(entry)
        return state

    case_original = _write_case(inputs / "case-original.json", synthetic_case())

    # 0. 初回の版
    stats_2020 = write_synthetic_statistics(inputs / "stats-2020", 2020)
    initial = build(stats_2020, case_original)
    _expect("initial", record("initial"), latest_year=2020, quote=ORIGINAL_QUOTE, snapshot_id=initial["snapshotId"])

    # 1-2. 正常更新2回（統計に新しい年が加わる）
    released = [initial["snapshotId"]]
    for number, year in ((1, 2021), (2, 2022)):
        previous_files = _generation_files(output_root, released[-1])
        manifest = build(write_synthetic_statistics(inputs / f"stats-{year}", year), case_original)
        if manifest["snapshotId"] in released:
            raise DrillError(f"normal-update-{number}: 新しい版になっていません")
        if _generation_files(output_root, released[-1]) != previous_files:
            raise DrillError(f"normal-update-{number}: 前の世代が書き換わりました")
        _expect(f"normal-update-{number}", record(f"normal-update-{number}"), latest_year=year, quote=ORIGINAL_QUOTE, snapshot_id=manifest["snapshotId"])
        released.append(manifest["snapshotId"])
    stats_2022 = inputs / "stats-2022"

    # 3. 訂正（引用を改訂。事例IDと出典IDは保ち、版識別子は内容から再計算される）
    before_correction = released[-1]
    before_files = _generation_files(output_root, before_correction)
    case_corrected = _write_case(inputs / "case-corrected.json", synthetic_case(CORRECTED_QUOTE))
    corrected = build(stats_2022, case_corrected)
    if corrected["snapshotId"] == before_correction:
        raise DrillError("correction: 引用を改訂しても版識別子が変わりません")
    if _generation_files(output_root, before_correction) != before_files:
        raise DrillError("correction: 訂正前の世代が保持されていません")
    old_case = json.loads((output_root / "generations" / before_correction / "case.json").read_text(encoding="utf-8"))
    if next(item["quote"] for item in old_case["citations"] if item["id"] == "drill-c1") != ORIGINAL_QUOTE:
        raise DrillError("correction: 訂正前の世代の引用が変わりました")
    new_case = json.loads((output_root / corrected["casePath"]).read_text(encoding="utf-8"))
    if new_case["caseId"] != old_case["caseId"] or [item["id"] for item in new_case["citations"]] != [item["id"] for item in old_case["citations"]]:
        raise DrillError("correction: 安定した事例ID・出典IDが保たれていません")
    correction_state = record("correction", previousSnapshotId=before_correction)
    _expect("correction", correction_state, latest_year=2022, quote=CORRECTED_QUOTE, snapshot_id=corrected["snapshotId"])
    released.append(corrected["snapshotId"])
    good_manifest = correction_state["manifestBytes"]
    good_public = {path.relative_to(public_dir): path.read_bytes() for path in public_dir.rglob("*") if path.is_file()}

    # 4. 障害の注入：新しい更新の途中停止と、残った世代のファイル欠落
    stats_2023 = write_synthetic_statistics(inputs / "stats-2023", 2023)
    with patch.object(distribution, "_write_database", side_effect=RuntimeError("drill: injected interruption")):
        try:
            build(stats_2023, case_corrected)
        except RuntimeError:
            pass
        else:
            raise DrillError("failure: 注入した中断が発生しませんでした")
    partial = [path for path in (output_root / "generations").iterdir() if path.name not in released]
    if len(partial) != 1 or (partial[0] / "catalog.sqlite3").exists():
        raise DrillError("failure: 途中停止した世代の状態が想定と違います")
    (partial[0] / "case.json").unlink()
    try:
        build(stats_2023, case_corrected)
    except ValueError as error:
        refusal = str(error)
    else:
        raise DrillError("failure: 欠落のある世代を拒否しませんでした")
    if (output_root / "current.json").read_bytes() != good_manifest:
        raise DrillError("failure: 拒否後に現在版が変わりました")
    if {path.relative_to(public_dir): path.read_bytes() for path in public_dir.rglob("*") if path.is_file()} != good_public:
        raise DrillError("failure: 拒否後に配信用の写しが変わりました")
    _expect("failure-refused", record("failure-refused", refusal=refusal), latest_year=2022, quote=CORRECTED_QUOTE, snapshot_id=corrected["snapshotId"])

    # 5. 障害復旧：壊れた世代は削除せず隔離し、同じ入力で再生成する
    quarantine = work_root / "quarantine" / partial[0].name
    quarantine.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(partial[0]), str(quarantine))
    recovered = build(stats_2023, case_corrected)
    if recovered["snapshotId"] != partial[0].name:
        raise DrillError("recovery: 再生成した版が中断した版と一致しません")
    _expect("recovery", record("recovery", quarantined=str(quarantine.relative_to(work_root))), latest_year=2023, quote=CORRECTED_QUOTE, snapshot_id=recovered["snapshotId"])
    released.append(recovered["snapshotId"])
    recovered_files = _generation_files(output_root, recovered["snapshotId"])

    # 6. 前正常版への復帰：保存済みの前正常版の入力で再生成する。不変世代の検査を通ってから切り替わる
    rollback = build(stats_2022, case_corrected)
    if rollback["snapshotId"] != corrected["snapshotId"]:
        raise DrillError("rollback: 前正常版に戻っていません")
    if (output_root / "current.json").read_bytes() != good_manifest:
        raise DrillError("rollback: 現在版の記述が前正常版と一致しません")
    if {path.relative_to(public_dir): path.read_bytes() for path in public_dir.rglob("*") if path.is_file() and path.parent == public_dir} != {key: value for key, value in good_public.items() if len(key.parts) == 1}:
        raise DrillError("rollback: 配信用の現在版の写しが前正常版と一致しません")
    if _generation_files(output_root, recovered["snapshotId"]) != recovered_files:
        raise DrillError("rollback: 復帰前の版の世代が保持されていません")
    _expect("rollback", record("rollback", rolledBackFrom=recovered["snapshotId"]), latest_year=2022, quote=CORRECTED_QUOTE, snapshot_id=corrected["snapshotId"])

    # 6b. 復帰先の世代が改ざんされていれば復帰を拒否し、現在版を変えない
    tampered = work_root / "tamper-check"
    shutil.copytree(output_root, tampered / "out")
    shutil.copytree(public_dir, tampered / "public")
    economy_path = tampered / "out" / "generations" / initial["snapshotId"] / "economy.json"
    payload = json.loads(economy_path.read_text(encoding="utf-8"))
    payload["note"] = "drill: tampered"
    economy_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tampered_current = (tampered / "out" / "current.json").read_bytes()
    try:
        distribution.build_public_distribution(stats_2020, case_original, tampered / "out", tampered / "public")
    except ValueError:
        pass
    else:
        raise DrillError("rollback-tamper: 改ざんされた世代への復帰を拒否しませんでした")
    if (tampered / "out" / "current.json").read_bytes() != tampered_current:
        raise DrillError("rollback-tamper: 拒否後に現在版が変わりました")
    steps.append({"step": "rollback-tamper-refused", "snapshotId": json.loads(tampered_current)["snapshotId"], "target": initial["snapshotId"]})

    generations = sorted(path.name for path in (output_root / "generations").iterdir())
    if generations != sorted(released):
        raise DrillError("final: 保持されている世代が想定と違います")
    return {
        "evidenceKind": EVIDENCE_KIND,
        "note": "架空データによる手順の再現です。M4の運用証跡ではありません。実データでの更新・訂正・復旧・復帰は別に実測します。",
        "steps": steps,
        "generations": len(generations),
        "currentSnapshotId": corrected["snapshotId"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="M4運用訓練（架空データ）。結果はM4の証跡ではありません。")
    parser.add_argument("--work-root", type=Path, help="訓練の出力先。省略時は一時ディレクトリを使い、終了時に消します。")
    args = parser.parse_args()
    if args.work_root:
        if args.work_root.exists() and any(args.work_root.iterdir()):
            parser.error("--work-root は空のディレクトリを指定してください")
        result = run_drill(args.work_root)
    else:
        with tempfile.TemporaryDirectory() as folder:
            result = run_drill(Path(folder))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
