"""
Experimental Copier-based updater using git-aware template at repo root.

This module provides an alternative to the manual updater by using Copier's
native update mechanism with a copier.yml at the repository root.
"""

import logging
import subprocess
from pathlib import Path

from copier import run_update
from packaging.version import parse
from pydantic import BaseModel, Field

from aegis.config.defaults import GITHUB_REPO_URL, version_to_git_tag
from aegis.constants import AnswerKeys, ComponentNames, StorageBackends
from aegis.core.copier_manager import load_copier_answers
from aegis.core.post_gen_tasks import cleanup_components, run_post_generation_tasks
from aegis.core.template_cleanup import cleanup_nested_project_directory
from aegis.i18n import t

logger = logging.getLogger(__name__)


class CopierUpdateResult(BaseModel):
    """Result of a Copier update operation."""

    success: bool = Field(description="Whether the operation succeeded")
    method: str = Field(default="copier-native", description="Update method used")
    error_message: str | None = Field(
        default=None, description="Error message if operation failed"
    )
    files_modified: list[str] = Field(
        default_factory=list, description="Files that were modified"
    )


def get_template_root(override_path: str | None = None) -> Path:
    """
    Get path to aegis-stack repository root (where copier.yml lives).

    Args:
        override_path: Optional custom template path to use instead of default

    Returns:
        Path to aegis-stack root directory

    Raises:
        ValueError: If override_path is invalid or missing required structure
    """
    if override_path:
        template_path = Path(override_path).expanduser().resolve()

        # Validate path exists
        if not template_path.exists():
            raise ValueError(f"Template path does not exist: {template_path}")

        # Validate it's a directory
        if not template_path.is_dir():
            raise ValueError(f"Template path is not a directory: {template_path}")

        # Validate it has copier.yml
        if not (template_path / "copier.yml").exists():
            raise ValueError(f"Invalid template: missing copier.yml at {template_path}")

        # Validate it's a git repository
        if not (template_path / ".git").exists():
            raise ValueError(f"Template path must be a git repository: {template_path}")

        return template_path

    # Default: This file is at: aegis-stack/aegis/core/copier_updater.py
    # We want: aegis-stack/ (2 levels up)
    return Path(__file__).parents[2]


