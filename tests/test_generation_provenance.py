import tempfile
import unittest
from pathlib import Path

from scripts.generation_provenance import generation_metadata


class GenerationMetadataTest(unittest.TestCase):
    def fixture(self, root):
        for name, text in {
            'app/src/method-spec.ts': "export const SPEC_VERSION = 'method-spec-v2.2';\n",
            'scripts/generation_provenance.py': '# fixture generator\n',
            'scripts/path_guard.py': '# fixture guard\n',
            'scripts/calculate.py': 'result = 1\n',
        }.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def test_only_actual_sources_and_spec_change_the_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            before = generation_metadata(['scripts/calculate.py'], root=root)
            (root / 'README.md').write_text('unrelated change')
            self.assertEqual(before, generation_metadata(['scripts/calculate.py'], root=root))
            (root / 'scripts/calculate.py').write_text('result = 2\n')
            after = generation_metadata(['scripts/calculate.py'], root=root)
            self.assertNotEqual(before['codeHashes'], after['codeHashes'])
            self.assertEqual(after['methodSpecVersion'], 'method-spec-v2.2')
            (root / 'app/src/method-spec.ts').write_text("export const SPEC_VERSION = 'method-spec-v2.3';\n")
            self.assertEqual(generation_metadata([], root=root)['methodSpecVersion'], 'method-spec-v2.3')

    def test_missing_ambiguous_or_outside_sources_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            self.fixture(root)
            outside = Path(tmp) / 'outside.py'
            outside.write_text('private')
            with self.assertRaises(ValueError):
                generation_metadata(['../outside.py'], root=root)
            with self.assertRaises(FileNotFoundError):
                generation_metadata(['missing.py'], root=root)
            spec = root / 'app/src/method-spec.ts'
            spec.write_text(spec.read_text() * 2)
            with self.assertRaises(ValueError):
                generation_metadata([], root=root)
