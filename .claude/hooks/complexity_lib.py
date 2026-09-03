"""
complexity_lib.py — analysis functions shared by check_complexity.py (the
Claude Code hook / CLI entrypoint) and anything else that wants the same
checks (a pre-commit hook, a CI job, the reduce-cyclomatic-complexity skill).

Split out of check_complexity.py so the entrypoint file itself stays under
the thresholds it enforces — see README.md in this directory for the "does the
checker pass its own bar" self-check, and for the one-time venv setup the
lizard-backed checks need.
"""

import os

# Re-exported so complexity_lib stays the one import both the hook and the CI
# reporter reach for; complexity_config is an implementation detail of where
# the numbers live.
from complexity_config import (  # noqa: F401
    DEFAULT_THRESHOLDS,
    THRESHOLDS_FILENAME,
    load_thresholds,
    should_skip,
)

BRACE_LANGUAGES = {
    ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".c", ".cc",
    ".cpp", ".h", ".hpp", ".cs", ".swift", ".m",
}


def _indent_width(line):
    """(indent columns, the line without its indent). Tabs count as 4, so a
    tab-indented and a space-indented block nest to the same depth."""
    stripped = line.lstrip(" \t")
    return len(line[: len(line) - len(stripped)].expandtabs(4)), stripped


def _scan_line_braces(line, depth, max_depth, in_string):
    """One line's worth of { / } tracking, skipping brace characters inside
    quoted strings (best-effort, not a real parser). Pulled out of
    _nesting_depth_braces so the loop-over-lines stays flat."""
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            if ch == "\\":
                i += 2
                continue
            if ch == in_string:
                in_string = None
        elif ch in ('"', "'"):
            in_string = ch
        elif ch == "{":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == "}":
            depth = max(0, depth - 1)
        i += 1
    return depth, max_depth, in_string


def _nesting_depth_braces(lines):
    """Deepest brace nesting in a C-like function body, excluding the body's
    own outermost pair. lizard's max_nesting_depth is initialized and never
    incremented, so depth is measured here instead."""
    depth = max_depth = 0
    in_string = None
    for line in lines:
        depth, max_depth, in_string = _scan_line_braces(line, depth, max_depth, in_string)
    return max(0, max_depth - 1)  # depth 1 = the function body itself


def _nesting_depth_indent(lines):
    """Indent-based (Python, Ruby, ...): detect the indent unit from the
    smallest nonzero indent delta seen, then depth = delta // unit."""
    indents = []
    for line in lines:
        width, stripped = _indent_width(line)
        if not stripped or stripped.startswith(("#", "//")):
            continue
        indents.append(width)
    if len(indents) < 2:
        return 0
    base = min(indents)
    deltas = sorted(set(i - base for i in indents if i > base))
    unit = (deltas[0] if deltas else 4) or 4
    return max(0, (max(indents) - base) // unit - 1)


def estimate_nesting_depth(lines, ext):
    """Lizard doesn't compute nesting depth in the installed version
    (verified: FunctionInfo.max_nesting_depth is initialized but never
    incremented in lizard 1.24.0), so this is a deliberate heuristic, not
    a parser. Dispatches on language family rather than branching inline."""
    estimator = _nesting_depth_braces if ext in BRACE_LANGUAGES else _nesting_depth_indent
    return estimator(lines)


def find_duplicate_blocks(lines, min_lines, min_occurrences):
    """Sliding-window duplicate detection within a single file: whitespace-
    normalized N-line windows, hashed, flagged if the same window recurs.
    File-level signal (not per-function) — a cheap proxy for copy-pasted
    branches that often hide behind high cyclomatic complexity."""
    normalized = [" ".join(line.split()) for line in lines]
    seen = {}
    for i in range(len(normalized) - min_lines + 1):
        window = tuple(normalized[i : i + min_lines])
        if all(w == "" for w in window):
            continue
        seen.setdefault(window, []).append(i + 1)  # 1-indexed line number
    return [
        (line_starts, min_lines)
        for line_starts in seen.values()
        if len(line_starts) >= min_occurrences
    ]


def _file_level_findings(lines, thresholds):
    """Findings about the file as a whole — total length and repeated blocks —
    as opposed to the per-function ones lizard reports."""
    findings = []
    if len(lines) > thresholds["max_file_lines"]:
        findings.append(
            f"file is {len(lines)} lines (max {thresholds['max_file_lines']}) "
            "— consider splitting into smaller modules"
        )
    dupes = find_duplicate_blocks(
        lines,
        thresholds["duplicate_block_min_lines"],
        thresholds["duplicate_block_min_occurrences"],
    )
    for line_starts, n in dupes[:5]:  # cap noise
        findings.append(
            f"duplicate {n}-line block repeated at lines {line_starts} "
            "— extract a shared helper"
        )
    return findings


def _function_violations(fn, lines, ext, thresholds):
    """The thresholds one lizard function record breaks, as phrases to join
    into a single finding. Empty when the function is within every limit."""
    fn_lines = lines[fn.start_line - 1 : fn.end_line]
    nesting = estimate_nesting_depth(fn_lines, ext)
    checks = [
        (fn.cyclomatic_complexity > thresholds["max_cyclomatic_complexity"],
         f"cyclomatic complexity {fn.cyclomatic_complexity} "
         f"(max {thresholds['max_cyclomatic_complexity']})"),
        (fn.nloc > thresholds["max_function_length"],
         f"{fn.nloc} lines (max {thresholds['max_function_length']})"),
        (fn.parameter_count > thresholds["max_parameters"],
         f"{fn.parameter_count} parameters (max {thresholds['max_parameters']})"),
        (nesting > thresholds["max_nesting_depth"],
         f"~{nesting} levels of nesting (max {thresholds['max_nesting_depth']})"),
    ]
    return [msg for triggered, msg in checks if triggered]


def analyze_file(path, thresholds):
    """Returns (findings, notices).

    findings = real threshold violations — what "block" mode acts on.
    notices  = informational only (e.g. lizard missing) — always shown,
    never block, so a missing dependency can never stop a write."""
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    findings = _file_level_findings(lines, thresholds)

    try:
        import lizard
    except ImportError:
        return findings, [
            "`lizard` isn't installed — cyclomatic complexity / function "
            "length / parameter-count checks were skipped. Set up the hook venv "
            "once: see .claude/hooks/README.md. File-size and duplicate-block "
            "checks still ran."
        ]

    ext = os.path.splitext(path)[1]
    for fn in lizard.analyze_file(path).function_list:
        violations = _function_violations(fn, lines, ext, thresholds)
        if violations:
            findings.append(f"{fn.name}() at line {fn.start_line}: " + "; ".join(violations))

    return findings, []


def format_report(path, findings, notices):
    """One file's findings and notices as the text the hook prints. Notices
    (e.g. lizard missing) are rendered but never make the report blocking."""
    lines = [f"Complexity findings for {path}:"]
    lines += [f"  - {f}" for f in findings]
    lines += [f"  (note: {n})" for n in notices]
    if findings:
        lines.append(
            "Suggested fixes, in order: guard clauses, extract function, "
            "lookup table / dispatch map instead of long if/elif chains, named "
            "predicates for compound conditions. See the reduce-cyclomatic-"
            "complexity skill for the full playbook."
        )
    return "\n".join(lines)
