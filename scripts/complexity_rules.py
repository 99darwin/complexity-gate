"""Rules for the complexity gate: what counts as a finding, and how one is
rendered for GitLab.

Split from complexity-report.py, which was over the 300-line file limit the
gate enforces. The seam: this module turns complexity_lib's English finding
strings into typed Violations and back into report shapes; complexity-report.py
decides which files to run over and writes the files out.
"""

import re
from typing import NamedTuple


class Rule(NamedTuple):
    """One finding class: how to recognize it, rate it, and word it.

    pattern's group(1) is the measured value; threshold_key names the
    complexity_thresholds.json entry it was measured against; template is
    formatted with where/value/limit.

    Severity is major for the two rules that indicate genuinely branchy logic,
    minor for the shape/size advisories. Never critical or blocker (the other
    two GitLab levels): this job is allow_failure, and outranking what the
    blocking security gates emit would misrepresent it on the merge request.
    """

    id: str
    pattern: "re.Pattern"
    severity: str
    threshold_key: str
    template: str


# complexity_lib returns findings as preformatted English strings, not records.
# Rather than fork it (which would split the one-source-of-truth this whole kit
# is built around), classify the string back into a rule id here. Each pattern
# is anchored to wording that lives in exactly one f-string in
# _function_violations / _file_level_findings.
#
# ORDER IS LOAD-BEARING: first match wins, and the file-level patterns must be
# tried before the function-level ones. complexity_lib renders a file-length
# finding as "file is 515 lines (max 300)", which the function-length pattern
# `(\d+) lines \(max` also matches — so with the looser pattern first, every
# oversized file was reported as an oversized function at line 1.
RULES = [
    Rule("file-length", re.compile(r"file is (\d+) lines"), "minor",
         "max_file_lines", "This file is {value} lines (max {limit})."),
    Rule("duplicate-block", re.compile(r"duplicate (\d+)-line block"), "minor",
         "duplicate_block_min_lines",
         "{value}-line block repeated in this file (min {limit})."),
    Rule("cyclomatic-complexity", re.compile(r"cyclomatic complexity (\d+)"), "major",
         "max_cyclomatic_complexity",
         "{where} has cyclomatic complexity {value} (max {limit})."),
    Rule("function-length", re.compile(r"(\d+) lines \(max"), "minor",
         "max_function_length", "{where} is {value} lines (max {limit})."),
    Rule("parameter-count", re.compile(r"(\d+) parameters \(max"), "minor",
         "max_parameters", "{where} takes {value} parameters (max {limit})."),
    Rule("nesting-depth", re.compile(r"~(\d+) levels of nesting"), "major",
         "max_nesting_depth", "{where} nests ~{value} levels deep (max {limit})."),
]

RULES_BY_ID = {rule.id: rule for rule in RULES}
ALL_RULES = [rule.id for rule in RULES]

FUNCTION_RE = re.compile(r"^(?P<name>.+?)\(\) at line (?P<line>\d+): (?P<body>.*)$")


def classify(text):
    """(rule_id, measured_value) for a finding string, or (None, None)."""
    for rule in RULES:
        m = rule.pattern.search(text)
        if m:
            return rule.id, int(m.group(1))
    return None, None


class Violation(NamedTuple):
    """One threshold breach, parsed back out of a complexity_lib string.

    scope is the enclosing function name, or None for a file-level finding.
    Kept as one value rather than four positional fields so the writers below
    stay under the parameter-count threshold this script itself enforces.
    """

    rule: str
    value: int
    line: int
    scope: "str | None"
    message: str


def split_finding(finding):
    """One complexity_lib string -> [Violation, ...].

    A function-level finding joins its violations with '; ' ("f() at line 12:
    cyclomatic complexity 14 (max 10); 6 parameters (max 4)"), and each of
    those is a separate Code Quality entry with its own rule and severity —
    otherwise one fingerprint carries two unrelated problems and fixing one
    leaves the entry standing.
    """
    m = FUNCTION_RE.match(finding)
    if not m:
        rule_id, value = classify(finding)
        return [Violation(rule_id, value, 1, None, finding)] if rule_id else []

    line = int(m.group("line"))
    scope = m.group("name")
    out = []
    for part in m.group("body").split("; "):
        rule_id, value = classify(part)
        if rule_id:
            out.append(Violation(rule_id, value, line, scope, finding))
    return out


def describe(rule_id, value, scope, thresholds):
    """One violation as the human-facing sentence GitLab shows in the merge
    request widget: what broke, by how much, and the fix order to try."""
    rule = RULES_BY_ID[rule_id]
    text = rule.template.format(
        where=f"{scope}()" if scope else "this file",
        value=value,
        limit=thresholds[rule.threshold_key],
    )
    return text + (
        " Fixes, in order: guard clauses, extract function, lookup table instead"
        " of a long if/elif chain, named predicates for compound conditions."
    )


def _record(path, v):
    """One violation as a complexity.json record — the raw fields, for the
    retained artifact and anything that reads it later."""
    return {
        "path": path,
        "rule": v.rule,
        "value": v.value,
        "line": v.line,
        "scope": v.scope,
        "message": v.message,
    }


def _entry(path, v, thresholds):
    """One violation as a GitLab Code Quality entry, which is what puts it on
    the merge request diff. See the fingerprint comment for why it is built
    the way it is."""
    return {
        "type": "issue",
        "check_name": f"complexity/{v.rule}",
        "categories": ["Complexity"],
        "description": describe(v.rule, v.value, v.scope, thresholds),
        # Unique per occurrence. GitLab collapses Code Quality entries sharing a
        # fingerprint into one, so path+rule alone would hide a second offending
        # function in the same file. Deliberately excludes the measured value so
        # the entry keeps its identity when a refactor moves complexity 14 to 12
        # and it is still over threshold.
        "fingerprint": f"complexity:{v.rule}:{path}:{v.scope or 'file'}:{v.line}",
        "severity": RULES_BY_ID[v.rule].severity,
        "location": {"path": path, "lines": {"begin": v.line}},
    }
