# complexity-gate

A cyclomatic-complexity bar for a codebase, enforced in three places from one
config file: while an AI coding agent writes code, in CI on the diff, and as a
refactoring skill the agent can invoke to fix what it finds.

`.claude/hooks/complexity_thresholds.json` is the single source of truth. The
`PostToolUse` hook, the CI gate, and the `reduce-cyclomatic-complexity` skill
all read it. One bar in three places, not three copies of a number that drift.

Language support comes from [lizard](https://github.com/terryyin/lizard):
Python, JavaScript, TypeScript, Go, Java, C, C++, C#, Ruby, Swift, Objective-C.

## Why this exists

Agents write code faster than anyone reviews it, and the failure mode is not
bugs — it is a 140-line function with six levels of nesting that passes its
tests. That is invisible to a linter, invisible to a type checker, and obvious
to whoever has to change it in three months.

The design decisions worth knowing before you install it:

**Diff-scoped, not whole-tree.** On the ~90k-line TypeScript monorepo this was
extracted from, a whole-tree run reported 276 findings across 81 files. Gating
on that fails every pipeline forever on code nobody in the pull request wrote.
Scoring only the changed files asks a question with an achievable answer of
zero: *did this change add complexity?*

**Non-blocking by default.** Complexity is a shape problem, not a correctness
or security one. The CI job ships `allow_failure` / `continue-on-error` so it
reports without stopping anyone. Drop that once your team trusts the bar.

**The hook is stricter than CI.** The hook runs all six rules on the single file
just written, where a human is present to judge context. CI runs four of them
(no `duplicate-block`, no `file-length`) because those two are noisy without
that context — 148 of those 276 findings were duplicate-block hits, and the
biggest was an ESLint config where the "repeated block" was the repeated shape
of a rule object. Config data, not an extractable helper.

## Install

```sh
git clone https://github.com/99darwin/complexity-gate.git
cd complexity-gate
./install.sh /path/to/your/repo
```

That copies `.claude/hooks/`, `.claude/skills/reduce-cyclomatic-complexity/`,
and `scripts/` into the target repository, wires the hook into
`.claude/settings.json`, and prints the CI snippet. It never overwrites an
existing `complexity_thresholds.json` (the bar a team already tuned) or an
existing `.claude/settings.json` (a merge that drops someone's formatter hook
is worse than printing four lines for them to paste).

Then, in the target repository:

```sh
python3 -m venv .claude/hooks/.venv
.claude/hooks/.venv/bin/pip install --require-hashes -r scripts/complexity-requirements.txt
```

The hook runs without that venv, but skips every check lizard provides. See
`.claude/hooks/README.md` for why the requirements file is hash-pinned.

## The three surfaces

| | Agent-time hook | CI gate | Skill |
|---|---|---|---|
| Runs on | every Write/Edit in a Claude Code session | every pull/merge request | invocation, by you or the agent |
| Scope | the one file just written | files in the diff | the file or function you point it at |
| Rules | all six | four | reads the same thresholds |
| Effect | notice, or blocks the write in `"mode": "block"` | annotations + job summary; non-blocking | refactors the code |

### 1. Agent-time hook

`.claude/settings.json` registers `run_check_complexity.sh` as a `PostToolUse`
hook on `Write|Edit|MultiEdit`. In the default `"mode": "warn"` it reports and
exits 0. Set `"mode": "block"` and it exits 2, which makes Claude Code fix the
function before it moves on.

Run it by hand over a path:

```sh
.claude/hooks/run_check_complexity.sh --report src/thing.ts
```

### 2. CI gate

**GitHub Actions** — copy `ci/github/complexity.yml` to
`.github/workflows/complexity.yml`. Findings land as diff annotations plus a
job summary that stays complete past GitHub's 10-annotations-per-level cap.
The job is `permissions: contents: read`, so a fork pull request running it
never holds a token that can comment, label, or push.

**GitLab CI** — include `ci/gitlab/complexity.yml` from your `.gitlab-ci.yml`.
Findings reach the merge request widget as a Code Quality report, one entry per
violation with a fingerprint that survives a value changing while still over
threshold.

Both write `gate-findings/complexity.json`, the same raw record, so the two
surfaces cannot disagree about what was found.

### 3. Refactoring skill

`.claude/skills/reduce-cyclomatic-complexity/` is a Claude Code skill that
measures first, fixes the worst offender, and re-measures — in a fixed priority
order (guard clauses, extract function, lookup table, named predicate,
polymorphism last). It reads the same thresholds file, so it stops at the same
line the hook and CI stop at.

## Tuning the bar

Edit `.claude/hooks/complexity_thresholds.json`:

| Key | Default | |
|---|---|---|
| `mode` | `warn` | `warn` reports, `block` exits 2. Affects the hook only. |
| `max_cyclomatic_complexity` | 10 | |
| `max_function_length` | 30 | lines |
| `max_nesting_depth` | 3 | a heuristic, deliberately — see below |
| `max_parameters` | 4 | |
| `max_file_lines` | 300 | |
| `duplicate_block_min_lines` | 4 | |
| `duplicate_block_min_occurrences` | 2 | |
| `include_extensions` | 16 languages | |
| `exclude_path_substrings` | vendor, build, migrations, tests | |

A key with an out-of-shape value is dropped and the shipped default stands, so
a typo degrades the bar rather than crashing the hook. Consider making this
file code-owned: raising a threshold weakens the gate for everyone and should
not be single-developer-approvable.

Start in `warn` for a sprint, tune against your real false-positive rate, then
flip to `block`.

**Nesting depth is a heuristic, not a parser.** lizard 1.24.0 initializes
`FunctionInfo.max_nesting_depth` but never increments it, so this kit counts
braces and indentation itself, skipping string literals. It is reported as
`~N levels` because that tilde is honest.

## Layout

```
.claude/hooks/          the measurements, the config loader, the hook entrypoint
.claude/skills/         the refactoring skill
scripts/                the CI reporter, the GitHub annotator, pinned requirements
ci/github/              GitHub Actions example
ci/gitlab/              GitLab CI example
tests/                  pytest suite for all of the above
install.sh              copies the first three into your repository
```

The `.claude/hooks/` + `scripts/` split is preserved on purpose: the modules
find each other by relative path, so the layout is part of the contract. It is
also why this repository dogfoods its own hook.

## Development

```sh
python3 -m venv .venv
.venv/bin/pip install --require-hashes \
  -r scripts/complexity-requirements.txt \
  -r scripts/complexity-dev-requirements.txt
.venv/bin/python -m pytest tests/
.venv/bin/python .claude/hooks/check_complexity.py --report .
```

Python 3.11+. The self-check on the last line is enforced in CI: this is the
one repository that cannot ship an over-threshold function.

## License

MIT. See [LICENSE](LICENSE).
