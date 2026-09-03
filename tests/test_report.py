"""End-to-end: complexity-report.py as CI actually invokes it.

Run as a subprocess rather than imported, because the thing worth pinning is
the contract the CI job asserts against — two files on disk, one of them the
JSON array GitLab requires — not the internal functions.
"""

import json
import os
import subprocess
import sys

import pytest
from conftest import REPO_ROOT, SCRIPTS_DIR

REPORT = os.path.join(SCRIPTS_DIR, "complexity-report.py")


@pytest.fixture
def repo(tmp_path):
    """A checkout the reporter will accept paths as relative to."""
    (tmp_path / ".git").mkdir()
    return tmp_path


def run(repo, paths, *args, raw=None):
    """Invoke the reporter over `paths` inside `repo`; returns CompletedProcess."""
    listing = repo / "changed"
    listing.write_bytes(raw if raw is not None else "\n".join(paths).encode())
    env = dict(os.environ, CI_PROJECT_DIR=str(repo))
    env.pop("PYTHONPATH", None)
    return subprocess.run(
        [sys.executable, REPORT, "--files-from", str(listing),
         "--out-dir", str(repo / "gate-findings"), *args],
        cwd=str(repo), env=env, capture_output=True, text=True,
    )


def findings(repo):
    with open(repo / "gate-findings" / "complexity.json") as f:
        return json.load(f)


def entries(repo):
    with open(repo / "gate-findings" / "gl-code-quality-complexity.json") as f:
        return json.load(f)


class TestContract:
    def test_writes_both_reports_and_exits_zero(self, repo):
        (repo / "a.py").write_text("x = 1\n")
        result = run(repo, ["a.py"])
        assert result.returncode == 0, result.stderr
        assert findings(repo)["finding_count"] == 0
        assert entries(repo) == []

    def test_the_code_quality_report_is_an_array(self, repo):
        """The CI job asserts this shape; GitLab silently ignores anything
        else."""
        (repo / "a.py").write_text("x = 1\n")
        run(repo, ["a.py"])
        assert isinstance(entries(repo), list)

    def test_an_empty_diff_still_produces_valid_reports(self, repo):
        """An empty change legitimately produces [] — which is what lets the
        job's `test -s` distinguish 'no findings' from 'nothing ran'."""
        result = run(repo, [])
        assert result.returncode == 0
        assert findings(repo)["files_examined"] == 0
        assert entries(repo) == []


class TestFindings:
    def over_length(self, repo, name="big.py", lines=400):
        (repo / name).write_text("\n".join(f"x{i} = {i}" for i in range(lines)) + "\n")

    def test_reports_a_file_level_finding(self, repo):
        self.over_length(repo)
        run(repo, ["big.py"], "--rules", "file-length")
        report = findings(repo)
        assert report["finding_count"] == 1
        assert report["findings"][0]["rule"] == "file-length"
        assert report["findings"][0]["path"] == "big.py"

    def test_rules_not_requested_are_not_reported(self, repo):
        self.over_length(repo)
        run(repo, ["big.py"], "--rules", "cyclomatic-complexity")
        assert findings(repo)["finding_count"] == 0

    def test_the_requested_rules_are_recorded_in_the_report(self, repo):
        (repo / "a.py").write_text("x = 1\n")
        run(repo, ["a.py"], "--rules", "file-length,parameter-count")
        assert findings(repo)["rules"] == ["file-length", "parameter-count"]

    def test_excluded_paths_are_not_analyzed(self, repo):
        (repo / "tests").mkdir()
        self.over_length(repo, "tests/big.py")
        run(repo, ["tests/big.py"], "--rules", "file-length")
        assert findings(repo)["finding_count"] == 0

    def test_repo_thresholds_are_honored(self, repo):
        hooks = repo / ".claude" / "hooks"
        hooks.mkdir(parents=True)
        (hooks / "complexity_thresholds.json").write_text('{"max_file_lines": 1000}')
        self.over_length(repo)
        run(repo, ["big.py"], "--rules", "file-length")
        assert findings(repo)["finding_count"] == 0


class TestHostileInput:
    """The path list comes from a contributor-controlled diff."""

    def test_a_deleted_path_is_skipped_not_fatal(self, repo):
        """A change that deletes a file lists it in the diff; the gate must not
        fail because a deleted path cannot be analyzed."""
        result = run(repo, ["gone.py"])
        assert result.returncode == 0
        assert findings(repo)["finding_count"] == 0

    def test_an_absolute_path_is_skipped(self, repo, tmp_path):
        outside = tmp_path.parent / "outside.py"
        outside.write_text("\n".join(f"x{i} = {i}" for i in range(400)) + "\n")
        run(repo, [str(outside)], "--rules", "file-length")
        assert findings(repo)["finding_count"] == 0

    def test_a_traversal_path_is_skipped(self, repo):
        run(repo, ["../../etc/hosts"], "--rules", "file-length")
        assert findings(repo)["finding_count"] == 0

    def test_a_symlink_is_skipped(self, repo, tmp_path):
        target = tmp_path.parent / "secret.py"
        target.write_text("\n".join(f"x{i} = {i}" for i in range(400)) + "\n")
        (repo / "link.py").symlink_to(target)
        run(repo, ["link.py"], "--rules", "file-length")
        assert findings(repo)["finding_count"] == 0

    def test_a_nul_separated_path_with_spaces_is_analyzed(self, repo):
        """The CI job feeds `git diff -z`, and a filename with a space must
        survive it — stripping would drop the file and report 'clean'."""
        name = "a file.py"
        (repo / name).write_text("\n".join(f"x{i} = {i}" for i in range(400)) + "\n")
        run(repo, [], "--rules", "file-length", raw=f"{name}\0".encode())
        report = findings(repo)
        assert report["finding_count"] == 1
        assert report["findings"][0]["path"] == name


class TestArguments:
    def test_an_unknown_rule_fails_loudly(self, repo):
        """Rather than silently reporting nothing, which would look like a
        clean gate."""
        result = run(repo, [], "--rules", "no-such-rule")
        assert result.returncode != 0
        assert "unknown rule" in result.stderr

    def test_files_from_is_required(self, repo):
        result = subprocess.run(
            [sys.executable, REPORT], cwd=str(repo), capture_output=True, text=True
        )
        assert result.returncode != 0


class TestSelfCheck:
    def test_the_kit_passes_its_own_bar(self):
        """The checker holds itself to its own thresholds — the reason
        complexity_config.py and complexity_rules.py are separate files."""
        checker = os.path.join(REPO_ROOT, ".claude", "hooks", "check_complexity.py")
        result = subprocess.run(
            [sys.executable, checker, "--report", ".claude/hooks"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout
