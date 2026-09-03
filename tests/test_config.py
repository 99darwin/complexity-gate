"""Threshold loading and file selection — complexity_config.py.

The theme here is that every failure mode of a bad config must degrade to the
shipped default rather than crash, because this code runs inside a
PostToolUse hook where an exception blocks a write for a reason the developer
cannot see.
"""

import pytest
from conftest import write_thresholds

from complexity_config import (
    DEFAULT_THRESHOLDS,
    _is_valid_override,
    load_thresholds,
    should_skip,
)


class TestIsValidOverride:
    @pytest.mark.parametrize("value", ["warn", "block"])
    def test_accepts_the_two_modes(self, value):
        assert _is_valid_override("mode", value)

    @pytest.mark.parametrize("value", ["Warn", "off", "", True, 1, None])
    def test_rejects_anything_else_for_mode(self, value):
        assert not _is_valid_override("mode", value)

    def test_accepts_a_positive_int(self):
        assert _is_valid_override("max_cyclomatic_complexity", 15)

    @pytest.mark.parametrize("value", ["10", 10.0, None, [], 0, -1])
    def test_rejects_non_int_and_sub_floor_values(self, value):
        assert not _is_valid_override("max_cyclomatic_complexity", value)

    def test_rejects_bool_for_an_int_key(self):
        # bool is a subclass of int, so a plain isinstance check would accept
        # `"max_parameters": true` and then compare parameter counts against 1.
        assert not _is_valid_override("max_parameters", True)

    def test_duplicate_occurrences_floor_is_two_not_one(self):
        # A block "repeated once" is every window in the file, so 1 would make
        # find_duplicate_blocks report all of them.
        assert not _is_valid_override("duplicate_block_min_occurrences", 1)
        assert _is_valid_override("duplicate_block_min_occurrences", 2)

    def test_accepts_a_list_of_strings(self):
        assert _is_valid_override("include_extensions", [".py", ".rs"])

    @pytest.mark.parametrize("value", [[".py", 3], ".py", None, {}])
    def test_rejects_a_non_string_list(self, value):
        assert not _is_valid_override("include_extensions", value)

    def test_rejects_an_unknown_key(self):
        assert not _is_valid_override("max_gadgets", 3)


class TestLoadThresholds:
    def test_repo_config_wins_over_defaults(self, fake_repo):
        write_thresholds(fake_repo, {"max_cyclomatic_complexity": 25})
        loaded = load_thresholds(str(fake_repo))
        assert loaded["max_cyclomatic_complexity"] == 25

    def test_unset_keys_keep_their_defaults(self, fake_repo):
        write_thresholds(fake_repo, {"max_cyclomatic_complexity": 25})
        loaded = load_thresholds(str(fake_repo))
        assert loaded["max_function_length"] == DEFAULT_THRESHOLDS["max_function_length"]

    def test_a_bad_value_is_dropped_and_its_neighbours_survive(self, fake_repo):
        write_thresholds(
            fake_repo,
            {"max_parameters": "four", "max_function_length": 50},
        )
        loaded = load_thresholds(str(fake_repo))
        assert loaded["max_parameters"] == DEFAULT_THRESHOLDS["max_parameters"]
        assert loaded["max_function_length"] == 50

    def test_underscore_keys_are_not_read(self, fake_repo):
        write_thresholds(fake_repo, {"_comment": "hi", "_mode_comment": "x"})
        loaded = load_thresholds(str(fake_repo))
        assert "_comment" not in loaded

    def test_unparseable_json_falls_back_to_defaults(self, fake_repo):
        write_thresholds(fake_repo, "{ not json")
        assert load_thresholds(str(fake_repo))["max_parameters"] == \
            DEFAULT_THRESHOLDS["max_parameters"]

    def test_a_json_array_is_treated_as_no_config(self, fake_repo):
        # Parses fine, then raises AttributeError on .items() if not guarded —
        # which would take the hook down instead of degrading.
        write_thresholds(fake_repo, "[1, 2, 3]")
        assert load_thresholds(str(fake_repo)) == DEFAULT_THRESHOLDS

    def test_no_config_anywhere_returns_defaults(self, fake_repo):
        assert load_thresholds(str(fake_repo))["max_file_lines"] == \
            DEFAULT_THRESHOLDS["max_file_lines"]

    def test_a_nested_config_does_not_override_the_root(self, fake_repo):
        """The search is root-only, not nearest-wins: a config committed deep in
        the tree must not quietly weaken the bar for its own subtree."""
        write_thresholds(fake_repo, {"max_cyclomatic_complexity": 10})
        nested = fake_repo / "libs" / "foo"
        write_thresholds(nested, {"max_cyclomatic_complexity": 99})
        assert load_thresholds(str(nested))["max_cyclomatic_complexity"] == 10

    def test_env_project_dir_wins_over_the_git_search(self, fake_repo, tmp_path, monkeypatch):
        other = tmp_path / "elsewhere"
        write_thresholds(other, {"max_parameters": 7})
        monkeypatch.setenv("CI_PROJECT_DIR", str(other))
        assert load_thresholds(str(fake_repo))["max_parameters"] == 7


class TestShouldSkip:
    @pytest.fixture
    def thresholds(self):
        return dict(DEFAULT_THRESHOLDS)

    @pytest.mark.parametrize("path", ["src/app.py", "src/app.ts", "src/app.go"])
    def test_analyzes_known_extensions(self, path, thresholds):
        assert not should_skip(path, thresholds)

    @pytest.mark.parametrize("path", ["README.md", "config.yml", "Makefile"])
    def test_skips_unknown_extensions(self, path, thresholds):
        assert should_skip(path, thresholds)

    @pytest.mark.parametrize(
        "path",
        [
            "tests/test_thing.py",
            "src/thing.spec.ts",
            "src/thing_test.go",
            "node_modules/pkg/index.js",
            "dist/bundle.js",
            "prisma/migrations/001/steps.ts",
        ],
    )
    def test_skips_excluded_paths(self, path, thresholds):
        assert should_skip(path, thresholds)

    def test_a_repo_relative_dir_match_behaves_like_an_absolute_one(self, thresholds):
        """Without the leading-slash normalization these disagree: the hook is
        handed an absolute path and the reporter a relative one, and the same
        file gets two different answers depending on who asked."""
        assert should_skip("/repo/tests/x.py", thresholds)
        assert should_skip("tests/x.py", thresholds)

    def test_a_directory_named_like_an_exclusion_substring_is_not_skipped(self, thresholds):
        # "contests/" contains "tests/" but not "/tests/".
        assert not should_skip("contests/x.py", thresholds)
