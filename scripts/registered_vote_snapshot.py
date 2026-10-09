"""登録済み参議院個人別投票原本を、実評価の有限入力に変換する。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import date
from pathlib import Path

from .evidence_materials import read_materials
from .fetch_sangiin_votes import read_registered_votes


def build_snapshot(
    *,
    record_path: Path,
    material_root: Path,
    bill_id: str,
    title: str,
    url: str,
    as_of: str,
    period: int,
) -> dict:
    if period not in {4, 8}:
        raise ValueError("period must be 4 or 8 years")
    cutoff = date.fromisoformat(as_of)
    try:
        start = cutoff.replace(year=cutoff.year - period)
    except ValueError:
        start = cutoff.replace(year=cutoff.year - period, day=28)
    vote = read_registered_votes(
        record_path,
        material_root=material_root,
        bill_id=bill_id,
        title=title,
        url=url,
    )
    if not vote["allPublishedRowsConfirmed"] or not vote["available"]:
        raise ValueError("published member rows are incomplete")
    if not start <= date.fromisoformat(vote["eventDate"]) <= cutoff:
        raise ValueError("vote is outside the declared period")
    refs = []
    for row in vote["rows"]:
        identity = [vote["sha256"], bill_id, row["sourceLine"], row["nameText"]]
        mid = hashlib.sha256(
            json.dumps(identity, ensure_ascii=False, separators=(",", ":")).encode()
        ).hexdigest()
        refs.append(
            {
                "id": mid,
                "recordPath": str(record_path.resolve(strict=True)),
                "originalHash": vote["sha256"],
                "selector": {
                    "kind": "vote-row",
                    "billId": bill_id,
                    "title": title,
                    "sourceLine": row["sourceLine"],
                    "nameText": row["nameText"],
                },
            }
        )
    materials = read_materials(refs, material_root, _include_source_record=True)
    readable = [
        {
            "id": material["sourceRecord"]["id"],
            "text": material["text"],
            "position": material["sourceRecord"]["position"],
        }
        for material in materials
    ]
    if len(readable) != len(vote["rows"]) or len({r["id"] for r in readable}) != len(
        readable
    ):
        raise ValueError("original row projection is incomplete")
    return {
        "schemaVersion": "ranking-dataset/v1",
        "fictional": False,
        "asOf": as_of,
        "materialRefs": refs,
        "readableEvidence": {"votes": readable},
        "evidenceEvaluation": {
            "schemaVersion": "evidence-evaluation/v1",
            "mode": "real",
            "options": {
                "domain": "economy",
                "direction": "benefit",
                "period": period,
                "asOf": as_of,
                "weights": {"economy": 70, "technology": 30},
            },
            "people": [],
            "materials": [],
            "actions": [],
            "assessments": [],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--record-path", type=Path, required=True)
    parser.add_argument("--material-root", type=Path, required=True)
    parser.add_argument("--bill-id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--period", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    private_root = (Path(__file__).resolve().parent.parent / ".local").resolve()
    if not output.is_relative_to(private_root):
        raise ValueError("output must be inside this checkout .local")
    snapshot = build_snapshot(
        record_path=args.record_path,
        material_root=args.material_root,
        bill_id=args.bill_id,
        title=args.title,
        url=args.url,
        as_of=args.as_of,
        period=args.period,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    bytes_out = (
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as tmp:
        tmp.write(bytes_out)
        temporary = Path(tmp.name)
    try:
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    print(
        json.dumps(
            {
                "billId": args.bill_id,
                "period": args.period,
                "voteRows": len(snapshot["materialRefs"]),
                "outputHash": hashlib.sha256(bytes_out).hexdigest(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
