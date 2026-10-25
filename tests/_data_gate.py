"""外したデータ（Git に入れない CSV）に頼るテストを、データが無いときだけ後の段に回す仕組み。

- データの置き場所はこのファイルの DATA だけに書く。
- 回してよいテストは tests/data_gated_tests.txt に固定する。一覧に無いテストに
  requires_data を付けると、読み込んだ時点で赤になる（skip で不具合を隠さないため）。
- 環境変数 PIL_REQUIRE_DATA=1 のときは skip しない（データ検査の段で全部を回す）。
"""
import os
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWLIST = Path(__file__).resolve().parent / "data_gated_tests.txt"

DATA = {
    "speeches": ROOT / "data" / "acquired" / "bill-speeches" / "speeches.csv",
    "industry_va": ROOT / "data" / "acquired" / "oecd-industry" / "industry_va.csv",
}

REGISTERED = {}


def load_allowlist():
    entries = {}
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        test_id, keys = line.split("\t")
        entries[test_id] = tuple(sorted(keys.split(",")))
    return entries


def missing(keys):
    return [key for key in keys if not DATA[key].exists()]


def requires_data(*keys):
    for key in keys:
        if key not in DATA:
            raise RuntimeError(f"知らないデータの名前です: {key}")

    def wrap(target):
        test_id = f"{target.__module__}.{target.__qualname__}"
        allowed = load_allowlist()
        if allowed.get(test_id) != tuple(sorted(keys)):
            raise RuntimeError(
                f"{test_id} は tests/data_gated_tests.txt に（同じデータの名前で）載っていないので、後の段に回せません"
            )
        REGISTERED[test_id] = tuple(sorted(keys))
        lacking = missing(keys)
        if not lacking or os.environ.get("PIL_REQUIRE_DATA") == "1":
            return target
        return unittest.skip("データ検査の段に回す（無いデータ: " + ",".join(lacking) + "）")(target)

    return wrap