def update_with_copier_native(
    project_path: Path,
    components_to_add: list[str],
    scheduler_backend: str = StorageBackends.MEMORY,
) -> CopierUpdateResult:
    """
    EXPERIMENTAL: Use Copier's native update with git root template.

    This approach uses the copier.yml at aegis-stack repo root which
    includes _subdirectory setting. This allows Copier to recognize the
    template as git-tracked and use proper merge conflict handling.

    Args:
        project_path: Path to the existing project directory
        components_to_add: List of component names to add
        scheduler_backend: Backend to use for scheduler ("memory" or "sqlite")

    Returns:
        CopierUpdateResult with success status

    Note:
        This is experimental. Falls back to manual updater if it fails.
    """
    try:
        # Get template root (aegis-stack/, not aegis/templates/...)
        template_root = get_template_root()

        # Build update data for Copier
        update_data: dict[str, bool | str] = {}

        for component in components_to_add:
            include_key = AnswerKeys.include_key(component)
            update_data[include_key] = True

        # Add scheduler backend configuration if adding scheduler
        if ComponentNames.SCHEDULER in components_to_add:
            update_data[AnswerKeys.SCHEDULER_BACKEND] = scheduler_backend
            update_data[AnswerKeys.SCHEDULER_WITH_PERSISTENCE] = (
                scheduler_backend == StorageBackends.SQLITE
            )

        # CRITICAL: Manually update .copier-answers.yml BEFORE running copier update
        # The `data` parameter in run_update() doesn't actually update existing answers
        # We must edit the file directly, then Copier detects the change and regenerates
        answers = load_copier_answers(project_path)
        answers.update(update_data)
        # Point _src_path to the template root (copier 9.14+ reads src from answers)
        answers["_src_path"] = f"git+file://{template_root}"

        # Save updated answers
        import yaml

        answers_file = project_path / AnswerKeys.ANSWERS_FILENAME
        with open(answers_file, "w") as f:
            yaml.safe_dump(answers, f, default_flow_style=False, sort_keys=False)

        # Commit the updated answers (Copier requires clean repo)
        import subprocess

        try:
            subprocess.run(
                ["git", "add", AnswerKeys.ANSWERS_FILENAME],
                cwd=project_path,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    f"Enable components: {', '.join(components_to_add)}",
                ],
                cwd=project_path,
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to commit .copier-answers.yml changes: {e}")

        # Run Copier update
        # Copier will detect the changed answers and regenerate files accordingly
        # Copier will:
        # 1. Use repo root as template (where .git exists)
        # 2. _subdirectory setting in copier.yml points to actual template content
        # 3. Detect template is git-tracked (finds .git at aegis-stack/)
        # 4. Detect changed answers in .copier-answers.yml (we just committed them)
        # 5. Use git diff to merge changes
        # 6. Handle conflicts with .rej files or inline markers
        # NOTE: _tasks removed from copier.yml - we run them ourselves below
        # copier 9.14+ reads _src_path from .copier-answers.yml (set above)
        run_update(
            dst_path=str(project_path),
            defaults=True,  # Use existing answers as defaults
            overwrite=True,  # Allow overwriting files
            conflict="rej",  # Create .rej files for conflicts
            unsafe=False,  # No tasks in copier.yml anymore - we run them ourselves
            vcs_ref="HEAD",  # Use latest template version
        )

        # Load answers for cleanup and post-generation tasks
        answers = load_copier_answers(project_path)

        # Clean up nested directory if Copier created one
        # This happens when new files are added between template versions
        # because the template uses {{ project_slug }}/ wrapper
        project_slug = answers.get("project_slug", "")

        if project_slug:
            moved_files = cleanup_nested_project_directory(project_path, project_slug)
            if moved_files:
                # CRITICAL: Clean up files that shouldn't exist based on component selection
                # This mirrors what happens during 'aegis init' - the template includes all
                # files and cleanup_components removes those not selected in answers
                cleanup_components(project_path, answers)

        # CRITICAL: Copy service-specific files for newly-added services
        # Copier can only re-render existing files - it cannot copy new directories
        # that were excluded during initial generation

        # Check for services in components_to_add (they start with 'include_')
        # Service names with service-specific template directories. Derived
        # from the service registry so a new service is picked up automatically
        # (no second list to keep in sync).
        from aegis.core.services import SERVICES

        service_names = set(SERVICES)
        newly_added_services = [
            svc for svc in service_names if AnswerKeys.include_key(svc) in update_data
        ]

        if newly_added_services:
            from aegis.core.post_gen_tasks import copy_service_files

            # Template content is at: template_root/aegis/templates/copier-aegis-project/
            template_path = (
                template_root / "aegis" / "templates" / "copier-aegis-project"
            )

            for service_name in newly_added_services:
                copy_service_files(project_path, service_name, template_path)

        # Run post-generation tasks with explicit working directory control
        # This ensures consistent behavior with initial generation
        include_auth = answers.get(AnswerKeys.AUTH, False)
        include_ai = answers.get(AnswerKeys.AI, False)
        include_insights = answers.get(AnswerKeys.INSIGHTS, False)
        include_payment = answers.get(AnswerKeys.PAYMENT, False)
        include_blog = answers.get(AnswerKeys.BLOG, False)
        include_documents = answers.get(AnswerKeys.DOCUMENTS, False)
        include_scheduler = answers.get(AnswerKeys.SCHEDULER, False)
        ai_backend = answers.get(AnswerKeys.AI_BACKEND, StorageBackends.MEMORY)
        scheduler_backend = answers.get(
            AnswerKeys.SCHEDULER_BACKEND, StorageBackends.MEMORY
        )
        ai_needs_migrations = include_ai and ai_backend != StorageBackends.MEMORY
        scheduler_needs_migrations = (
            include_scheduler and scheduler_backend == StorageBackends.POSTGRES
        )
        include_migrations = (
            include_auth
            or ai_needs_migrations
            or include_insights
            or include_payment
            or include_blog
            or include_documents
            or scheduler_needs_migrations
        )
        # AI needs seeding when using persistence backend (same condition as migrations)
        ai_needs_seeding = ai_needs_migrations

        # Run shared post-generation tasks
        run_post_generation_tasks(
            project_path,
            include_migrations=include_migrations,
            seed_ai=ai_needs_seeding,
        )

        return CopierUpdateResult(
            success=True,
            method="copier-native",
            files_modified=[],  # Copier doesn't provide this info easily
        )

    except Exception as e:
        return CopierUpdateResult(
            success=False, method="copier-native", error_message=str(e)
        )


# Version Management Functions


