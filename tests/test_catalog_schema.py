import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.build_readable_catalog import write_database


class CatalogSchemaTests(unittest.TestCase):
    def test_published_schema_matches_builder(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'catalog.sqlite3'
            context = {'releaseId': 'a' * 64, 'policies': []}
            write_database(path, (context, 'b' * 64, [], [], [], [], []))
            generated = sqlite3.connect(path)
            declared = sqlite3.connect(':memory:')
            try:
                declared.executescript((Path(__file__).resolve().parents[1] / 'data/catalog-schema.sql').read_text(encoding='utf-8'))
                tables = sorted(row[0] for row in generated.execute("SELECT name FROM sqlite_master WHERE type='table'"))
                self.assertEqual(tables, sorted(row[0] for row in declared.execute("SELECT name FROM sqlite_master WHERE type='table'")))
                for table in tables:
                    self.assertEqual(generated.execute(f'PRAGMA table_info({table})').fetchall(), declared.execute(f'PRAGMA table_info({table})').fetchall())
                    self.assertEqual(generated.execute(f'PRAGMA foreign_key_list({table})').fetchall(), declared.execute(f'PRAGMA foreign_key_list({table})').fetchall())
            finally:
                generated.close()
                declared.close()


if __name__ == '__main__':
    unittest.main()
