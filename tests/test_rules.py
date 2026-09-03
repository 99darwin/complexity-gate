"""Finding classification and report shapes — complexity_rules.py.

complexity_lib returns findings as preformatted English, and this module parses
them back into typed records. That makes the wording of those f-strings load
bearing, so these tests pin the round trip rather than the regexes.
"""

import pytest

from complexity_lib import DEFAULT_THRESHOLDS
from complexity_rules import (
    ALL_RULES,
    RULES_BY_ID,
    _entry,
    _record,
    classify,
    describe,
    split_finding,
)


class TestClassify:
    @pytest.mark.parametrize(
        "text,rule,value",
        [
            ("cyclomatic complexity 14 (max 10)", "cyclomatic-complexity", 14),
            ("42 lines (max 30)", "function-length", 42),
            ("6 parameters (max 4)", "parameter-count", 6),
            ("~5 levels of nesting (max 3)", "nesting-depth", 5),
            ("file is 515 lines (max 300) — consider splitting", "file-length", 515),
            ("duplicate 4-line block repeated at lines [1, 9]", "duplicate-block", 4),
        ],
    )
    def test_classifies_each_finding_class(self, text, rule, value):
        assert classify(text) == (rule, value)

    def test_file_length_is_matched_before_function_length(self):
        """ORDER IS LOAD-BEARING. 'file is 515 lines (max 300)' also matches the
        function-length pattern `(\\d+) lines \\(max`, and with the looser rule
        first every oversized file was reported as an oversized function at
        line 1."""
        assert classify("file is 515 lines (max 300)")[0] == "file-length"

    def test_unrecognized_text_classifies_as_nothing(self):
        assert classify("something else entirely") == (None, None)

    def test_every_rule_id_is_exposed(self):
        assert set(ALL_RULES) == set(RULES_BY_ID)

    def test_no_rule_outranks_the_blocking_gates(self):
        """This gate is non-blocking, so a `critical` or `blocker` entry would
        misrepresent it next to a security gate's output."""
        assert {r.severity for r in RULES_BY_ID.values()} <= {"major", "minor"}


class TestSplitFinding:
    def test_a_function_finding_carries_its_name_and_line(self):
        (v,) = split_finding("handle() at line 42: cyclomatic complexity 14 (max 10)")
        assert (v.rule, v.value, v.line, v.scope) == \
            ("cyclomatic-complexity", 14, 42, "handle")

    def test_joined_violations_become_separate_records(self):
        """One fingerprint carrying two unrelated problems means fixing one
        leaves the entry standing."""
        out = split_finding(
            "f() at line 7: cyclomatic complexity 14 (max 10); 6 parameters (max 4)"
        )
        assert [v.rule for v in out] == ["cyclomatic-complexity", "parameter-count"]
        assert all(v.line == 7 for v in out)

    def test_a_file_level_finding_has_no_scope_and_sits_on_line_one(self):
        (v,) = split_finding("file is 515 lines (max 300) — consider splitting")
        assert v.scope is None and v.line == 1

    def test_an_unrecognized_finding_yields_nothing(self):
        assert split_finding("mystery") == []

    def test_a_function_name_with_parens_still_parses(self):
        # FUNCTION_RE is non-greedy up to "() at line", so a qualified or
        # generic name does not derail it.
        (v,) = split_finding("Foo::bar() at line 3: 6 parameters (max 4)")
        assert v.scope == "Foo::bar"


class TestDescribe:
    def test_quotes_the_limit_from_the_thresholds_passed_in(self):
        text = describe("cyclomatic-complexity", 14, "handle", dict(DEFAULT_THRESHOLDS, max_cyclomatic_complexity=8))
        assert "max 8" in text and "handle()" in text

    def test_a_file_level_finding_says_this_file(self):
        text = describe("file-length", 515, None, dict(DEFAULT_THRESHOLDS))
        assert text.startswith("This file is 515 lines (max 300).")

    def test_carries_the_fix_order(self):
        text = describe("nesting-depth", 5, "f", dict(DEFAULT_THRESHOLDS))
        assert "guard clauses" in text


class TestCodeQualityEntry:
    def entry(self, finding, path="src/a.ts"):
        (v,) = split_finding(finding)
        return _entry(path, v, dict(DEFAULT_THRESHOLDS))

    def test_locates_the_finding_on_its_line(self):
        e = self.entry("f() at line 42: cyclomatic complexity 14 (max 10)")
        assert e["location"] == {"path": "src/a.ts", "lines": {"begin": 42}}

    def test_names_the_rule_in_the_check_name(self):
        e = self.entry("f() at line 1: cyclomatic complexity 14 (max 10)")
        assert e["check_name"] == "complexity/cyclomatic-complexity"

    def test_two_functions_in_one_file_get_distinct_fingerprints(self):
        """GitLab collapses entries sharing a fingerprint, so path+rule alone
        would hide the second offending function."""
        a = self.entry("f() at line 10: cyclomatic complexity 14 (max 10)")
        b = self.entry("g() at line 80: cyclomatic complexity 14 (max 10)")
        assert a["fingerprint"] != b["fingerprint"]

    def test_the_fingerprint_survives_a_partial_improvement(self):
        """It deliberately excludes the measured value, so an entry keeps its
        identity when a refactor moves complexity 14 to 12 and it is still
        over threshold."""
        a = self.entry("f() at line 10: cyclomatic complexity 14 (max 10)")
        b = self.entry("f() at line 10: cyclomatic complexity 12 (max 10)")
        assert a["fingerprint"] == b["fingerprint"]

    def test_the_same_rule_in_two_files_is_two_entries(self):
        a = self.entry("f() at line 10: cyclomatic complexity 14 (max 10)", "src/a.ts")
        b = self.entry("f() at line 10: cyclomatic complexity 14 (max 10)", "src/b.ts")
        assert a["fingerprint"] != b["fingerprint"]

    def test_severity_comes_from_the_rule(self):
        e = self.entry("f() at line 1: cyclomatic complexity 14 (max 10)")
        assert e["severity"] == RULES_BY_ID["cyclomatic-complexity"].severity


class TestRawRecord:
    def test_keeps_the_original_finding_text(self):
        finding = "f() at line 42: cyclomatic complexity 14 (max 10)"
        (v,) = split_finding(finding)
        r = _record("src/a.ts", v)
        assert r["message"] == finding
        assert (r["path"], r["rule"], r["value"], r["line"], r["scope"]) == \
            ("src/a.ts", "cyclomatic-complexity", 14, 42, "f")