def get_current_template_commit(project_path: Path) -> str | None:
    """
    Get the git commit hash of the template used to generate the project.

    Args:
        project_path: Path to the project directory

    Returns:
        Commit hash string or None if not found
    """
    try:
        answers = load_copier_answers(project_path)
        commit_hash = answers.get("_commit")
        if commit_hash and commit_hash != "None":
            return commit_hash
        return None
    except Exception:
        return None


def _get_versions_from_github(include_prereleases: bool = False) -> list[str]:
    """
    Fetch available versions from GitHub API when not in a git repo.

    Used when running from installed package (pip/uvx) instead of git checkout.

    Args:
        include_prereleases: Include pre-release versions (rc, alpha, beta, dev)

    Returns:
        List of version strings sorted by PEP 440 (newest first)
    """
    import json
    import urllib.request
    from urllib.parse import urlparse

    github_url = GITHUB_REPO_URL

    # Extract owner/repo from GITHUB_REPO_URL (e.g., "lbedner/aegis-stack")
    parsed = urlparse(github_url)
    repo_path = parsed.path.strip("/")  # "lbedner/aegis-stack"

    api_url = f"https://api.github.com/repos/{repo_path}/tags?per_page=100"

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "aegis-stack-cli",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        # Parse tags from API response
        versions = []
        for tag_info in data:
            tag_name = tag_info.get("name", "")
            if tag_name.startswith("v"):
                version_str = tag_name[1:]  # Remove 'v' prefix
                try:
                    parsed_ver = parse(version_str)
                    if not include_prereleases and parsed_ver.is_prerelease:
                        continue
                    versions.append(version_str)
                except Exception:
                    continue

        # Sort by PEP 440 (newest first)
        versions.sort(key=parse, reverse=True)
        return versions

    except Exception:
        return []


def get_available_versions(
    template_root: Path | None = None, include_prereleases: bool = False
) -> list[str]:
    """
    Get list of available template versions from git tags.

    Falls back to GitHub API when not in a git repository (installed package mode).

    Args:
        template_root: Path to template repository (default: auto-detect)
        include_prereleases: Include pre-release versions (rc, alpha, beta, dev)

    Returns:
        List of version strings sorted by PEP 440 (newest first)
    """
    if template_root is None:
        template_root = get_template_root()

    # Check if we're in a git repository
    if not (template_root / ".git").exists():
        # Fall back to GitHub API (installed package mode)
        return _get_versions_from_github(include_prereleases)

    try:
        result = subprocess.run(
            ["git", "tag", "--list", "v*"],
            cwd=template_root,
            capture_output=True,
            text=True,
            check=True,
        )

        # Parse tags (remove 'v' prefix and filter valid versions)
        versions = []
        for tag in result.stdout.strip().split("\n"):
            if tag.startswith("v"):
                version_str = tag[1:]  # Remove 'v' prefix
                try:
                    parsed_ver = parse(version_str)  # Validate version
                    # Skip pre-releases (rc, alpha, beta, dev) unless explicitly requested
                    if not include_prereleases and parsed_ver.is_prerelease:
                        continue
                    versions.append(version_str)
                except Exception:
                    continue

        # Sort by PEP 440 (newest first)
        versions.sort(key=parse, reverse=True)
        return versions

    except Exception:
        # Fall back to GitHub API on any git error
        return _get_versions_from_github(include_prereleases)


def get_latest_version(template_root: Path | None = None) -> str | None:
    """
    Get the latest template version from git tags.

    Args:
        template_root: Path to template repository (default: auto-detect)

    Returns:
        Latest version string or None if no versions found
    """
    versions = get_available_versions(template_root)
    return versions[0] if versions else None


