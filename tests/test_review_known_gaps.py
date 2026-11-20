"""別モデルレビューで見つけた既知の不具合。

期待する契約を書き、いまは失敗する（expectedFailure）。評価エンジンの挙動は変えない。
直すとこのテストは成功し、expectedFailure を外すまで不合格になる。

tests/test_three_columns.py は、いまの符号検査（便益の中央値が負なら矛盾）を固定している。
こちらは method-spec-v3.0 の式（正は失った額、負は得た額）に合わせた契約。
"""
from __future__ import annotations

import unittest

from scripts.evaluation_rules import sign_conflict

# loss-batch の amountCell が、得た額（負の中央値）に付ける文字列と同じ形。
GAIN = "便益：中央値=-2;第1四分位=-3;第3四分位=-1"


class KnownSignContractTest(unittest.TestCase):
    @unittest.expectedFailure
    def test_negative_benefit_matches_gain_direction(self) -> None:
        """貢献・上昇と、負の中央値の便益は矛盾ではない（method-spec-v3.0 の損失の式）。"""
        self.assertIsNone(sign_conflict("貢献", GAIN))
        self.assertIsNone(sign_conflict("上昇", GAIN))
