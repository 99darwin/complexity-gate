"""Path handling for the complexity gate.

Split from complexity-report.py so the containment rules that decide which
files may be analyzed live in one place, separate from the reporting logic
that formats what was found.
"""

import os
import sys


def read_paths(source):
    """Paths from a file, or from stdin when source is "-"."""
    if source == "-":
        raw = sys.stdin.read()
    else:
        with open(source, encoding="utf-8") as f:
            raw = f.read()
    if "\0" in raw:
        # NUL-delimited (`git diff -z`, `find -print0`): a path is exactly the
        # bytes between separators. Do NOT strip — leading and trailing spaces
        # are legal in filenames, and stripping them yields a path that does
        # not exist, so the file silently drops out of the scored set. This
        # branch is the one CI takes.
        parts = [p for p in raw.split("\0") if p]
    else:
        # Newline-delimited fallback cannot represent such a name unambiguously
        # anyway, so strip here: a trailing "\r" from a CRLF producer, or stray
        # indentation in a hand-written list, is not part of the path.
        parts = [p.strip() for p in raw.splitlines()]
        parts = [p for p in parts if p]
    # normpath strips a leading "./": GitLab matches a Code Quality entry to a
    # diff line by exact path string, and "./libs/x.ts" does not match the
    # "libs/x.ts" git reports, which silently drops the entry from the merge
    # request surface this job exists to populate.
    return [os.path.normpath(p) for p in parts]


def project_root():
    """The directory analyzed paths must stay inside. CI_PROJECT_DIR is what the
    runner checks out into; cwd is the local-run equivalent."""
    return os.path.realpath(os.environ.get("CI_PROJECT_DIR", os.getcwd()))


def is_contained(path, root):
    """True if path is a repo-relative path resolving inside root.

    The diff list is contributor-controlled, and isfile/open both follow
    symlinks: without this, a merge request adding a symlink or an absolute
    path gets that file's function names and path into location.path, the
    description and the fingerprint — all of which reach the MR widget and a
    90-day artifact. Verified reproducible before this guard existed.

    Symlinks are skipped, not resolved: a symlink has no complexity of its own,
    and its target is either in the diff already or outside the checkout.
    """
    if os.path.isabs(path) or os.path.islink(path):
        return False
    resolved = os.path.realpath(path)
    return resolved == root or resolved.startswith(root + os.sep)
