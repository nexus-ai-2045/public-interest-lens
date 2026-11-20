"""同じ表示文字列を、二つの符号の読みが別々に判定することだけを示す。

どちらを契約にするかは決めない。
- 表示（設計決定0024）: 便益は正、損失は負。sign_conflict は便益の中央値が負なら矛盾とする。
- 内部の損失額（method-spec-v3.0）: 正は失った額、負は得た額。

二つの読みが揃うと、この試験は失敗する。評価エンジンの挙動は変えない。
"""
from __future__ import annotations

import unittest

from scripts.evaluation_rules import sign_conflict

# loss-batch の amountCell が、得た額（負の中央値）に付ける文字列と同じ形。
GAIN = "便益：中央値=-2;第1四分位=-3;第3四分位=-1"
MEDIAN = -2


def display_says_conflict(direction: str) -> bool:
    """表示欄の検査。便益の数が負なら矛盾。"""
    return sign_conflict(direction, GAIN) is not None


def internal_says_conflict(direction: str) -> bool:
    """内部の損失額。負は得た額なので、貢献・上昇とは一致する。"""
    gained = MEDIAN < 0
    good = direction in ("貢献", "上昇")
    return good != gained


class SignReadingsDisagreeTest(unittest.TestCase):
    def test_contribution_and_negative_benefit_text_disagree(self) -> None:
        self.assertNotEqual(display_says_conflict("貢献"), internal_says_conflict("貢献"))

    def test_rise_and_negative_benefit_text_disagree(self) -> None:
        self.assertNotEqual(display_says_conflict("上昇"), internal_says_conflict("上昇"))
