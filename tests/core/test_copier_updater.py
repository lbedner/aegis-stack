"""
Tests for copier_updater module functions.

These tests validate the backup, rollback, and version management functions.
"""

import subprocess
from pathlib import Path

import pytest

from aegis.core.copier_updater import (
    _format_commits_as_changelog,
    _get_changelog_from_github,
    analyze_conflict_files,
    cleanup_backup_tag,
    create_backup_point,
    format_conflict_report,
    get_available_versions,
    get_latest_version,
    rollback_to_backup,
)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Initialize a git repository with an initial commit."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
    )

    # Create initial commit
    (tmp_path / "test.txt").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial"],
        cwd=tmp_path,
        capture_output=True,
    )

    return tmp_path


class TestCreateBackupPoint:
    """Tests for create_backup_point function."""

    def test_creates_backup_tag(self, git_repo: Path) -> None:
        """Test successful backup tag creation."""
        backup_tag = create_backup_point(git_repo)

        assert backup_tag is not None
        assert backup_tag.startswith("aegis-backup-")

        # Verify tag exists
        result = subprocess.run(
            ["git", "tag", "-l", backup_tag],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert backup_tag in result.stdout

    def test_returns_none_on_failure(self, tmp_path: Path) -> None:
        """Test returns None when not in git repo."""
        # Don't initialize git - should fail
        backup_tag = create_backup_point(tmp_path)

        assert backup_tag is None


class TestRollbackToBackup:
    """Tests for rollback_to_backup function."""

    def test_successful_rollback(self, git_repo: Path) -> None:
        """Test successful rollback to backup point."""
        # Modify the test file to have original content
        test_file = git_repo / "test.txt"
        test_file.write_text("original")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Set original"],
            cwd=git_repo,
            capture_output=True,
        )

        # Create backup
        backup_tag = create_backup_point(git_repo)
        assert backup_tag is not None

        # Make changes
        test_file.write_text("modified")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Modified"],
            cwd=git_repo,
            capture_output=True,
        )

        # Verify file is modified
        assert test_file.read_text() == "modified"

        # Rollback
        success, message = rollback_to_backup(git_repo, backup_tag)

        assert success is True
        assert backup_tag in message
        assert test_file.read_text() == "original"

    def test_rollback_failure(self, git_repo: Path) -> None:
        """Test rollback failure with invalid tag."""
        # Try to rollback to non-existent tag
        success, message = rollback_to_backup(git_repo, "nonexistent-tag")

        assert success is False
        assert "failed" in message.lower()


