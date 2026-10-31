"""規制リスト（data/evidence/regulation_candidates.json）の形を守る。
批判の多さは根拠に使わない：根拠の欄に批判の多さを混ぜない、確認済みには研究の出典を必須にする。"""
import json
from pathlib import Path

ALLOWED = {"peer-reviewed", "working-paper", "meta-analysis", "official-estimate"}
DATA = json.loads((Path(__file__).resolve().parent.parent / "data/evidence/regulation_candidates.json").read_text(encoding="utf-8"))


def test_confirmed_entries_have_studies_with_sources():
    for e in DATA["entries"]:
        ev = e["evidence"]
        if ev["status"].startswith("確認"):
            assert ev["studies"], e["id"]
            for s in ev["studies"]:
                assert s["url"].startswith("https://") and s["study_type"] in ALLOWED, (e["id"], s["title"])
        else:
            assert not ev["studies"], e["id"]


def test_criticism_is_separate_from_evidence():
    for e in DATA["entries"]:
        assert "criticism_volume" in e["discovery"]
        assert "criticism" not in json.dumps(e["evidence"], ensure_ascii=False)
