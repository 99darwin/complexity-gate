"""
complexity_config.py — where the thresholds come from and which files they
apply to.

Split out of complexity_lib.py, which was over the 300-line file limit it
enforces. The seam is real, not arbitrary: everything here answers "what bar,
for which files", and nothing here measures anything. complexity_lib re-exports
the public names, so importers keep using it as the single entrypoint.
"""

import json
import os

THRESHOLDS_FILENAME = "complexity_thresholds.json"

DEFAULT_THRESHOLDS = {
    "mode": "warn",
    "max_cyclomatic_complexity": 10,
    "max_function_length": 30,
    "max_nesting_depth": 3,
    "max_parameters": 4,
    "max_file_lines": 300,
    "duplicate_block_min_lines": 4,
    "duplicate_block_min_occurrences": 2,
    "include_extensions": [
        ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java",
        ".rb", ".c", ".cc", ".cpp", ".h", ".hpp", ".cs", ".swift", ".m",
    ],
    "exclude_path_substrings": [
        "/node_modules/", "/dist/", "/build/", "/vendor/", "/.git/",
        "/migrations/", "/__pycache__/", "/.venv/", "/venv/",
        "_test.", ".test.", ".spec.", "/test/", "/tests/", "/testdata/",
    ],
}

def _repo_root(start_dir):
    """The one directory whose .claude/hooks/ config is honored: CI_PROJECT_DIR
    if set, else the nearest ancestor of start_dir holding a .git, else None.

    realpath, not abspath, and deliberately: getcwd() is always symlink-resolved,
    while CI_PROJECT_DIR is whatever string the runner set. When a checkout is
    reached through a symlink those two disagree as strings, and any comparison
    between them silently stops matching. Same reason project_root() in
    scripts/complexity_paths.py is realpath.
    """
    env_root = os.environ.get("CI_PROJECT_DIR")
    if env_root:
        return os.path.realpath(env_root)
    d = os.path.realpath(start_dir)
    while True:
        if os.path.exists(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent


def _candidate_config_paths(start_dir):
    """Search order: the repository root's .claude/hooks/, then this file's own
    directory as last resort.

    NOT a walk up from the analyzed file. An upward search is nearest-wins, so
    libs/foo/.claude/hooks/complexity_thresholds.json would beat the root file
    for everything under libs/foo/ — and a code-ownership rule anchored at
    /.claude/hooks/ (a leading slash binds it to the repository root, in both
    CODEOWNERS and GitLab's equivalent) does not cover the nested copy, so that
    copy is single-developer-approvable while the file it overrides is not.
    Reading only the root file closes that by construction rather than by adding
    a second ownership rule that has to stay in sync.

    It also removes the climb past the repository entirely, which used to probe
    /builds/.claude/ and /.claude/ in CI — plantable by another job on a shared
    runner — and ~/.claude/hooks/ locally, which would quietly give one
    developer a different bar from CI. The point of a checked-in thresholds file
    is that everyone is judged by the same numbers.
    """
    root = _repo_root(start_dir)
    if root:
        yield os.path.join(root, ".claude", "hooks", THRESHOLDS_FILENAME)
    yield os.path.join(os.path.dirname(os.path.abspath(__file__)), THRESHOLDS_FILENAME)


def _read_config(path):
    """Parsed JSON at path, or None if it is absent or unreadable. Returning
    None rather than raising is what lets the caller fall through to the next
    candidate — a broken config must not take the hook down with it."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path) as f:
            config = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    # A file holding a valid JSON array, string, or number parses fine and then
    # raises AttributeError on .items() in the caller, which takes down the hook
    # and the CI reporter rather than falling back to defaults. Treat any
    # non-object as no config at all.
    return config if isinstance(config, dict) else None


def _is_valid_override(key, value):
    """True if value has the shape DEFAULT_THRESHOLDS uses for key.

    A wrong-typed override is a config typo whose failure mode is silent and
    late: "include_extensions": null makes should_skip raise TypeError on the
    next write, and "max_parameters": "4" raises the first time a function is
    measured. Both surface as a broken hook rather than a bad config. Keys
    that fail here are dropped so the shipped default stands — a degraded bar
    beats a gate that crashes. Unknown keys are dropped too; they were never
    read.
    """
    default = DEFAULT_THRESHOLDS.get(key)
    if key == "mode":
        return value in ("warn", "block")
    if isinstance(default, bool):
        return isinstance(value, bool)
    if isinstance(default, int):
        # 1 is a coherent floor for every count here except the duplicate-block
        # occurrence one, where it is degenerate: a block "repeated once" is
        # every window in the file, so find_duplicate_blocks would report all
        # of them.
        minimum = 2 if key == "duplicate_block_min_occurrences" else 1
        return isinstance(value, int) and not isinstance(value, bool) and value >= minimum
    if isinstance(default, list):
        return isinstance(value, list) and all(isinstance(v, str) for v in value)
    return False


def load_thresholds(start_dir):
    """Repo-local .claude/hooks/complexity_thresholds.json wins over the
    config next to this script, which wins over DEFAULT_THRESHOLDS. Never
    raises — a missing, broken, or wrong-typed config falls back to defaults,
    per key."""
    for path in _candidate_config_paths(start_dir):
        cfg = _read_config(path)
        if cfg is not None:
            merged = dict(DEFAULT_THRESHOLDS)
            merged.update({
                k: v
                for k, v in cfg.items()
                if not k.startswith("_") and _is_valid_override(k, v)
            })
            return merged
    return dict(DEFAULT_THRESHOLDS)


def should_skip(path, thresholds):
    """True if path is outside the analyzed set: an extension the checks do not
    understand, or a path matching an exclusion (generated code, vendored
    dependencies, tests)."""
    ext = os.path.splitext(path)[1]
    if ext not in thresholds["include_extensions"]:
        return True
    # Leading "/" so a repo-relative path is matched the same as an absolute
    # one. The directory exclusions are written slash-wrapped ("/tests/"), so
    # without this the hook skips /repo/tests/x.py while `--report tests/x.py`
    # analyzes it — same file, two answers, depending on how it was named.
    # The unwrapped entries ("_test.", ".spec.") are unaffected.
    norm = "/" + path.replace(os.sep, "/").lstrip("/")
    return any(s in norm for s in thresholds["exclude_path_substrings"])
