"""
Update command implementation.

Updates an existing Aegis Stack project to a newer template version using
Copier's git-aware update mechanism.
"""

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import typer

from .. import __version__ as aegis_version
from ..cli import brand
from ..config.defaults import GITHUB_TEMPLATE_URL
from ..constants import AnswerKeys, OllamaMode, StorageBackends
from ..core.behavior_changes import behavior_changes_for
from ..core.copier_manager import is_copier_project, load_copier_answers
from ..core.copier_updater import (
    analyze_conflict_files,
    cleanup_backup_tag,
    create_backup_point,
    format_conflict_report,
    get_changelog,
    get_current_template_commit,
    get_template_root,
    is_version_downgrade,
    resolve_ref_to_commit,
    resolve_ref_to_commit_remote,
    resolve_version_to_ref,
    rollback_to_backup,
    src_path_to_git_url,
    validate_clean_git_tree,
)
from ..core.manual_updater import detect_insights_sources
from ..core.migration_generator import generate_missing_migrations
from ..core.post_gen_tasks import cleanup_components, run_post_generation_tasks
from ..core.template_cleanup import (
    cleanup_nested_project_directory,
    env_value,
    removed_env_keys,
    stale_env_defaults,
    sync_template_changes,
)
from ..core.version_compatibility import get_cli_version, get_project_template_version
from ..i18n import lazy_t, t

# Which questions ``_detect_existing_features`` reads off the project. Named
# here so the guard in ``tests/core/test_answer_derivation_declared.py`` can
# tell a covered question from a forgotten one.
DETECTED: frozenset[str] = frozenset(
    {
        AnswerKeys.OLLAMA_MODE,
        AnswerKeys.INSIGHTS_GITHUB,
        AnswerKeys.INSIGHTS_PYPI,
        AnswerKeys.INSIGHTS_PLAUSIBLE,
        AnswerKeys.INSIGHTS_REDDIT,
    }
)

# Questions a project cannot answer from its own contents. Identity and
# provenance: the values ARE the answer, there is nothing on disk to read
# them back from, and every answers file has carried them since 0.1 — so no
# project can be missing one and no default can be silently substituted.
NOT_INFERABLE: dict[str, str] = {
    "project_name": "identity; asked once, never re-derived",
    "project_description": "identity; free text with no on-disk echo",
    "author_name": "identity",
    "author_email": "identity",
    "github_username": "identity",
    "version": "the project's own version, which it alone owns",
    "aegis_version": "provenance, written by the update itself",
    "python_version": "pyproject states a range, not the answered pin",
}

# Answerable from the project, but nobody has written the detector. A
# ratchet: entries exist so nothing gets worse, and each one is meant to be
# deleted the day its detector lands. The parenthetical names where the
# evidence lives, so the next person does not have to go looking.
INFERENCE_DEBT: dict[str, str] = {
    "database_engine": "DATABASE_URL scheme in .env",
    "postgres_provider": "DATABASE_URL host in .env",
    "worker_backend": "the worker entrypoint the compose file runs",
    "scheduler_backend": "SCHEDULER_* settings in .env",
    "ai_framework": "the chat engine package under app/services/ai",
    "ai_providers": "the *_API_KEY names present in .env",
    "ai_backend": "presence of the AI persistence models",
    "ai_rag": "app/services/rag",
    "ai_voice": "app/services/ai/domains/voice",
    "auth_level": "presence of the rbac / org models",
    "include_oauth": "app/components/backend/api/auth/oauth.py",
    "include_cache": "app/services/cache",
    "ingress_tls": "the TLS block in the ingress config",
    "ingress_domain": "the server name in the ingress config",
    "payment_provider": "the provider client under app/services/payment",
    "insights_per_user": "the per-user column on the insights models",
    "finance_plaid": "app/services/finance providers",
    "finance_snaptrade": "app/services/finance providers",
    "finance_import": "app/services/finance import surface",
}


