import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import worktree_audit  # noqa: E402


def test_stale_branches_excludes_open_and_prless(monkeypatch):
    refs = "origin/main\norigin/a\norigin/b\norigin/c\norigin/d"
    prs = [
        {"headRefName": "a", "state": "MERGED", "isCrossRepository": False},
        {"headRefName": "b", "state": "OPEN", "isCrossRepository": False},
        {"headRefName": "c", "state": "CLOSED", "isCrossRepository": False},
        {"headRefName": "c", "state": "OPEN", "isCrossRepository": False},
        {"headRefName": "d", "state": "CLOSED", "isCrossRepository": True},
    ]
    monkeypatch.setattr(worktree_audit, "git", lambda cwd, *a: (0, refs))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=json.dumps(prs), stderr=""),
    )
    assert worktree_audit.stale_branches(".") == ["a"]


def test_stale_branches_exits_when_gh_fails(monkeypatch):
    monkeypatch.setattr(worktree_audit, "git", lambda cwd, *a: (0, "origin/a"))
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr="auth"),
    )
    try:
        worktree_audit.stale_branches(".")
    except SystemExit as e:
        assert "auth" in str(e)
    else:
        raise AssertionError("gh 失敗で終了しなかった")
