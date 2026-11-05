import ast
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'archive/knowledge-export-20260930/export_knowledge_notes.py.txt'


def archived_private_reference_guard():
    tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'private_root' for target in node.targets)]
    conditions = [node.test for node in ast.walk(tree) if isinstance(node, ast.If) and isinstance(node.test, ast.BoolOp) and any(isinstance(value, ast.Name) and value.id == 'private_root' for value in node.test.values)]
    if len(assignments) != 1 or len(conditions) != 1:
        raise ValueError('archived_guard_contract_changed')
    expression = ast.Expression(ast.List(elts=[ast.NamedExpr(target=ast.Name(id='private_root', ctx=ast.Store()), value=assignments[0].value), conditions[0]], ctx=ast.Load()))
    compiled = compile(ast.fix_missing_locations(expression), 'archived_private_reference_guard', 'eval')
    return lambda text: eval(compiled, {'re': re, 'text': text})[1]


class ArchivedKnowledgeGuardTests(unittest.TestCase):
    def setUp(self):
        self.guard = archived_private_reference_guard()

    def test_private_directory_components_are_rejected(self):
        for root in ('Users', 'home'):
            path = str(PurePosixPath('/', root, 'user', 'fixture'))
            for text in (path, '資料: ' + path + ' 本文', 'https://example.invalid' + path):
                with self.subTest(root=root, text=text):
                    self.assertTrue(self.guard(text))

    def test_drive_uri_and_local_state_are_rejected(self):
        for text in (str(PureWindowsPath('Q:/', 'fixture')), 'file://fixture', '.local/state.json'):
            with self.subTest(text=text):
                self.assertTrue(self.guard(text))

    def test_public_references_and_ordinary_words_are_allowed(self):
        for text in ('https://www.sangiin.go.jp/japanese/joho1/kousei/gian/', '/homework/guide', '/UsersGuide/page', 'home Users', '政策の概要です。'):
            with self.subTest(text=text):
                self.assertFalse(self.guard(text))

    def test_archival_source_stays_outside_executable_entrypoints(self):
        self.assertTrue(SOURCE.name.endswith('.py.txt'))
        self.assertFalse((SOURCE.parent / 'export_knowledge_notes.py').exists())


if __name__ == '__main__':
    unittest.main()
