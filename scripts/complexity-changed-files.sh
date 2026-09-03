#!/bin/sh
# Writes the NUL-separated list of files a change touched to stdout.
#
#   scripts/complexity-changed-files.sh [<base-sha>]
#
# Shared by both CI flavors so the two cannot disagree about what "the diff"
# means. Progress goes to stderr; stdout is nothing but NUL-separated paths,
# because it is redirected straight into the reporter's --files-from.
#
# -z and --diff-filter=d: NUL separation survives a path containing a space,
# and d drops deletions, whose paths no longer exist to analyze. The reporter
# tolerates a missing path anyway; this keeps the count honest.
set -eu

base=${1:-}

# A base the CI variable named but this clone does not have — a shallow fetch,
# or a force-push that orphaned it. `git diff` against a missing SHA exits 128,
# which under continue-on-error/allow_failure reads as a passing gate that
# measured nothing. Verified: this is exactly how the first run of this kit's
# own workflow "passed".
if [ -n "$base" ] && ! git rev-parse --verify --quiet "$base^{commit}" >/dev/null; then
    echo "complexity: base $base is not in this clone; falling back to HEAD^" >&2
    base=""
fi

if [ -z "$base" ]; then
    base=$(git rev-parse --verify --quiet "HEAD^" || true)
fi

if [ -n "$base" ]; then
    echo "complexity: diffing against $base" >&2
    git diff -z --name-only --diff-filter=d "$base"...HEAD
else
    # Root commit: nothing precedes it, so the whole tree is the change. The one
    # case where whole-tree scoring is the right answer and not the failure mode
    # this gate exists to avoid.
    echo "complexity: root commit; scoring the whole tree" >&2
    git ls-tree -r -z --name-only HEAD
fi
