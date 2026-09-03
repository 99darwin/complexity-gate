"""Path parsing and containment — complexity_paths.py.

The diff list is contributor-controlled, so these are the security-relevant
tests in the suite: is_contained is what keeps a pull request from pulling an
arbitrary file's contents into a published report.
"""

import os

import pytest

from complexity_paths import is_contained, project_root, read_paths


def write_list(tmp_path, raw):
    target = tmp_path / "changed"
    target.write_bytes(raw.encode())
    return str(target)


class TestReadPaths:
    def test_reads_newline_separated(self, tmp_path):
        assert read_paths(write_list(tmp_path, "a.py\nb.ts\n")) == ["a.py", "b.ts"]

    def test_reads_nul_separated(self, tmp_path):
        assert read_paths(write_list(tmp_path, "a.py\0b.ts\0")) == ["a.py", "b.ts"]

    def test_nul_mode_preserves_a_path_with_spaces(self, tmp_path):
        """Leading and trailing spaces are legal in filenames. Stripping them
        yields a path that does not exist, so the file silently drops out of
        the scored set — the failure looks like 'clean', not like an error."""
        raw = " leading.py\0trailing.py \0mid space.py\0"
        assert read_paths(write_list(tmp_path, raw)) == [
            " leading.py", "trailing.py ", "mid space.py",
        ]

    def test_newline_mode_strips_carriage_returns(self, tmp_path):
        assert read_paths(write_list(tmp_path, "a.py\r\nb.ts\r\n")) == ["a.py", "b.ts"]

    def test_drops_empty_entries(self, tmp_path):
        assert read_paths(write_list(tmp_path, "a.py\n\n\nb.ts\n")) == ["a.py", "b.ts"]

    def test_normalizes_away_a_leading_dot_slash(self, tmp_path):
        """GitLab matches a Code Quality entry to a diff line by exact string,
        and './libs/x.ts' does not match the 'libs/x.ts' git reports."""
        assert read_paths(write_list(tmp_path, "./libs/x.ts\n")) == ["libs/x.ts"]

    def test_an_empty_list_is_not_an_error(self, tmp_path):
        assert read_paths(write_list(tmp_path, "")) == []

    def test_reads_stdin_for_dash(self, monkeypatch):
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO("a.py\nb.py\n"))
        assert read_paths("-") == ["a.py", "b.py"]


class TestProjectRoot:
    def test_prefers_the_ci_checkout_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CI_PROJECT_DIR", str(tmp_path))
        assert project_root() == os.path.realpath(str(tmp_path))

    def test_falls_back_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert project_root() == os.path.realpath(str(tmp_path))


class TestIsContained:
    @pytest.fixture
    def root(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return os.path.realpath(str(tmp_path))

    def test_accepts_a_relative_path_inside_the_root(self, tmp_path, root):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "a.py").write_text("x = 1\n")
        assert is_contained("src/a.py", root)

    def test_accepts_the_root_itself(self, root):
        assert is_contained(".", root)

    def test_rejects_an_absolute_path(self, root):
        assert not is_contained("/etc/passwd", root)

    def test_rejects_a_parent_traversal(self, root):
        assert not is_contained("../outside.py", root)

    def test_rejects_a_traversal_that_re_enters(self, root):
        """'src/../../elsewhere/a.py' resolves outside even though every
        component before the escape is inside."""
        assert not is_contained("src/../../elsewhere/a.py", root)

    def test_rejects_a_symlink(self, tmp_path, root):
        """A symlink has no complexity of its own, and following one would put
        the target's function names and path into a published report."""
        (tmp_path / "secret.py").write_text("password = 1\n")
        link = tmp_path / "link.py"
        link.symlink_to(tmp_path / "secret.py")
        assert not is_contained("link.py", root)

    def test_rejects_a_symlink_pointing_outside_the_checkout(self, tmp_path, root):
        outside = tmp_path.parent / "outside-target.py"
        outside.write_text("x = 1\n")
        (tmp_path / "escape.py").symlink_to(outside)
        assert not is_contained("escape.py", root)

    def test_a_sibling_prefix_directory_is_not_inside(self, tmp_path, root):
        """'<root>-evil' starts with the root string but is not under it — the
        containment check must compare path segments, not string prefixes."""
        sibling = tmp_path.parent / (tmp_path.name + "-evil")
        sibling.mkdir()
        assert not is_contained(os.path.join("..", sibling.name, "a.py"), root)
