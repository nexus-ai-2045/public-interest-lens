"""閲覧用更新は失敗時に前正常版を保持します。"""
import json
import tempfile
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch

from scripts.run_local_mvp import run_local_mvp


class ReadableRunTests(unittest.TestCase):
    def test_evaluation_failure_does_not_replace_display(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            out = root / 'out'
            out.mkdir()
            (out / 'current.json').write_text('previous', encoding='utf-8')
            candidates = root / 'candidates.json'
            candidates.write_text('{"held": []}', encoding='utf-8')
            dataset = {'coverage': {'assessedPeople': 0, 'sourceStatus': 'pages_captured'}, 'held': []}
            with patch('scripts.run_local_mvp.build_readable_evidence', return_value=dataset), \
                 patch('scripts.run_local_mvp.subprocess.run', side_effect=subprocess.TimeoutExpired('node', 90)):
                result = run_local_mvp(root, out, as_of='2026-10-01',
                    readable_material_root=root, bill_source=candidates, evaluate=True)
            self.assertEqual('failed', result['status'])
            self.assertEqual('previous', (out / 'current.json').read_text(encoding='utf-8'))

    def test_offline_readable_run_and_failure_preserve_current(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidates = root / 'candidates.json'
            candidates.write_text(json.dumps({'held': []}), encoding='utf-8')
            dataset = {'coverage': {'assessedPeople': 0, 'sourceStatus': 'pages_captured'},
                       'held': [], 'readableEvidence': {'counts': {'readableSpeechBodies': 1}}}
            with patch('scripts.run_local_mvp.build_readable_evidence', return_value=dataset):
                result = run_local_mvp(root, root / 'out', as_of='2026-10-01',
                                      readable_material_root=root, bill_source=candidates)
            self.assertEqual('ready', result['status'])
            before = (root / 'out/current.json').read_bytes()
            with patch('scripts.run_local_mvp.build_readable_evidence', side_effect=ValueError('broken')):
                result = run_local_mvp(root, root / 'out', as_of='2026-10-01',
                                      readable_material_root=root, bill_source=candidates)
            self.assertEqual('failed', result['status'])
            self.assertTrue(result['last_good_preserved'])
            self.assertEqual(before, (root / 'out/current.json').read_bytes())


if __name__ == '__main__':
    unittest.main()
