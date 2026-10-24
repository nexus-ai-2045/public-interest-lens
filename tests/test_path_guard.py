import os
import re
import tempfile
import unittest
from pathlib import Path

from scripts.path_guard import inside_without_links

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class AliasedRoot:
    def __enter__(self):
        self._real = tempfile.TemporaryDirectory()
        self._holder = tempfile.TemporaryDirectory()
        self.real = Path(self._real.name)
        self.alias = Path(self._holder.name) / "repo"
        try:
            os.symlink(self.real, self.alias, target_is_directory=True)
        except OSError as error:
            self.__exit__(None, None, None)
            raise unittest.SkipTest(type(error).__name__)
        return self

    def __exit__(self, *exc):
        self._holder.cleanup()
        self._real.cleanup()


class PathGuardTests(unittest.TestCase):
    def test_alias_on_either_side_is_accepted(self):
        with AliasedRoot() as roots:
            target = roots.real.resolve() / ".local" / "out"
            self.assertEqual(inside_without_links(roots.alias, roots.real / ".local" / "out"), target)
            self.assertEqual(inside_without_links(roots.real, roots.alias / ".local" / "out"), target)

    def test_link_below_root_is_rejected(self):
        with AliasedRoot() as roots:
            (roots.real / ".local" / "target").mkdir(parents=True)
            os.symlink(roots.real / ".local" / "target", roots.real / ".local" / "link", target_is_directory=True)
            self.assertIsNone(inside_without_links(roots.alias, roots.alias / ".local" / "link" / "out"))

    def test_outside_and_root_itself_are_rejected(self):
        with AliasedRoot() as roots:
            self.assertIsNone(inside_without_links(roots.alias, roots.real))
            self.assertIsNone(inside_without_links(roots.alias, roots.real.parent))
            self.assertIsNone(inside_without_links(roots.alias, roots.alias / ".local" / ".." / ".." / "x"))

    def test_lexical_and_resolved_paths_are_not_mixed_outside_path_guard(self):
        pattern = re.compile(r"\.absolute\(\)|os\.path\.(abspath|realpath|commonpath)\b")
        offenders = [
            path.name
            for path in sorted(SCRIPTS.glob("*.py"))
            if path.name != "path_guard.py" and pattern.search(path.read_text(encoding="utf-8"))
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