def resolve_ref_to_commit(ref: str, repo_path: Path) -> str | None:
    """
    Resolve a git reference (HEAD, branch, tag, commit) to full commit SHA.

    Args:
        ref: Git reference (HEAD, branch name, tag, or commit hash)
        repo_path: Path to git repository

    Returns:
        Full commit SHA or None if resolution fails
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", ref],
            cwd=repo_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def src_path_to_git_url(src_path: str) -> str:
    """Translate a copier ``_src_path`` into a URL ``git`` can clone.

    Copier accepts shorthands like ``gh:owner/repo`` and a ``git+`` VCS
    prefix that ``git ls-remote`` doesn't understand. Expand the common
    shorthands and strip the prefix; pass anything already URL-shaped
    through unchanged.
    """
    if src_path.startswith("gh:"):
        return f"https://github.com/{src_path[3:]}"
    if src_path.startswith("gl:"):
        return f"https://gitlab.com/{src_path[3:]}"
    if src_path.startswith("git+"):
        return src_path[4:]
    return src_path


def resolve_ref_to_commit_remote(ref: str, repo_url: str) -> str | None:
    """Resolve a git ref to a commit SHA against a remote repository.

    The production (pip/uvx) fallback for ``resolve_ref_to_commit``: when
    the template root is the installed package directory rather than a git
    checkout, ``git rev-parse`` can't resolve the ref locally. Query the
    remote the update pulled from with ``git ls-remote`` instead.

    Returns the dereferenced commit SHA — the peeled ``^{}`` value for
    annotated tags, matching ``git rev-parse`` semantics so the stamped
    ``_commit`` is the same SHA a dev-checkout update would record — or
    None if the ref can't be resolved.

    Args:
        ref: Git reference (tag, branch, ``HEAD``, or a full commit SHA)
        repo_url: Clonable URL of the template remote

    Returns:
        Full commit SHA or None on failure
    """
    # A full commit SHA is already resolved; ls-remote can't match a bare
    # commit (it matches refs), so return it verbatim.
    if len(ref) == 40 and all(c in "0123456789abcdef" for c in ref.lower()):
        return ref

    try:
        result = subprocess.run(
            ["git", "ls-remote", repo_url, ref],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    # Parse "<sha>\t<refname>" lines. Prefer the peeled commit ("^{}") that
    # annotated tags emit; fall back to the first plain ref line otherwise
    # (lightweight tags, branches, HEAD).
    plain: str | None = None
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        sha, refname = parts
        if refname.endswith("^{}"):
            return sha
        if plain is None:
            plain = sha
    return plain


def resolve_version_to_ref(
    version: str | None, template_root: Path | None = None
) -> str:
    """
    Resolve a version string to a git reference.

    Args:
        version: Version string ("latest", "0.2.0", commit hash, or None)
        template_root: Path to template repository (default: auto-detect)

    Returns:
        Git reference string (tag name, commit hash, or "HEAD")
    """
    if template_root is None:
        template_root = get_template_root()

    # None or "latest" -> use latest version tag
    if not version or version == "latest":
        latest = get_latest_version(template_root)
        if latest:
            return version_to_git_tag(latest)
        return "HEAD"

    # Check if it's a commit hash (40 hex characters)
    if len(version) == 40 and all(c in "0123456789abcdef" for c in version.lower()):
        return version

    # Check if it looks like a version number (add 'v' prefix)
    try:
        parse(version)
        # Valid version number - convert to git tag format
        # PEP 440 "0.6.0rc1" → git tag "v0.6.0-rc1"
        return version_to_git_tag(version)
    except Exception:
        pass

    # Fall back to using the version string as-is (might be a branch name)
    return version


def is_version_downgrade(
    current_commit: str, target_commit: str, template_root: Path
) -> bool:
    """
    Check if target commit is older than current commit (downgrade).

    Args:
        current_commit: Current template commit hash
        target_commit: Target template commit hash
        template_root: Path to template repository

    Returns:
        True if target is older than current (downgrade), False otherwise
    """
    try:
        # Use git merge-base to check if target is ancestor of current
        # If target IS an ancestor of current, it means target is older (downgrade)
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", target_commit, current_commit],
            cwd=template_root,
            capture_output=True,
            check=False,
        )
        # Exit code 0 means target IS ancestor (downgrade)
        # Exit code 1 means target is NOT ancestor (upgrade or unrelated)
        return result.returncode == 0
    except Exception:
        # If we can't determine, assume it's not a downgrade (safe default)
        return False


def validate_clean_git_tree(project_path: Path) -> tuple[bool, str]:
    """
    Check if the project's git working tree is clean.

    Args:
        project_path: Path to project directory

    Returns:
        Tuple of (is_clean: bool, message: str)
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        )

        if result.stdout.strip():
            return False, t("update.dirty_tree")

        return True, t("update.git_clean")

    except subprocess.CalledProcessError as e:
        return False, f"Failed to check git status: {e}"
    except Exception as e:
        return False, f"Error checking git status: {e}"


