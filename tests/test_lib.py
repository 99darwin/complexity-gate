"""Measurements — complexity_lib.py."""

import textwrap

import pytest

from complexity_lib import (
    DEFAULT_THRESHOLDS,
    analyze_file,
    estimate_nesting_depth,
    find_duplicate_blocks,
    format_report,
)


def lines(src):
    return textwrap.dedent(src).strip("\n").splitlines()


class TestNestingDepthBraces:
    def test_a_flat_body_is_depth_zero(self):
        # The body's own outermost pair is not nesting.
        assert estimate_nesting_depth(lines("""
            function f() {
              return 1;
            }
        """), ".ts") == 0

    def test_each_nested_block_adds_a_level(self):
        assert estimate_nesting_depth(lines("""
            function f() {
              if (a) {
                if (b) {
                  return 1;
                }
              }
            }
        """), ".ts") == 2

    def test_braces_inside_a_string_do_not_count(self):
        assert estimate_nesting_depth(lines("""
            function f() {
              const t = "{{{{";
              return t;
            }
        """), ".ts") == 0

    def test_an_escaped_quote_does_not_end_the_string(self):
        assert estimate_nesting_depth(lines(r"""
            function f() {
              const t = "he said \" { { ";
              return t;
            }
        """), ".ts") == 0

    def test_sibling_blocks_do_not_accumulate(self):
        """Depth is the deepest point, not a running total — two blocks at the
        same level are one level, not two."""
        assert estimate_nesting_depth(lines("""
            function f() {
              if (a) { x(); }
              if (b) { y(); }
            }
        """), ".ts") == 1


class TestNestingDepthIndent:
    def test_counts_indent_levels_below_the_signature(self):
        assert estimate_nesting_depth(lines("""
            def f():
                if a:
                    if b:
                        return 1
        """), ".py") == 2

    def test_tabs_and_spaces_measure_the_same(self):
        spaces = estimate_nesting_depth(lines("""
            def f():
                if a:
                    return 1
        """), ".py")
        tabs = estimate_nesting_depth(
            ["def f():", "\tif a:", "\t\treturn 1"], ".py"
        )
        assert spaces == tabs == 1

    def test_comments_do_not_set_the_depth(self):
        assert estimate_nesting_depth(lines("""
            def f():
                # deliberately over-indented note
                            return 1
        """), ".py") == 0

    def test_a_single_line_body_is_depth_zero(self):
        assert estimate_nesting_depth(["def f(): return 1"], ".py") == 0


class TestFindDuplicateBlocks:
    def test_finds_a_repeated_window(self):
        src = lines("""
            a = 1
            b = 2
            a = 1
            b = 2
        """)
        found = find_duplicate_blocks(src, min_lines=2, min_occurrences=2)
        assert found and found[0][0] == [1, 3]

    def test_respects_min_occurrences(self):
        src = lines("""
            a = 1
            b = 2
            a = 1
            b = 2
        """)
        assert find_duplicate_blocks(src, min_lines=2, min_occurrences=3) == []

    def test_ignores_whitespace_differences(self):
        src = ["a  =  1", "b = 2", "a = 1", "b   =   2"]
        assert find_duplicate_blocks(src, min_lines=2, min_occurrences=2)

    def test_all_blank_windows_are_not_findings(self):
        assert find_duplicate_blocks(["", "", "", ""], min_lines=2, min_occurrences=2) == []

    def test_line_numbers_are_one_indexed(self):
        src = ["x", "dup", "dup2", "dup", "dup2"]
        found = find_duplicate_blocks(src, min_lines=2, min_occurrences=2)
        assert found[0][0] == [2, 4]


class TestAnalyzeFile:
    def test_reports_an_oversized_file(self, tmp_path):
        target = tmp_path / "big.py"
        target.write_text("\n".join(f"x{i} = {i}" for i in range(400)) + "\n")
        thresholds = dict(DEFAULT_THRESHOLDS, max_file_lines=100)
        findings, _ = analyze_file(str(target), thresholds)
        assert any("file is 400 lines (max 100)" in f for f in findings)

    def test_a_clean_file_reports_nothing(self, tmp_path):
        target = tmp_path / "ok.py"
        target.write_text("def f(a):\n    return a + 1\n")
        findings, notices = analyze_file(str(target), dict(DEFAULT_THRESHOLDS))
        assert findings == []
        # notices may hold the "lizard isn't installed" note; that is not a
        # finding and must never be treated as one.
        assert all("max" not in n for n in notices)

    def test_undecodable_bytes_do_not_raise(self, tmp_path):
        target = tmp_path / "bin.py"
        target.write_bytes(b"def f():\n    return b'\xff\xfe'\n")
        analyze_file(str(target), dict(DEFAULT_THRESHOLDS))  # must not raise


class TestAnalyzeFileWithLizard:
    """The function-level checks, which need the analyzer installed."""

    @pytest.fixture(autouse=True)
    def _needs_lizard(self):
        pytest.importorskip("lizard")

    def test_reports_a_branchy_function(self, tmp_path):
        branches = "\n".join(f"    if x == {i}:\n        return {i}" for i in range(15))
        target = tmp_path / "branchy.py"
        target.write_text(f"def pick(x):\n{branches}\n    return None\n")
        findings, _ = analyze_file(str(target), dict(DEFAULT_THRESHOLDS))
        assert any("pick() at line 1" in f and "cyclomatic complexity" in f
                   for f in findings)

    def test_reports_too_many_parameters(self, tmp_path):
        target = tmp_path / "wide.py"
        target.write_text("def f(a, b, c, d, e, f_):\n    return a\n")
        findings, _ = analyze_file(str(target), dict(DEFAULT_THRESHOLDS))
        assert any("6 parameters (max 4)" in f for f in findings)

    def test_one_function_joins_its_violations_into_one_finding(self, tmp_path):
        branches = "\n".join(f"    if a == {i}:\n        return {i}" for i in range(15))
        target = tmp_path / "both.py"
        target.write_text(f"def f(a, b, c, d, e):\n{branches}\n    return None\n")
        findings, _ = analyze_file(str(target), dict(DEFAULT_THRESHOLDS))
        joined = [f for f in findings if f.startswith("f() at line 1:")]
        assert len(joined) == 1
        assert "cyclomatic complexity" in joined[0] and "parameters" in joined[0]


class TestFormatReport:
    def test_names_the_file_and_lists_findings(self):
        out = format_report("src/a.py", ["f() at line 3: 6 parameters (max 4)"], [])
        assert "src/a.py" in out and "6 parameters" in out

    def test_findings_bring_the_fix_order_with_them(self):
        out = format_report("a.py", ["f() at line 1: cyclomatic complexity 12 (max 10)"], [])
        assert "guard clauses" in out

    def test_notices_alone_do_not_suggest_fixes(self):
        out = format_report("a.py", [], ["`lizard` isn't installed"])
        assert "guard clauses" not in out
        assert "note:" in out
