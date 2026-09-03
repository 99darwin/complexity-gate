# Complexity hook (`.claude/hooks/`)

A `PostToolUse` hook that measures the file Claude Code just wrote or edited and
reports functions that are harder to read than this repo's agreed bar. The same
code backs the CI gate (`ci/github/` and `ci/gitlab/`) and the
`reduce-cyclomatic-complexity` skill, so all three judge a file by one
`complexity_thresholds.json` rather than three copies of a number.

## Setup — one command, once per clone

The hook needs `lizard`, and it looks for it in a dedicated venv beside this
file. Without that venv it still runs, but the cyclomatic-complexity,
function-length and parameter-count checks are skipped and you get a notice on
every write instead:

```sh
python3 -m venv .claude/hooks/.venv
.claude/hooks/.venv/bin/pip install --require-hashes -r scripts/complexity-requirements.txt
```

`.claude/hooks/.venv/` is gitignored, so this is per-clone rather than something
you can inherit from a teammate.

**Why the pinned requirements file and not `pip install lizard`.** That is the
exact closure the CI gate installs. An unpinned install puts a different
analyzer version behind the agent-time hook than behind the gate, so a write the
hook called clean can still fail CI — or the reverse — for no reason a
contributor can see. `--require-hashes` is what makes the pin real: without it a
matching version from a different artifact still installs.

## What runs where

| | agent-time hook | CI gate |
|---|---|---|
| Population | Claude Code CLI sessions only | every commit, whoever wrote it |
| Scope | the single file just written | files in the merge/pull request diff |
| Rules | all six | four (no duplicate-block, no file-length) |
| On a finding | notice, or blocks the write when `"mode": "block"` | reports; the job is non-blocking |

They are complements, not redundancy: the hook catches complexity at the moment
it is introduced, and the gate is the backstop for everything the hook never saw.

## Files

- `run_check_complexity.sh` — what `.claude/settings.json` registers. Picks the
  venv interpreter when present, else ambient `python3`.
- `check_complexity.py` — entrypoint. Hook mode reads a JSON payload on stdin;
  `--report <paths>` runs the same checks from a shell.
- `complexity_lib.py` — the measurements. Also the single import surface: it
  re-exports the config names.
- `complexity_config.py` — where the numbers come from and which files they apply
  to. Only the repository root's `complexity_thresholds.json` is honored, on
  purpose — see `_candidate_config_paths`.
- `complexity_thresholds.json` — the bar. `"mode"` (`warn` / `block`) controls
  only the hook; CI enforcement is `allow_failure` on the job.

## Tuning the bar

Edit `complexity_thresholds.json`. Consider making it code-owned (a CODEOWNERS
entry, or GitLab's equivalent), because raising a threshold weakens the gate for
everyone and should not be single-developer-approvable. A key with an
out-of-shape value is dropped and the shipped default stands, so a typo degrades
the bar rather than crashing the hook.

## Self-check

The checker holds itself to its own thresholds — including the 300-line file
limit, which is why the config and rules modules are separate files:

```sh
.claude/hooks/run_check_complexity.sh --report .
```

`--report` takes exactly one path (a file or a directory it walks), not a list.

The behavior of every module here is pinned by the `pytest` suite in `tests/`
(in the complexity-gate repository, not in the repositories this is installed
into):

```sh
python3 -m pytest tests/
```
