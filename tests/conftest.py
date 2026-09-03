"""Import surface and isolation for the gate's own tests.

The kit is scripts, not an installed package: .claude/hooks/ holds the shared
library and scripts/ holds the CI reporter, and each reaches the other by
sys.path at import time. The tests reproduce that rather than restructure it,
so what they exercise is what actually runs in the hook and in CI.
"""

import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(REPO_ROOT, ".claude", "hooks")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")

for path in (HOOKS_DIR, SCRIPTS_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)


@pytest.fixture(autouse=True)
def _no_ambient_project_dir(monkeypatch):
    """Unset CI_PROJECT_DIR for every test.

    _repo_root reads it first, so a test running under a real CI job would
    otherwise resolve the *runner's* checkout instead of the tmp_path repo the
    test just built — the suite would then pass locally and assert against the
    wrong config in CI.
    """
    monkeypatch.delenv("CI_PROJECT_DIR", raising=False)


@pytest.fixture
def fake_repo(tmp_path):
    """A tmp directory that _repo_root will stop at, since it looks for .git."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def write_thresholds(repo, payload):
    """Write a complexity_thresholds.json into repo's .claude/hooks/."""
    import json
    hooks = repo / ".claude" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    target = hooks / "complexity_thresholds.json"
    target.write_text(payload if isinstance(payload, str) else json.dumps(payload))
    return target
