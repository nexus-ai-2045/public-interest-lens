"""評価器の保存本文readback。入力の文字列を命令として実行しません。"""

import argparse
import json
from pathlib import Path
import sys

from .evidence_materials import read_materials, read_verified_projection


def main():
    parser = argparse.ArgumentParser(
        description="登録原本を再読し、対応する本文を返します"
    )
    parser.add_argument("--material-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = sys.stdin.buffer.read(5_000_001)
        if len(raw) > 5_000_000:
            raise ValueError("入力の上限超過です")
        value = json.loads(raw.decode("utf-8"))
        if isinstance(value, list):
            materials = read_materials(value, args.material_root)
        elif isinstance(value, dict) and set(value) == {
            "materialRefs",
            "readableEvidence",
        }:
            materials = read_verified_projection(
                value["materialRefs"], value["readableEvidence"], args.material_root
            )
        else:
            raise ValueError("原本参照または閲覧照合の入力が必要です")
        print(json.dumps(materials, ensure_ascii=False))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(
            json.dumps({"status": "failed", "errorType": type(error).__name__}),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
