"""GitHub surface — complexity-annotate.py.

Loaded by path because the file is named with a hyphen (it is a CLI, not an
importable module), same as complexity-report.py.
"""

import importlib.util
import json
import os
import subprocess
import sys

import pytest
from conftest import SCRIPTS_DIR

ANNOTATE = os.path.join(SCRIPTS_DIR, "complexity-annotate.py")


def _load():
    spec = importlib.util.spec_from_file_location("complexity_annotate", ANNOTATE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


annotate = _load()


def finding(**overrides):
    base = {
        "path": "src/a.ts",
        "rule": "cyclomatic-complexity",
        "value": 14,
        "line": 42,
        "scope": "handle",
        "message": "handle() at line 42: cyclomatic complexity 14 (max 10)",
    }
    base.update(overrides)
    return base


class TestEscaping:
    def test_a_newline_cannot_truncate_the_message(self):
        """An unescaped newline ends the workflow command, leaving the rest
        printed as plain log output and the annotation half-written."""
        assert "\n" not in annotate.escape_data("a\nb")
        assert annotate.escape_data("a\nb") == "a%0Ab"

    def test_percent_is_escaped_first(self):
        # Escaping % last would double-escape the % this function introduces.
        assert annotate.escape_data("100%\n") == "100%25%0A"

    def test_carriage_return_is_escaped(self):
        assert annotate.escape_data("a\rb") == "a%0Db"

    def test_a_property_escapes_the_separators_too(self):
        """Properties are comma-separated with ':' ending the list, so a
        function named f(a, b) in a title corrupts the command otherwise."""
        out = annotate.escape_property("Foo::bar(a, b)")
        assert ":" not in out and "," not in out

    def test_a_property_still_escapes_what_data_does(self):
        assert "\n" not in annotate.escape_property("a\nb")


class TestAnnotation:
    def test_carries_file_line_and_message(self):
        line = annotate.annotation(finding())
        assert "file=src/a.ts" in line
        assert "line=42" in line
        assert "cyclomatic complexity 14" in line

    def test_a_major_rule_is_a_warning(self):
        assert annotate.annotation(finding()).startswith("::warning ")

    def test_a_minor_rule_is_a_notice(self):
        line = annotate.annotation(finding(rule="function-length"))
        assert line.startswith("::notice ")

    def test_never_emits_an_error_level(self):
        """The gate is non-blocking; an error annotation reads like a failed
        build next to the ones that are."""
        for rule in ("cyclomatic-complexity", "nesting-depth", "function-length",
                     "parameter-count", "file-length", "duplicate-block"):
            assert not annotate.annotation(finding(rule=rule)).startswith("::error")

    def test_the_title_names_the_rule(self):
        assert "title=complexity/cyclomatic-complexity::" in annotate.annotation(finding())


class TestCap:
    def test_under_the_cap_nothing_is_dropped(self, capsys):
        dropped = annotate.emit_annotations([finding() for _ in range(5)])
        assert dropped == 0
        assert capsys.readouterr().out.count("::warning") == 5

    def test_past_the_cap_the_remainder_is_counted(self, capsys):
        n = annotate.MAX_ANNOTATIONS_PER_LEVEL + 4
        dropped = annotate.emit_annotations([finding() for _ in range(n)])
        assert dropped == 4
        assert capsys.readouterr().out.count("::warning") == \
            annotate.MAX_ANNOTATIONS_PER_LEVEL

    def test_the_cap_is_per_level_not_overall(self, capsys):
        """Ten warnings must not consume the notice budget."""
        n = annotate.MAX_ANNOTATIONS_PER_LEVEL
        items = [finding() for _ in range(n)] + \
                [finding(rule="function-length") for _ in range(n)]
        assert annotate.emit_annotations(items) == 0
        out = capsys.readouterr().out
        assert out.count("::warning") == n and out.count("::notice") == n


class TestSummary:
    def report(self, items, files=3):
        return {
            "files_examined": files,
            "rules": ["cyclomatic-complexity", "nesting-depth"],
            "finding_count": len(items),
            "findings": items,
        }

    def test_a_clean_run_says_so(self):
        text = "\n".join(annotate.summary_lines(self.report([]), 0))
        assert "No findings" in text and "|" not in text

    def test_lists_every_finding_past_the_annotation_cap(self):
        """The summary is the surface that stays complete when annotations are
        capped."""
        items = [finding(line=i) for i in range(30)]
        text = "\n".join(annotate.summary_lines(self.report(items), dropped=20))
        assert text.count("| `src/a.ts` |") == 30

    def test_says_when_findings_are_summary_only(self):
        items = [finding(line=i) for i in range(30)]
        text = "\n".join(annotate.summary_lines(self.report(items), dropped=20))
        assert "20 finding(s) are listed here only" in text

    def test_a_pipe_in_a_message_does_not_break_the_row(self):
        """A TypeScript union in a signature lizard captured is enough; one
        unescaped pipe shifts every later column."""
        items = [finding(message="f(a: string | null) at line 1: 6 parameters (max 4)")]
        row = [ln for ln in annotate.summary_lines(self.report(items), 0)
               if ln.startswith("| `")][0]
        assert row.count("|") - row.count("\\|") == 5

    def test_reports_the_file_count(self):
        text = "\n".join(annotate.summary_lines(self.report([], files=7), 0))
        assert "7 changed file(s)" in text


class TestCli:
    def test_writes_the_summary_to_the_github_file(self, tmp_path):
        report = tmp_path / "complexity.json"
        report.write_text(json.dumps({
            "files_examined": 1, "rules": ["cyclomatic-complexity"],
            "finding_count": 1, "findings": [finding()],
        }))
        summary = tmp_path / "summary.md"
        env = dict(os.environ, GITHUB_STEP_SUMMARY=str(summary))
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, ANNOTATE, "--findings", str(report)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0, result.stderr
        assert "::warning" in result.stdout
        assert "Complexity gate" in summary.read_text()

    def test_falls_back_to_stdout_without_the_env_var(self, tmp_path):
        report = tmp_path / "complexity.json"
        report.write_text(json.dumps({
            "files_examined": 0, "rules": ["cyclomatic-complexity"],
            "finding_count": 0, "findings": [],
        }))
        env = {k: v for k, v in os.environ.items() if k != "GITHUB_STEP_SUMMARY"}
        env.pop("PYTHONPATH", None)
        result = subprocess.run(
            [sys.executable, ANNOTATE, "--findings", str(report)],
            capture_output=True, text=True, env=env,
        )
        assert result.returncode == 0
        assert "No findings" in result.stdout
