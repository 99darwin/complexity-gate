#!/usr/bin/env sh
# Copy the complexity gate into another repository.
#
#   ./install.sh /path/to/your/repo
#   ./install.sh                      # installs into the current directory
#
# What lands: .claude/hooks/ (the analyzer + the agent-time hook),
# .claude/skills/reduce-cyclomatic-complexity/ (the refactor playbook), and
# scripts/complexity*.py plus the pinned requirements file the CI job installs.
# The CI job itself is NOT copied — pick ci/github/ or ci/gitlab/ and put it
# where that platform expects it. The last section printed below says how.
#
# NEVER CLOBBERS TWO THINGS, by design:
#   - an existing complexity_thresholds.json, which is the bar a team already
#     tuned and agreed on. Re-running the installer to pick up an analyzer fix
#     must not silently reset it.
#   - an existing .claude/settings.json, which holds hook wiring this kit knows
#     nothing about. A merge that drops someone's formatter hook is worse than
#     printing four lines for them to paste.
#
# POSIX sh, not bash: this is the one file people run before they have anything
# else set up, so it should not assume a shell macOS stopped shipping updates for.
set -eu

SRC=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
DEST=${1:-.}

if [ ! -d "$DEST" ]; then
    echo "error: $DEST is not a directory" >&2
    exit 1
fi
DEST=$(CDPATH='' cd -- "$DEST" && pwd)

if [ "$SRC" = "$DEST" ]; then
    echo "error: source and destination are the same directory" >&2
    exit 1
fi

# A git repository is not strictly required to run the analyzer, but it is
# required for the thing to be useful: the CI job is diff-scoped, and
# _repo_root finds the thresholds file by walking up to a .git.
if [ ! -e "$DEST/.git" ]; then
    echo "warning: $DEST is not a git repository — the CI gate is diff-scoped" >&2
    echo "         and the hook locates its config by finding a .git directory." >&2
fi

echo "installing the complexity gate into $DEST"

mkdir -p "$DEST/.claude/hooks"
mkdir -p "$DEST/.claude/skills/reduce-cyclomatic-complexity"
mkdir -p "$DEST/scripts"

for f in check_complexity.py complexity_config.py complexity_lib.py \
         run_check_complexity.sh README.md; do
    cp "$SRC/.claude/hooks/$f" "$DEST/.claude/hooks/$f"
    echo "  .claude/hooks/$f"
done
chmod +x "$DEST/.claude/hooks/check_complexity.py" "$DEST/.claude/hooks/run_check_complexity.sh"

cp "$SRC/.claude/skills/reduce-cyclomatic-complexity/SKILL.md" \
   "$DEST/.claude/skills/reduce-cyclomatic-complexity/SKILL.md"
echo "  .claude/skills/reduce-cyclomatic-complexity/SKILL.md"

for f in complexity-report.py complexity-annotate.py complexity_paths.py \
         complexity_rules.py complexity-changed-files.sh \
         complexity-requirements.txt; do
    cp "$SRC/scripts/$f" "$DEST/scripts/$f"
    echo "  scripts/$f"
done

THRESHOLDS="$DEST/.claude/hooks/complexity_thresholds.json"
if [ -f "$THRESHOLDS" ]; then
    echo "  .claude/hooks/complexity_thresholds.json (kept — your tuned bar)"
else
    cp "$SRC/.claude/hooks/complexity_thresholds.json" "$THRESHOLDS"
    echo "  .claude/hooks/complexity_thresholds.json"
fi

# The venv is per-clone and must never be committed. Appended rather than
# assumed, and only when the pattern is not already covered.
IGNORE="$DEST/.gitignore"
if ! { [ -f "$IGNORE" ] && grep -q '\.claude/hooks/\.venv' "$IGNORE"; }; then
    {
        echo ""
        echo "# Dedicated venv for the complexity PostToolUse hook (.claude/hooks)."
        echo "# Per-clone, created by the setup command in .claude/hooks/README.md."
        echo ".claude/hooks/.venv/"
    } >> "$IGNORE"
    echo "  .gitignore (appended .claude/hooks/.venv/)"
fi

# shellcheck disable=SC2016  # literal: this string is printed for the user to paste.
HOOK_CMD='"$CLAUDE_PROJECT_DIR"/.claude/hooks/run_check_complexity.sh'
SETTINGS="$DEST/.claude/settings.json"
if [ ! -f "$SETTINGS" ]; then
    cp "$SRC/.claude/settings.json" "$SETTINGS"
    echo "  .claude/settings.json"
    SETTINGS_NOTE=""
elif grep -q 'run_check_complexity.sh' "$SETTINGS"; then
    echo "  .claude/settings.json (hook already wired)"
    SETTINGS_NOTE=""
else
    SETTINGS_NOTE="yes"
fi

echo ""
echo "Next:"
echo ""
echo "  1. Install the analyzer for the agent-time hook (once per clone):"
echo "       python3 -m venv .claude/hooks/.venv"
echo "       .claude/hooks/.venv/bin/pip install --require-hashes \\"
echo "         -r scripts/complexity-requirements.txt"
echo ""
echo "  2. Add the CI job:"
echo "       GitHub  — cp $SRC/ci/github/complexity.yml .github/workflows/"
echo "       GitLab  — cp $SRC/ci/gitlab/complexity.yml ci/ and include: it"
echo "                 from .gitlab-ci.yml (check the stage: name matches one"
echo "                 your pipeline defines)"
echo ""
echo "  3. Tune .claude/hooks/complexity_thresholds.json, and consider making it"
echo "     code-owned: raising a threshold weakens the gate for everyone."

if [ -n "$SETTINGS_NOTE" ]; then
    echo ""
    echo "  4. .claude/settings.json already exists and was NOT modified. Add this"
    echo "     hook to its PostToolUse list yourself:"
    echo ""
    echo '       {"type": "command", "command": '"$HOOK_CMD"'}'
fi