def _detect_existing_features(target_path: Path) -> dict[str, Any]:
    """Reconstruct ``include_*`` and sub-feature flags from project structure.

    Older template versions didn't have today's full set of questions in
    ``copier.yml`` (e.g. ``include_insights`` was added after 0.6.10), so
    those flags are missing from older ``.copier-answers.yml`` files.
    During ``aegis update -y``, copier silently uses the template's
    ``default: false`` for any missing flag — which means a project that
    *clearly* has ``app/services/insights/`` on disk gets re-rendered as
    if it never had insights, deleting service files and breaking the
    project.

    To prevent that, we walk the project structure and re-derive a flag
    set from what's actually installed. The caller persists those inferred
    values into ``.copier-answers.yml`` BEFORE invoking copier update, so
    copier reads them as part of the project's stored answers instead of
    falling back to template defaults for newly-added questions. Writing
    them to the answers file (rather than passing via
    ``run_update(data=...)``) means every downstream step in the same
    update run — copier render, ``cleanup_components``,
    ``sync_template_changes``, ``run_post_generation_tasks`` — sees one
    consistent picture. Earlier iterations of this fix passed the flags
    only via ``data=`` and ``cleanup_components`` then re-read the stale
    answers and deleted service files anyway.
    """
    from ..core.components import COMPONENTS
    from ..core.services import SERVICES

    # Marker presence → include_<name>, derived from each spec's
    # ``marker_path`` (single source of truth — a new component/service with
    # a marker is detectable on update automatically). Only ever sets True:
    # an absent marker leaves the flag out so the caller's merge doesn't
    # clobber an existing answer.
    detected: dict[str, Any] = {}
    for spec in [*SERVICES.values(), *COMPONENTS.values()]:
        if spec.marker_path and (target_path / spec.marker_path).exists():
            detected[AnswerKeys.include_key(spec.name)] = True

    # Insights sub-flags come from the collector registration, so we
    # neither resurrect collectors the user never opted into nor tear
    # down ones they use.
    detected.update(detect_insights_sources(target_path) or {})

    # Not every question is a flag. ``ollama_mode`` is a three-valued string
    # whose answer the project states outright, in the URL it talks to.
    ollama_mode = _detect_ollama_mode(target_path)
    if ollama_mode is not None:
        detected[AnswerKeys.OLLAMA_MODE] = ollama_mode

    return detected


def _detect_ollama_mode(target_path: Path) -> str | None:
    """Which Ollama the project talks to, from the URL it actually uses.

    The template's own dichotomy: ``docker`` is the compose service, and any
    other reachable URL is an Ollama the project talks to over the network,
    which is ``host``. An unset variable means no Ollama, which is already
    the default — return None so nothing is written and no stored answer is
    clobbered.

    ``.env`` is what the app reads; ``.env.example`` is the template artifact
    it was seeded from, and only stands in when the real file is gone.
    """
    for name in (".env", ".env.example"):
        url = env_value(target_path / name, "OLLAMA_BASE_URL")
        if url is None:
            continue
        return OllamaMode.DOCKER if "//ollama:" in url else OllamaMode.HOST
    return None


def _get_template_changed_files(
    template_root: Path,
    from_ref: str,
    to_ref: str,
) -> set[str] | None:
    """Get project-relative paths of files that changed in the template between refs.

    Diffs the template repo between two refs and extracts paths under the
    ``{{ project_slug }}/`` directory, stripping the template prefix and
    ``.jinja`` suffix so they map to actual project file paths.

    Returns ``None`` on git failure (so the caller falls back to syncing
    everything) and an empty ``set`` when the diff succeeded but found no
    changed files.
    """
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            from_ref,
            to_ref,
            "--",
            "aegis/templates/copier-aegis-project/{{ project_slug }}/",
        ],
        cwd=template_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None

    prefix = "aegis/templates/copier-aegis-project/{{ project_slug }}/"
    changed: set[str] = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith(prefix):
            continue
        relative = line[len(prefix) :]
        # Strip .jinja suffix — rendered files don't have it
        if relative.endswith(".jinja"):
            relative = relative[:-6]
        if relative:
            changed.add(relative)
    return changed


def _template_version_for_ref(target_ref: str) -> str:
    """Map a git ref to the ``_template_version`` value stored in answers.

    A version tag (``v0.7.0-rc3``) is recorded without the leading ``v``
    (``0.7.0-rc3``), matching ``copier_manager``. Anything else — ``HEAD``,
    a commit hash, or a branch that merely starts with ``v`` like
    ``v-next`` — is kept verbatim, so only genuine version tags get the
    prefix stripped.
    """
    from packaging.version import parse

    if target_ref.startswith("v"):
        try:
            parse(target_ref[1:])
        except Exception:
            return target_ref
        return target_ref[1:]
    return target_ref


_PENDING_FILE = Path(".git") / "aegis-update-pending.json"


def _pending_path(project_path: Path) -> Path:
    # Inside .git so it is never committed, yet survives until the user
    # finishes; a tracked file would dirty the tree the finish step needs.
    return project_path / _PENDING_FILE