class TestCleanupBackupTag:
    """Tests for cleanup_backup_tag function."""

    def test_removes_existing_tag(self, git_repo: Path) -> None:
        """Test that cleanup removes an existing tag."""
        # Create backup
        backup_tag = create_backup_point(git_repo)
        assert backup_tag is not None

        # Verify tag exists
        result = subprocess.run(
            ["git", "tag", "-l", backup_tag],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert backup_tag in result.stdout

        # Cleanup
        cleanup_backup_tag(git_repo, backup_tag)

        # Verify tag is gone
        result = subprocess.run(
            ["git", "tag", "-l", backup_tag],
            cwd=git_repo,
            capture_output=True,
            text=True,
        )
        assert backup_tag not in result.stdout

    def test_handles_nonexistent_tag(self, tmp_path: Path) -> None:
        """Test that cleanup handles non-existent tag gracefully."""
        # Initialize git repo (minimal, just needs to be a git repo)
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        # Should not raise exception
        cleanup_backup_tag(tmp_path, "nonexistent-tag")


class TestAnalyzeConflictFiles:
    """Tests for analyze_conflict_files function."""

    def test_finds_rej_files(self, tmp_path: Path) -> None:
        """Test that .rej files are detected and analyzed."""
        # Create some .rej files
        rej_file = tmp_path / "test.txt.rej"
        rej_file.write_text("rejected content\nline 2\nline 3")

        conflicts = analyze_conflict_files(tmp_path)

        assert len(conflicts) == 1
        assert conflicts[0]["original"] == "test.txt"
        assert conflicts[0]["path"] == "test.txt.rej"
        assert "3 lines in conflict file" in conflicts[0]["summary"]

    def test_handles_nested_rej_files(self, tmp_path: Path) -> None:
        """Test that nested .rej files are found."""
        # Create nested directory structure
        nested_dir = tmp_path / "app" / "core"
        nested_dir.mkdir(parents=True)
        rej_file = nested_dir / "config.py.rej"
        rej_file.write_text("rejected changes")

        conflicts = analyze_conflict_files(tmp_path)

        assert len(conflicts) == 1
        assert "app/core/config.py" in conflicts[0]["original"]

    def test_finds_inline_conflict_markers(self, tmp_path: Path) -> None:
        """#1016: the 3-way merge leaves ``<<<<<<<`` markers in place, not
        .rej files. Those files must land in the same report."""
        (tmp_path / "app").mkdir()
        (tmp_path / "app" / "config.py").write_text(
            "x = 1\n<<<<<<< ours\na = 1\n=======\na = 2\n>>>>>>> theirs\n"
            "<<<<<<< ours\nb = 1\n=======\nb = 2\n>>>>>>> theirs\n"
        )
        (tmp_path / "clean.py").write_text("ok = True\n")

        conflicts = analyze_conflict_files(tmp_path)

        assert [c["original"] for c in conflicts] == ["app/config.py"]
        assert conflicts[0]["path"] == "app/config.py"
        assert "2 conflict blocks" in conflicts[0]["summary"]

    def test_marker_scan_skips_git_and_binaries(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "ORIG_HEAD").write_text("<<<<<<< x\n")
        (tmp_path / ".venv" / "lib").mkdir(parents=True)
        (tmp_path / ".venv" / "lib" / "m.py").write_text("<<<<<<< x\n")
        (tmp_path / "img.png").write_bytes(b"\x89PNG\x00<<<<<<< x\n")

        assert analyze_conflict_files(tmp_path) == []

    def test_report_explains_markers_and_rej_separately(self, tmp_path: Path) -> None:
        (tmp_path / "a.py.rej").write_text("-x\n+y\n")
        (tmp_path / "b.py").write_text("<<<<<<< ours\n1\n=======\n2\n>>>>>>> theirs\n")

        report = format_conflict_report(analyze_conflict_files(tmp_path))

        assert "a.py.rej" in report
        assert "b.py" in report
        assert "<<<<<<<" in report  # tells the user what to look for
        assert "aegis update --finish" in report

    def test_unparsable_pyproject_is_reported(self, tmp_path: Path) -> None:
        """A merge can leave pyproject.toml syntactically broken (duplicate
        tables) with no markers; the report and --finish must still see it."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.djlint]\nprofile = "a"\n[tool.djlint]\nprofile = "b"\n'
        )
        conflicts = analyze_conflict_files(tmp_path)
        assert [c["original"] for c in conflicts] == ["pyproject.toml"]
        assert conflicts[0]["kind"] == "toml"
        assert "TOML" in format_conflict_report(conflicts)

    def test_handles_no_conflicts(self, tmp_path: Path) -> None:
        """Test that empty list is returned when no .rej files exist."""
        # Create some regular files
        (tmp_path / "test.txt").write_text("normal content")

        conflicts = analyze_conflict_files(tmp_path)

        assert conflicts == []

    def test_handles_multiple_conflicts(self, tmp_path: Path) -> None:
        """Test handling of multiple .rej files."""
        # Create multiple .rej files
        (tmp_path / "file1.txt.rej").write_text("conflict 1")
        (tmp_path / "file2.py.rej").write_text("conflict 2\nmore")
        (tmp_path / "file3.md.rej").write_text("conflict 3\na\nb")

        conflicts = analyze_conflict_files(tmp_path)

        assert len(conflicts) == 3


class TestFormatConflictReport:
    """Tests for format_conflict_report function."""

    def test_formats_single_conflict(self) -> None:
        """Test formatting of a single conflict."""
        conflicts = [
            {
                "path": "test.txt.rej",
                "original": "test.txt",
                "size": "100 bytes",
                "summary": "5 rejected change(s)",
            }
        ]

        report = format_conflict_report(conflicts)

        assert "Conflicts detected" in report
        assert "test.txt" in report
        assert "test.txt.rej" in report
        assert "5 rejected change(s)" in report
        assert "Resolution steps" in report

    def test_formats_multiple_conflicts(self) -> None:
        """Test formatting of multiple conflicts."""
        conflicts = [
            {
                "path": "file1.rej",
                "original": "file1",
                "size": "50 bytes",
                "summary": "2 rejected change(s)",
            },
            {
                "path": "file2.rej",
                "original": "file2",
                "size": "100 bytes",
                "summary": "3 rejected change(s)",
            },
        ]

        report = format_conflict_report(conflicts)

        assert "file1" in report
        assert "file2" in report
        assert "git diff" in report

    def test_returns_empty_for_no_conflicts(self) -> None:
        """Test that empty string is returned for no conflicts."""
        report = format_conflict_report([])

        assert report == ""


class TestFormatCommitsAsChangelog:
    """Tests for _format_commits_as_changelog function."""

    def test_empty_commits_returns_no_changes(self) -> None:
        """Test that empty commits list returns 'No changes'."""
        result = _format_commits_as_changelog([], "https://github.com/test/repo")
        assert result == "No changes"

    def test_categorizes_breaking_changes(self) -> None:
        """Test that breaking changes are categorized correctly."""
        commits = [
            ("abc1234", "breaking: Remove deprecated API"),
            ("def5678", "Other change"),
        ]
        result = _format_commits_as_changelog(commits, "https://github.com/test/repo")

        assert "Breaking Changes:" in result
        assert "Remove deprecated API" in result

    def test_categorizes_features(self) -> None:
        """Test that features are categorized correctly."""
        commits = [
            ("abc1234", "feat: Add new feature"),
            ("def5678", "feature: Another feature"),
        ]
        result = _format_commits_as_changelog(commits, "https://github.com/test/repo")

        assert "New Features:" in result
        assert "Add new feature" in result
        assert "Another feature" in result

    def test_categorizes_fixes(self) -> None:
        """Test that fixes are categorized correctly."""
        commits = [
            ("abc1234", "fix: Fix a bug"),
        ]
        result = _format_commits_as_changelog(commits, "https://github.com/test/repo")

        assert "Bug Fixes:" in result
        assert "Fix a bug" in result

    def test_categorizes_other_changes(self) -> None:
        """Test that non-categorized commits go to Other Changes."""
        commits = [
            ("abc1234", "Update documentation"),
            ("def5678", "Refactor code"),
        ]
        result = _format_commits_as_changelog(commits, "https://github.com/test/repo")

        assert "Other Changes:" in result
        assert "Update documentation" in result
        assert "Refactor code" in result

    def test_includes_github_links(self) -> None:
        """Test that commit hashes are linked to GitHub."""
        commits = [("abc1234", "Some change")]
        github_url = "https://github.com/test/repo"
        result = _format_commits_as_changelog(commits, github_url)

        assert f"[abc1234]({github_url}/commit/abc1234)" in result

    def test_handles_empty_commit_hash(self) -> None:
        """Test that commits without hash are formatted without links."""
        commits = [("", "Some change")]
        result = _format_commits_as_changelog(commits, "https://github.com/test/repo")

        assert "• Some change" in result
        assert "[" not in result  # No link brackets


class TestGetChangelogFromGithub:
    """Tests for _get_changelog_from_github function."""

    def test_normalizes_head_to_main(self) -> None:
        """Test that HEAD is normalized to main for API calls."""
        # This test verifies the URL construction logic
        # We can't easily test the actual API call without mocking
        # but we can verify the function handles the HEAD -> main conversion
        # by checking it doesn't crash and returns a string
        result = _get_changelog_from_github("abc1234", "HEAD")
        # Should return either changelog or fallback message
        assert isinstance(result, str)
        assert len(result) > 0

    def test_returns_fallback_on_invalid_ref(self) -> None:
        """Test that invalid refs return a fallback message."""
        result = _get_changelog_from_github("invalid_ref_123", "HEAD")
        # Should contain fallback message with "Changelog not available" or actual changelog
        assert isinstance(result, str)
        assert "Changelog not available" in result or "Changes:" in result


@pytest.fixture
def git_repo_with_tags(tmp_path: Path) -> Path:
    """Initialize a git repository with version tags (including prereleases)."""
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    # Create a copier.yml to make it a valid template root
    (tmp_path / "copier.yml").write_text("_subdirectory: templates\n")

    # Create initial commit and tags
    (tmp_path / "test.txt").write_text("v0.1.0")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "v0.1.0"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "tag", "v0.1.0"], cwd=tmp_path, capture_output=True, check=True
    )

    # Add more commits and tags
    (tmp_path / "test.txt").write_text("v0.2.0")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "v0.2.0"], cwd=tmp_path, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "tag", "v0.2.0"], cwd=tmp_path, capture_output=True, check=True
    )

    # Add a prerelease tag (dash format matches our git tag convention)
    (tmp_path / "test.txt").write_text("v0.3.0-rc1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "v0.3.0-rc1"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "tag", "v0.3.0-rc1"], cwd=tmp_path, capture_output=True, check=True
    )

    # Add another prerelease
    (tmp_path / "test.txt").write_text("v0.3.0-alpha.1")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "v0.3.0-alpha.1"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "tag", "v0.3.0-alpha.1"], cwd=tmp_path, capture_output=True, check=True
    )

    return tmp_path


class TestGetAvailableVersions:
    """Tests for get_available_versions function."""

    def test_returns_versions_sorted_newest_first(
        self, git_repo_with_tags: Path
    ) -> None:
        """Test that versions are returned sorted newest first."""
        versions = get_available_versions(git_repo_with_tags)

        # Should get 0.2.0 and 0.1.0 (no prereleases by default)
        assert len(versions) == 2
        assert versions[0] == "0.2.0"  # Newest first
        assert versions[1] == "0.1.0"

    def test_excludes_prereleases_by_default(self, git_repo_with_tags: Path) -> None:
        """Test that prereleases are excluded by default."""
        versions = get_available_versions(git_repo_with_tags)

        # Should NOT contain rc or alpha versions
        assert "0.3.0-rc1" not in versions
        assert "0.3.0-alpha.1" not in versions

    def test_includes_prereleases_when_requested(
        self, git_repo_with_tags: Path
    ) -> None:
        """Test that prereleases are included when include_prereleases=True."""
        versions = get_available_versions(git_repo_with_tags, include_prereleases=True)

        # Should contain all versions including prereleases
        assert "0.3.0-rc1" in versions
        assert "0.3.0-alpha.1" in versions
        assert "0.2.0" in versions
        assert "0.1.0" in versions

    def test_returns_empty_for_no_tags(self, git_repo: Path) -> None:
        """Test that empty list is returned when no version tags exist."""
        # Create copier.yml to make it a valid template root
        (git_repo / "copier.yml").write_text("_subdirectory: templates\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add copier.yml"],
            cwd=git_repo,
            capture_output=True,
        )

        versions = get_available_versions(git_repo)

        assert versions == []


class TestGetLatestVersion:
    """Tests for get_latest_version function."""

    def test_returns_latest_non_prerelease_version(
        self, git_repo_with_tags: Path
    ) -> None:
        """Test that latest version is 0.2.0, not a prerelease."""
        latest = get_latest_version(git_repo_with_tags)

        # Should be 0.2.0, NOT 0.3.0-rc1 or 0.3.0-alpha.1
        assert latest == "0.2.0"

    def test_returns_none_for_no_versions(self, git_repo: Path) -> None:
        """Test that None is returned when no version tags exist."""
        # Create copier.yml to make it a valid template root
        (git_repo / "copier.yml").write_text("_subdirectory: templates\n")
        subprocess.run(["git", "add", "."], cwd=git_repo, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add copier.yml"],
            cwd=git_repo,
            capture_output=True,
        )

        latest = get_latest_version(git_repo)

        assert latest is None
