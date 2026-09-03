---
name: reduce-cyclomatic-complexity
description: Analyze and refactor code to reduce cyclomatic complexity, function length, nesting depth, and parameter count using lizard, guard clauses, extract-function, and lookup-table patterns, without changing behavior. Use when asked to reduce complexity, simplify a function, resolve a check_complexity.py hook finding, or clean up "AI slop" branching logic.
---

# Reduce Cyclomatic Complexity

## Trigger

Use this skill when:
- The user asks to reduce complexity, simplify, or refactor a function or file.
- A `check_complexity.py` hook finding (warn or block) needs to be resolved.
- A code review flags deep nesting, long functions, or a high branch count.
- You're about to write a function and can tell up front it'll branch heavily — apply the patterns below while writing, not just after.

## Steps

1. **Get current numbers.** Run:
   ```
   python3 .claude/hooks/check_complexity.py --report <path>
   ```
   (falls back to plain `lizard <path>` if the hook isn't present in this repo). This ranks functions by violation, with exact line numbers — don't guess at what's over threshold.

2. **Fix the worst offender first**, then re-measure. For each function the report flags as over threshold (the numbers come from `.claude/hooks/complexity_thresholds.json`; the report prints both the measured value and the limit it broke), pick the smallest transformation that fixes it, in this priority order:
   - **Guard clauses / early return** — replace a nested if/else chain that gates the rest of the function with early returns. Usually the single highest-value fix for nesting depth.
   - **Extract function** — pull a cohesive block (a validation block, one branch's body, a loop body) into a named helper. Fixes length and often complexity at the same time, since the extracted piece carries its own (usually low) CCN.
   - **Lookup table / dispatch map** — replace a long if/elif or switch/case chain keyed on a single value with a dict of `value -> handler` (or `value -> result` for pure data mapping).
   - **Named predicate** — replace a compound boolean condition (`if a and (b or c) and not d`) with a well-named helper function or intermediate variable. Doesn't reduce CCN by itself but makes the next pass legible.
   - **Polymorphism / strategy** — only for OO codebases where the same type-switch recurs across multiple functions; higher-cost, reach for it last.

3. **Never change externally observable behavior.**
   - If the file has tests, run them before and after every change.
   - If it doesn't, add the minimum characterization tests needed to refactor safely — or say so explicitly and ask before refactoring untested code silently.

4. **Re-run the analyzer after each change.** Stop once the file is under threshold, or once additional splitting would hurt readability more than it helps — that's a judgment call, so say so explicitly in the summary rather than force a mechanical split just to clear a number.

5. **Report per function:** before/after CCN, NLOC, nesting depth, and which pattern was applied. Flag anything left over threshold and why (e.g. "this state machine's CCN of 14 is inherent to the 14 states it handles; splitting further would scatter one cohesive decision across multiple files").

## Verification

- Full existing test suite passes, unchanged behavior.
- Re-running `check_complexity.py --report` shows no function over the configured thresholds, or the remainder is explicitly justified in the summary.
- Diff review confirms structure-only changes — call out explicitly any spot where a fix required interpreting ambiguous logic (i.e. you had to decide what an unclear branch *should* do), since that's a behavior judgment call, not a pure refactor, and deserves a second look.

## Notes

- `.claude/hooks/complexity_thresholds.json` is the single shared source of truth for this skill, the `check_complexity.py` hook, and (if wired up per the CI snippet in this kit) the CI gate. Don't hardcode different numbers here — read that file.
- This skill is deliberately about *mechanical* complexity reduction (branch count, length, nesting). It is not a substitute for an architecture review — a function with low CCN can still be in the wrong place, and a function with justified high CCN (e.g. a real state machine or parser) shouldn't be mangled just to hit a number.