def _record_pending_update(
    project_path: Path, *, target_ref: str, template_root: Path, backup_tag: str | None
) -> None:
    """Remember a conflicted update so ``--finish`` can complete it (#1018).

    On conflicts the baseline advance and post-gen are skipped on purpose;
    this is what lets a later run pick them up instead of re-merging.
    """
    _pending_path(project_path).write_text(
        json.dumps(
            {
                "target_ref": target_ref,
                "template_root": str(template_root),
                "backup_tag": backup_tag,
            }
        )
    )


def _load_pending_update(project_path: Path) -> dict[str, Any] | None:
    path = _pending_path(project_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def _run_postgen(target_path: Path, answers: dict[str, Any]) -> bool:
    """Missing migrations + post-generation tasks. Returns overall success."""
    include_auth = answers.get(AnswerKeys.AUTH, False)
    include_ai = answers.get(AnswerKeys.AI, False)
    include_insights = answers.get(AnswerKeys.INSIGHTS, False)
    include_payment = answers.get(AnswerKeys.PAYMENT, False)
    include_blog = answers.get(AnswerKeys.BLOG, False)
    include_documents = answers.get(AnswerKeys.DOCUMENTS, False)
    ai_backend = answers.get(AnswerKeys.AI_BACKEND, StorageBackends.MEMORY)
    ai_needs_migrations = include_ai and ai_backend != StorageBackends.MEMORY
    include_migrations = (
        include_auth
        or ai_needs_migrations
        or include_insights
        or include_payment
        or include_blog
        or include_documents
    )

    # Migrations the project predates. A project generated before a
    # revision existed never receives it otherwise: ``add-service``
    # and ``ManualUpdater.add_service`` both call this, ``update``
    # did not, so a v0.10.1 auth project kept ``001 -> 003`` with
    # ``auth_tokens`` never written (#1024). Must run BEFORE the
    # ``alembic upgrade head`` inside post-gen, or the DB is
    # stamped past a revision that only lands afterwards.
    if include_migrations:
        for migration_path in generate_missing_migrations(target_path, answers):
            brand.success(
                f"   {t('add_service.generated_migration', name=migration_path.name)}"
            )

    typer.echo(t("update.running_postgen"))
    postgen_report: dict[str, bool] = {}
    tasks_success = run_post_generation_tasks(
        target_path,
        include_migrations=include_migrations,
        report=postgen_report,
        relock=True,
    )
    # A failed upgrade is non-fatal to generation but must not be
    # reported as a clean update: the deployed app is what crashes
    # (UndefinedColumnError on first request), not this command.
    if postgen_report.get("migrations_ok") is False:
        tasks_success = False
    return tasks_success


def _finish_update(target_path: Path, pending: dict[str, Any]) -> None:
    """Complete a conflicted update once the user has resolved it (#1018).

    Refuses while any conflict remains: advancing the baseline past
    unresolved markers would make the next update skip the very hunks the
    user has not merged yet.
    """
    conflicts = analyze_conflict_files(target_path)
    if conflicts:
        brand.error(t("update.finish_blocked", count=len(conflicts)))
        for conflict in conflicts:
            typer.echo(f"      - {conflict['original']}")
        raise typer.Exit(1)

    answers = load_copier_answers(target_path) or {}
    tasks_success = _run_postgen(target_path, answers)
    _advance_copier_tracking(
        target_path, pending["target_ref"], Path(pending["template_root"])
    )
    _pending_path(target_path).unlink(missing_ok=True)
    backup_tag = pending.get("backup_tag")
    if backup_tag and tasks_success:
        cleanup_backup_tag(target_path, backup_tag)

    typer.echo("")
    if tasks_success:
        brand.success(t("update.finish_done"))
    else:
        brand.warn(t("update.partial_success"))
        typer.echo(t("update.partial_detail"))
    typer.echo("")
    typer.echo(t("update.next_steps"))
    typer.echo(t("update.next_review"))
    typer.echo(t("update.next_test"))
    typer.echo(t("update.next_commit"))


def _advance_copier_tracking(
    project_path: Path, target_ref: str, template_root: Path
) -> None:
    """Stamp ``.copier-answers.yml`` with the version we just applied.

    Copier's native answer write-back is unreliable for these
    ``{{ project_slug }}``-wrapped projects (we run our own
    ``sync_template_changes`` instead of copier's git-apply), so after a
    clean update ``_commit`` / ``_template_version`` are left pointing at
    the OLD version. The next ``aegis update`` would then diff from that
    stale baseline and re-apply changes that are already present. This
    advances both keys, mirroring how ``copier_manager`` records them on
    ``init``, so a subsequent update is a correct no-op.
    """
    import yaml

    answers_file = project_path / AnswerKeys.ANSWERS_FILENAME
    if not answers_file.exists():
        return

    answers = yaml.safe_load(answers_file.read_text()) or {}

    # Resolve the commit the update actually applied. In a dev checkout the
    # template_root is a git repo and ``git rev-parse`` resolves the ref. In
    # production (pip/uvx) template_root is the installed package directory —
    # not a git repo — so the local resolve returns None and we fall back to
    # resolving the ref against the remote the update pulled from (the
    # ``_src_path`` copier cloned). Without this fallback ``_commit`` stays
    # frozen at the original generation commit while ``_template_version``
    # advances, so the NEXT update diffs from a stale baseline and can
    # resurface already-applied changes / spurious conflicts.
    target_commit = resolve_ref_to_commit(target_ref, template_root)
    if not target_commit:
        repo_url = src_path_to_git_url(answers.get("_src_path") or GITHUB_TEMPLATE_URL)
        target_commit = resolve_ref_to_commit_remote(target_ref, repo_url)
    if target_commit:
        answers["_commit"] = target_commit

    # Mirror copier_manager: a version tag ("v0.7.0-rc3") is stored
    # without the leading "v"; "HEAD", commit refs, and branches are
    # stored as-is. Only strip the "v" when the remainder is a real
    # version, so a branch like "v-next" isn't mangled into "-next".
    if target_ref:
        answers["_template_version"] = _template_version_for_ref(target_ref)

    answers_file.write_text(
        yaml.safe_dump(answers, default_flow_style=False, sort_keys=False)
    )


def update_command(
    to_version: str | None = typer.Option(
        None,
        "--to-version",
        help=lazy_t("update.help_opt_to_version"),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=lazy_t("update.help_opt_dry_run"),
    ),
    project_path: str = typer.Option(
        ".",
        "--project-path",
        "-p",
        help=lazy_t("common.help_project_path_full"),
    ),
    template_path: str | None = typer.Option(
        None,
        "--template-path",
        "-t",
        help=lazy_t("update.help_opt_template_path"),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help=lazy_t("common.help_yes"),
    ),
    finish: bool = typer.Option(
        False,
        "--finish",
        help=lazy_t("update.help_opt_finish"),
    ),
) -> None:
    """
    Update project to a newer template version.

    This command uses Copier's git-aware update mechanism to merge template
    changes into your project while preserving your customizations.

    Examples:

        - aegis update

        - aegis update --to-version 0.2.0

        - aegis update --dry-run

        - aegis update --project-path ../my-project

        - aegis update --template-path ~/workspace/aegis-stack

    Note: This command requires a clean git working tree.
    """

    typer.echo(t("update.title"))
    typer.echo("=" * 50)

    # Resolve project path
    target_path = Path(project_path).resolve()

    # Validate it's a Copier project
    if not is_copier_project(target_path):
        brand.error(t("update.not_copier", path=target_path), err=True)
        typer.echo(
            f"   {t('update.copier_only')}",
            err=True,
        )
        typer.echo(
            f"   {t('update.need_regen')}",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo(t("update.project", path=target_path))

    # A previous run stopped on conflicts. Finish it (explicitly, or
    # because the user simply ran `aegis update` again) instead of
    # re-merging the whole range from the stale baseline. The tree is
    # dirty by definition here, so this comes before the clean check.
    pending = _load_pending_update(target_path)
    if finish or pending:
        if not pending:
            brand.error(t("update.finish_nothing"))
            raise typer.Exit(1)
        typer.echo(t("update.finish_resuming", ref=pending["target_ref"]))
        _finish_update(target_path, pending)
        return

    # Check git status
    is_clean, git_message = validate_clean_git_tree(target_path)
    if not is_clean:
        brand.error(git_message, err=True)
        typer.echo(
            f"   {t('update.commit_or_stash')}",
            err=True,
        )
        typer.echo(f"   {t('update.clean_required')}", err=True)
        raise typer.Exit(1)

    brand.success(t("update.git_clean"))

    # Get current template version
    current_commit = get_current_template_commit(target_path)
    if not current_commit:
        brand.warn(t("update.unknown_version"))
        typer.echo(f"   {t('update.untagged_commit')}")

    current_version = get_project_template_version(target_path)
    cli_version = get_cli_version()

    # Get template root (with optional custom path)

    # Precedence: --template-path flag > AEGIS_TEMPLATE_PATH env var > default
    effective_template_path = template_path or os.getenv("AEGIS_TEMPLATE_PATH")

    try:
        template_root = get_template_root(effective_template_path)
    except ValueError as e:
        brand.error(str(e), err=True)
        raise typer.Exit(1)

    if effective_template_path:
        source = "flag" if template_path else "AEGIS_TEMPLATE_PATH"
        typer.echo(t("update.custom_template", source=source, path=template_root))

    # Resolve target version
    if to_version:
        target_ref = resolve_version_to_ref(to_version, template_root)
        target_version_display = to_version
    else:
        # Default to CLI version - templates should match the installed CLI
        target_ref = resolve_version_to_ref(cli_version, template_root)
        if target_ref:
            target_version_display = f"{cli_version} (current CLI)"
        else:
            # Fallback to HEAD if CLI version tag doesn't exist
            target_ref = "HEAD"
            head_commit = resolve_ref_to_commit("HEAD", template_root)
            if head_commit:
                target_version_display = f"HEAD ({head_commit[:8]}...)"
            else:
                target_version_display = "HEAD (latest commit)"

    # Display version information
    typer.echo("")
    typer.echo(t("update.version_info"))
    typer.echo(t("update.current_cli", version=cli_version))
    if current_version:
        typer.echo(t("update.current_template", version=current_version))
    elif current_commit:
        typer.echo(t("update.current_template_commit", commit=current_commit[:8]))
    else:
        typer.echo(t("update.current_template_unknown"))
    typer.echo(t("update.target_template", version=target_version_display))

    # Check if already up to date (version-based)
    if current_version and to_version and current_version == to_version:
        typer.echo("")
        brand.success(t("update.already_at_version"))
        return

    # Check if already at target commit (for HEAD/branch updates)
    if current_commit and target_ref:
        target_commit = resolve_ref_to_commit(target_ref, template_root)

        if target_commit and current_commit == target_commit:
            typer.echo("")
            brand.success(t("update.already_at_commit"))
            typer.echo(t("update.current_commit", commit=current_commit[:8]))
            typer.echo(t("update.target_commit", commit=target_commit[:8]))
            return

        # Check for downgrade attempt (not supported by Copier)
        if target_commit and is_version_downgrade(
            current_commit, target_commit, template_root
        ):
            # No --to-version means "match the installed CLI". A project
            # generated from a newer commit (a dev checkout ahead of the
            # release tag) is already up to date, not a failed downgrade.
            # Only an explicitly requested downgrade is an error.
            if not to_version:
                typer.echo("")
                brand.success(t("update.ahead_of_target"))
                typer.echo(t("update.current_commit", commit=current_commit[:8]))
                typer.echo(t("update.target_commit", commit=target_commit[:8]))
                typer.echo(f"   {t('update.ahead_of_target_hint')}")
                return

            typer.echo("")
            brand.error(t("update.downgrade_blocked"), err=True)
            typer.echo(t("update.current_commit", commit=current_commit[:8]), err=True)
            typer.echo(t("update.target_commit", commit=target_commit[:8]), err=True)
            typer.echo(
                f"   {t('update.downgrade_reason')}",
                err=True,
            )
            raise typer.Exit(1)

    # Get and display changelog
    if current_commit:
        typer.echo("")
        typer.echo(t("update.changelog"))
        typer.echo("-" * 50)
        changelog = get_changelog(current_commit, target_ref, template_root)
        typer.echo(changelog)
        typer.echo("-" * 50)

    # Dry run mode
    if dry_run:
        typer.echo("")
        brand.accent(t("update.dry_run"))
        typer.echo("")
        typer.echo(t("update.dry_run_hint"))
        if to_version:
            typer.echo(f"  aegis update --to-version {to_version}")
        else:
            typer.echo("  aegis update")
        return

    # Confirmation
    if not yes:
        typer.echo("")
        if not typer.confirm(t("update.confirm"), default=True):
            brand.error(t("update.cancelled"))
            raise typer.Exit(0)

    # Create backup point before update
    typer.echo("")
    typer.echo(t("update.creating_backup"))
    backup_tag = create_backup_point(target_path)
    if backup_tag:
        typer.echo(t("update.backup_created", tag=backup_tag))
    else:
        brand.warn(t("update.backup_failed"))

    # Perform update using Copier
    typer.echo("")
    typer.echo(t("update.updating"))

    try:
        # Import here to avoid circular dependency
        import yaml
        from copier import run_update

        # Prepare .copier-answers.yml for the update
        # If custom template path was provided, update _src_path
        # so Copier reads the template from the correct location.
        # This is necessary because Copier's git detection only works reliably
        # when reading _src_path from the answers file, not when passed as src_path.
        if effective_template_path:
            answers_file = target_path / AnswerKeys.ANSWERS_FILENAME
            if answers_file.exists():
                with open(answers_file) as f:
                    answers = yaml.safe_load(f) or {}

                # Update _src_path to point to custom template
                # Use git+file:// URL format so Copier recognizes it as git-tracked
                answers["_src_path"] = f"git+file://{template_root}"

                with open(answers_file, "w") as f:
                    yaml.safe_dump(
                        answers, f, default_flow_style=False, sort_keys=False
                    )

                # Commit the updated answers (Copier requires clean repo)
                try:
                    subprocess.run(
                        ["git", "add", AnswerKeys.ANSWERS_FILENAME],
                        cwd=target_path,
                        check=True,
                        capture_output=True,
                    )
                    subprocess.run(
                        [
                            "git",
                            "commit",
                            "-m",
                            "Update template path for aegis update",
                        ],
                        cwd=target_path,
                        check=True,
                        capture_output=True,
                    )
                except subprocess.CalledProcessError:
                    # If commit fails (e.g., no changes), that's OK
                    pass

        # Get the set of files that actually changed in the template between versions
        # so sync_template_changes() only touches those, not every project customization
        template_changed_files: set[str] | None = None
        if current_commit:
            template_changed_files = _get_template_changed_files(
                template_root,
                current_commit,
                target_ref,
            )

        # Persist feature flags inferred from project structure into the
        # answers file BEFORE copier runs. Older answers files are missing
        # questions that were added later (e.g. ``include_insights`` was
        # added after 0.6.10), and ``defaults=True`` would silently use the
        # template's ``default: false`` for those — wiping service files
        # the user is actively using. By writing the inferred flags into
        # ``.copier-answers.yml`` first, every downstream step (copier
        # render, cleanup_components, sync_template_changes,
        # post_generation_tasks) sees the correct state.
        # See ``_detect_existing_features`` for full reasoning + scope.
        detected_flags = _detect_existing_features(target_path)
        if detected_flags:
            answers_path = target_path / AnswerKeys.ANSWERS_FILENAME
            if answers_path.exists():
                with open(answers_path) as f:
                    current_answers = yaml.safe_load(f) or {}
                # setdefault: only fill in MISSING flags. Don't overwrite an
                # explicit ``False`` from a user who deliberately removed
                # a service.
                changed = False
                for flag, value in detected_flags.items():
                    if flag not in current_answers:
                        current_answers[flag] = value
                        changed = True
                if changed:
                    with open(answers_path, "w") as f:
                        yaml.safe_dump(
                            current_answers,
                            f,
                            default_flow_style=False,
                            sort_keys=False,
                        )
                    # Copier requires a clean git tree, so commit the
                    # backfill. If the commit fails (e.g. blocked by a
                    # pre-commit hook) the working tree is left dirty —
                    # which would cause copier to fail with a confusing
                    # error several steps later. Verify the tree is clean
                    # post-commit and abort with a clear message if not.
                    try:
                        subprocess.run(
                            ["git", "add", AnswerKeys.ANSWERS_FILENAME],
                            cwd=target_path,
                            check=True,
                            capture_output=True,
                        )
                        subprocess.run(
                            [
                                "git",
                                "commit",
                                "-m",
                                "Backfill missing copier flags from project structure",
                            ],
                            cwd=target_path,
                            check=True,
                            capture_output=True,
                        )
                    except subprocess.CalledProcessError as exc:
                        # ``git commit`` exits non-zero when there's
                        # nothing to commit too — that's harmless. Only
                        # abort if the answers file is actually dirty.
                        status = subprocess.run(
                            [
                                "git",
                                "status",
                                "--porcelain",
                                AnswerKeys.ANSWERS_FILENAME,
                            ],
                            cwd=target_path,
                            capture_output=True,
                            text=True,
                        )
                        if status.stdout.strip():
                            stderr = (
                                (exc.stderr or b"")
                                .decode("utf-8", errors="replace")
                                .strip()
                            )
                            brand.error(
                                "Failed to commit backfilled .copier-answers.yml; "
                                "aborting because copier requires a clean git tree.",
                                err=True,
                            )
                            if stderr:
                                typer.echo(stderr, err=True)
                            raise typer.Exit(1) from exc

        # Run Copier update with git-aware merge
        # NOTE: We do NOT pass src_path - Copier reads it from .copier-answers.yml
        # This is critical for Copier's git tracking detection to work correctly
        run_update(
            dst_path=str(target_path),
            data={"aegis_version": aegis_version},  # Update to current CLI version
            defaults=True,  # Use existing answers as defaults
            overwrite=True,  # Allow overwriting files
            conflict="rej",  # Create .rej files for conflicts
            unsafe=False,  # Disable _tasks (we run them ourselves)
            vcs_ref=target_ref,  # Use specified version
            quiet=True,  # Suppress copier's English output
        )
        typer.echo(t("update.updating_to", version=target_version_display))

        # Load answers for cleanup and post-generation tasks
        # (the answers file was already backfilled with detected flags
        # above, so it has every ``include_*`` value cleanup_components
        # needs to make correct decisions.)
        answers = load_copier_answers(target_path)

        # Clean up nested directory if Copier created one
        # This happens when new files are added between template versions
        # because the template uses {{ project_slug }}/ wrapper
        project_slug = answers.get("project_slug", "")

        if project_slug:
            moved_files = cleanup_nested_project_directory(target_path, project_slug)
            if moved_files:
                typer.echo(t("update.moved_files", count=len(moved_files)))

                # CRITICAL: Clean up files that shouldn't exist based on component selection
                # This mirrors what happens during 'aegis init' - the template includes all
                # files and cleanup_components removes those not selected in answers
                cleanup_components(target_path, answers)

        # Sync template changes using 3-way merge to preserve user customizations
        # Copier's git apply is non-functional for Aegis projects due to the
        # {{ project_slug }}/ wrapper causing path mismatches
        template_src = answers.get("_src_path", "gh:lbedner/aegis-stack")
        sync_result = sync_template_changes(
            target_path,
            answers,
            template_src,
            target_ref,
            template_changed_files=template_changed_files,
            old_commit=current_commit,
        )
        if sync_result.synced:
            typer.echo(t("update.synced_files", count=len(sync_result.synced)))
        if sync_result.conflicts:
            typer.echo(t("update.merge_conflicts", count=len(sync_result.conflicts)))
            for conflict_file in sync_result.conflicts:
                typer.echo(f"      - {conflict_file}")
        if sync_result.removed:
            typer.echo(t("update.removed_files", count=len(sync_result.removed)))
        if sync_result.stale:
            typer.echo(t("update.stale_files", count=len(sync_result.stale)))
            for stale_file in sync_result.stale:
                typer.echo(f"      - {stale_file}")
        if sync_result.shadowed:
            typer.echo(t("update.shadowed_files", count=len(sync_result.shadowed)))
            for shadowed_file in sync_result.shadowed:
                typer.echo(f"      - {shadowed_file}")
        if sync_result.answers_backfilled:
            typer.echo(
                t(
                    "update.answers_backfilled",
                    count=len(sync_result.answers_backfilled),
                )
            )
            for key in sync_result.answers_backfilled:
                typer.echo(f"      - {key}")

        # Run post-generation tasks — but skip when conflicts exist.
        # ``run_post_generation_tasks`` calls ``uv sync``, which will fail
        # if any conflicted file (e.g. ``pyproject.toml``) still has
        # ``<<<<<<<`` markers. That failure is expected, but it surfaces as
        # a hard ``DependencyInstallationError`` that bubbles up to the
        # outer ``except`` handler and triggers a rollback — wiping the
        # merged state we just produced. Skip post-gen on conflicts so the
        # user can resolve them without losing the merge.
        if sync_result.conflicts:
            typer.echo(t("update.skipping_postgen_conflicts"))
            # Conflicts mean the update isn't done — the user still has
            # ``<<<<<<<`` markers to resolve and ``uv sync`` to run.
            # Routing through ``tasks_success = False`` flips the result
            # banner to the yellow "partial success" branch AND keeps the
            # backup tag alive (gated on this flag below). The pending
            # record is what ``--finish`` completes later (#1018).
            tasks_success = False
            _record_pending_update(
                target_path,
                target_ref=target_ref,
                template_root=template_root,
                backup_tag=backup_tag,
            )
        else:
            tasks_success = _run_postgen(target_path, answers)

        # Update __aegis_version__ directly (Copier doesn't re-render unchanged files)
        init_file = target_path / "app" / "__init__.py"
        if init_file.exists():
            content = init_file.read_text()
            updated_content = re.sub(
                r'__aegis_version__\s*=\s*(["\'])[^"\']*\1',
                f'__aegis_version__ = "{aegis_version}"',
                content,
            )
            if updated_content != content:
                init_file.write_text(updated_content)
                typer.echo(t("update.version_updated", version=aegis_version))

        # Advance the copier tracking keys so a re-run is a no-op. Only on
        # a fully clean update — with conflicts outstanding the baseline
        # must stay put so re-running still re-applies the same diff once
        # the user resolves the markers.
        if not sync_result.conflicts:
            _advance_copier_tracking(target_path, target_ref, template_root)

        # Show update result
        typer.echo("")
        if tasks_success:
            brand.success(t("update.success"))
        else:
            brand.warn(t("update.partial_success"))
            typer.echo(t("update.partial_detail"))
        # What the operator needs to know before deploying (#1020, #1029).
        # Both facts are knowable now and invisible later: a removed .env
        # key surfaces as a boot crash-loop, a behavior flip as a support
        # ticket. Neither is derived from a diff - the keys are a set
        # difference against the updated Settings, the changes are declared
        # per version by whoever changed the behavior. Report only.
        stale_keys = removed_env_keys(target_path) + stale_env_defaults(
            target_path, answers
        )
        changes = behavior_changes_for(
            from_version=current_version or "",
            to_version=_template_version_for_ref(target_ref),
            answers=answers,
        )
        if stale_keys or changes:
            typer.echo("")
            brand.warn(t("update.notice_header"))
            for entry in stale_keys:
                if entry.replacement:
                    typer.echo(
                        t(
                            "update.notice_env_renamed",
                            name=entry.key,
                            replacement=entry.replacement,
                        )
                    )
                else:
                    typer.echo(t("update.notice_env_removed", name=entry.key))
            for change in changes:
                typer.echo(
                    t(
                        "update.notice_behavior",
                        since=change.since,
                        message=change.message,
                    )
                )
                if change.restore:
                    typer.echo(t("update.notice_restore", restore=change.restore))

        typer.echo("")
        typer.echo(t("update.next_steps"))
        typer.echo(t("update.next_review"))
        typer.echo(t("update.next_conflicts"))
        typer.echo(t("update.next_test"))
        typer.echo(t("update.next_commit"))
        if sync_result.conflicts:
            typer.echo(t("update.next_finish"))

        # Every file left for the user: .rej hunks AND inline markers, the
        # latter scanned from the written tree as a safety net (#1016).
        conflicts = analyze_conflict_files(target_path)
        if conflicts:
            typer.echo("")
            report = format_conflict_report(conflicts)
            brand.warn(report)

        # Cleanup backup tag on a fully clean update only. With
        # ``sync_result.conflicts`` outstanding, the user still has work
        # to do (resolve markers, re-run ``uv sync``). If their
        # resolution goes wrong, the backup tag is the only rollback
        # path — deleting it here would defeat the safety net.
        if backup_tag and tasks_success:
            cleanup_backup_tag(target_path, backup_tag)
        elif backup_tag and sync_result.conflicts:
            typer.echo("")
            typer.echo(f"   Backup tag preserved: {backup_tag}")

    except Exception as e:
        typer.echo("")
        brand.error(t("update.failed", error=e), err=True)

        # Offer rollback if backup exists
        if backup_tag:
            typer.echo("")
            if yes or typer.confirm(t("update.rollback_prompt"), default=True):
                success, message = rollback_to_backup(target_path, backup_tag)
                if success:
                    brand.success(message)
                    cleanup_backup_tag(target_path, backup_tag)
                else:
                    brand.error(message, err=True)
                    typer.echo(f"   {t('update.manual_rollback', tag=backup_tag)}")
            else:
                typer.echo(t("update.manual_rollback", tag=backup_tag))

        typer.echo("")
        typer.echo(t("update.troubleshooting"))
        typer.echo(t("update.troubleshoot_clean"))
        typer.echo(t("update.troubleshoot_version"))
        typer.echo(t("update.troubleshoot_docs"))
        raise typer.Exit(1)