def _format_commits_as_changelog(
    commits: list[tuple[str, str]], github_url: str
) -> str:
    """
    Format a list of (hash, message) commits as a categorized changelog.

    Args:
        commits: List of (commit_hash, message) tuples
        github_url: Base GitHub URL for commit links

    Returns:
        Formatted changelog string
    """
    if not commits:
        return "No changes"

    features: list[tuple[str, str]] = []
    fixes: list[tuple[str, str]] = []
    breaking: list[tuple[str, str]] = []
    other: list[tuple[str, str]] = []

    for commit_hash, message in commits:
        message_lower = message.lower()
        if "breaking:" in message_lower or "breaking change" in message_lower:
            breaking.append((commit_hash, message))
        elif message.startswith("feat:") or message.startswith("feature:"):
            features.append((commit_hash, message))
        elif message.startswith("fix:"):
            fixes.append((commit_hash, message))
        else:
            other.append((commit_hash, message))

    def format_commit(commit_hash: str, message: str) -> str:
        """Format commit with GitHub link."""
        if commit_hash:
            return f"  • {message} ([{commit_hash}]({github_url}/commit/{commit_hash}))"
        return f"  • {message}"

    lines = []

    if breaking:
        lines.append(t("update.changelog_breaking"))
        for commit_hash, message in breaking:
            lines.append(format_commit(commit_hash, message))
        lines.append("")

    if features:
        lines.append(t("update.changelog_features"))
        for commit_hash, message in features:
            lines.append(format_commit(commit_hash, message))
        lines.append("")

    if fixes:
        lines.append(t("update.changelog_fixes"))
        for commit_hash, message in fixes:
            lines.append(format_commit(commit_hash, message))
        lines.append("")

    if other:
        lines.append(t("update.changelog_other"))
        for commit_hash, message in other:
            lines.append(format_commit(commit_hash, message))

    return "\n".join(lines).strip()


def _get_changelog_from_github(from_ref: str, to_ref: str) -> str:
    """
    Fetch changelog from GitHub Compare API when not in a git repo.

    Used when running from installed package (pip/uvx) instead of git checkout.

    Args:
        from_ref: Starting git reference (commit hash)
        to_ref: Ending git reference (commit, tag, or "HEAD")

    Returns:
        Formatted changelog string or error message with fallback link
    """
    import json
    import urllib.request
    from urllib.parse import urlparse

    github_url = GITHUB_REPO_URL

    # Extract owner/repo from GITHUB_REPO_URL (e.g., "lbedner/aegis-stack")
    parsed = urlparse(github_url)
    repo_path = parsed.path.strip("/")  # "lbedner/aegis-stack"

    # Normalize refs (HEAD -> main for API)
    base = from_ref
    head = "main" if to_ref == "HEAD" else to_ref

    api_url = f"https://api.github.com/repos/{repo_path}/compare/{base}...{head}"

    try:
        req = urllib.request.Request(
            api_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "aegis-stack-cli",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())

        api_commits = data.get("commits", [])
        if not api_commits:
            return "No changes"

        # Extract (hash, message) tuples from API response
        commits = [
            (c["sha"][:7], c["commit"]["message"].split("\n")[0]) for c in api_commits
        ]

        return _format_commits_as_changelog(commits, github_url)

    except Exception as e:
        # Fallback to compare link
        return (
            f"Changelog not available: {e}\n"
            f"View changes: {github_url}/compare/{from_ref}...main"
        )


def get_changelog(from_ref: str, to_ref: str, template_root: Path | None = None) -> str:
    """
    Get changelog between two git references.

    Args:
        from_ref: Starting git reference (commit, tag, or branch)
        to_ref: Ending git reference
        template_root: Path to template repository (default: auto-detect)

    Returns:
        Formatted changelog string
    """
    if template_root is None:
        template_root = get_template_root()

    # Check if we're in a git repository (not installed package mode)
    if not (template_root / ".git").exists():
        return _get_changelog_from_github(from_ref, to_ref)

    try:
        # Get commit log between refs (hash|message format for GitHub links)
        result = subprocess.run(
            [
                "git",
                "log",
                "--oneline",
                "--no-merges",
                "--pretty=format:%h|%s",
                f"{from_ref}..{to_ref}",
            ],
            cwd=template_root,
            capture_output=True,
            text=True,
            check=True,
        )

        if not result.stdout.strip():
            return "No changes"

        # Parse commits from git output
        raw_commits = result.stdout.strip().split("\n")
        commits = []
        for line in raw_commits:
            if "|" in line:
                commit_hash, message = line.split("|", 1)
            else:
                commit_hash, message = "", line
            commits.append((commit_hash, message))

        return _format_commits_as_changelog(commits, GITHUB_REPO_URL)

    except Exception as e:
        return f"Error generating changelog: {e}"


def create_backup_point(project_path: Path) -> str | None:
    """
    Create a backup point before update by tagging current HEAD.

    Args:
        project_path: Path to project directory

    Returns:
        Backup tag name or None if creation failed
    """
    import time

    backup_tag = f"aegis-backup-{int(time.time())}"

    try:
        # Create lightweight tag at current HEAD
        subprocess.run(
            ["git", "tag", backup_tag],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        )
        return backup_tag
    except subprocess.CalledProcessError:
        return None


def rollback_to_backup(project_path: Path, backup_tag: str) -> tuple[bool, str]:
    """
    Rollback project to backup point.

    Args:
        project_path: Path to project directory
        backup_tag: Tag name to rollback to

    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Hard reset to backup tag
        subprocess.run(
            ["git", "reset", "--hard", backup_tag],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=True,
        )

        # Clean untracked files that may have been added
        subprocess.run(
            ["git", "clean", "-fd"],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=False,  # Don't fail if clean has issues
        )

        return True, f"Successfully rolled back to {backup_tag}"
    except subprocess.CalledProcessError as e:
        return False, f"Rollback failed: {e}"


def cleanup_backup_tag(project_path: Path, backup_tag: str) -> None:
    """
    Remove backup tag after successful update.

    Args:
        project_path: Path to project directory
        backup_tag: Tag name to remove
    """
    import contextlib

    with contextlib.suppress(Exception):
        subprocess.run(
            ["git", "tag", "-d", backup_tag],
            cwd=project_path,
            capture_output=True,
            text=True,
            check=False,  # Don't fail if tag doesn't exist
        )


def get_commit_for_version(
    version: str, template_root: Path | None = None
) -> str | None:
    """
    Get the git commit hash for a version tag.

    Args:
        version: Version string (with or without 'v' prefix)
        template_root: Path to template repository (default: auto-detect)

    Returns:
        Commit hash or None if tag not found
    """
    if template_root is None:
        template_root = get_template_root()

    # Ensure version has 'v' prefix
    tag_name = version if version.startswith("v") else version_to_git_tag(version)

    try:
        result = subprocess.run(
            ["git", "rev-list", "-n", "1", tag_name],
            cwd=template_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:
        return None


def analyze_conflict_files(project_path: Path) -> list[dict[str, str]]:
    """
    Analyze .rej files created by Copier during conflict resolution.

    Args:
        project_path: Path to project directory

    Returns:
        List of conflict info dicts with keys: path, original, size, summary
    """
    conflicts = []

    # Find all .rej files
    rej_files = list(project_path.rglob("*.rej"))

    for rej_file in rej_files:
        # Get the original file path
        original_path = rej_file.with_suffix("")
        relative_path = rej_file.relative_to(project_path)
        relative_original = original_path.relative_to(project_path)

        # Read the .rej file content to get a summary
        try:
            rej_content = rej_file.read_text()
            line_count = len(rej_content.strip().split("\n"))
            summary = f"{line_count} lines in conflict file"
        except Exception as e:
            logger.debug(f"Failed to read .rej file {rej_file}: {e}")
            summary = "Unable to read conflict details"

        conflicts.append(
            {
                "path": str(relative_path),
                "original": str(relative_original),
                "size": f"{rej_file.stat().st_size} bytes",
                "summary": summary,
            }
        )

    return conflicts


def format_conflict_report(conflicts: list[dict[str, str]]) -> str:
    """
    Format a detailed conflict report for display.

    Args:
        conflicts: List of conflict info dicts from analyze_conflict_files

    Returns:
        Formatted string report
    """
    if not conflicts:
        return ""

    lines = []
    lines.append("Conflicts detected - manual resolution required")
    lines.append("")

    for conflict in conflicts:
        lines.append(f"  {conflict['original']}")
        lines.append(f"     Rejected changes: {conflict['path']}")
        lines.append(f"     Details: {conflict['summary']}")
        lines.append("")

    lines.append("Resolution steps:")
    lines.append("   1. Open the .rej file to see rejected changes")
    lines.append("   2. Manually apply changes to the original file")
    lines.append("   3. Delete the .rej file when resolved")
    lines.append("")
    lines.append("Tip: Use 'git diff' to see all changes made by the update")

    return "\n".join(lines)
