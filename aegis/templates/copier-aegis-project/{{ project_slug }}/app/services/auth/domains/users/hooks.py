"""Extension points for the auth service.

Hooks let downstream applications inject behavior into the UserService
flow without subclassing or monkey-patching. Today there's one hook:
``post_user_created``, which fires when a brand-new ``User`` row is
inserted by either the password-signup path or an OAuth signup that
creates a fresh local user.

How to subscribe
----------------
At app startup (e.g. in your integrations module or a startup hook),
register a coroutine::

    from app.services.auth.service import register_post_user_created

    async def ensure_default_workspace(db, user):
        ...  # stage rows on db; do NOT commit

    register_post_user_created(ensure_default_workspace)

Contract
--------
* Hooks run **inside** the UserService's open transaction. Stage rows
  on the provided session and let the caller commit. Calling
  ``db.commit()`` from a hook breaks the surrounding atomicity.
* Hooks fire in registration order. A hook that raises aborts the
  transaction (the new user is not persisted).
* Idempotency is the hook's responsibility: a hook may be called for
  the same user more than once if a downstream app wires it into more
  than one new-user moment.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.user import User

PostUserCreatedHook = Callable[[AsyncSession, User], Awaitable[None]]

_post_user_created_hooks: list[PostUserCreatedHook] = []


def register_post_user_created(hook: PostUserCreatedHook) -> None:
    """Register a coroutine to run after a new ``User`` row is inserted.

    Fires on the password-signup path (``UserService.create_user``) and
    on the OAuth-signup path (``UserService.upsert_from_oauth`` when it
    inserts a new local user). Does NOT fire when an existing user
    signs in via OAuth or links an additional identity.
    """
    _post_user_created_hooks.append(hook)


async def run_post_user_created(db: AsyncSession, user: User) -> None:
    """Fire all registered hooks in order. UserService calls this — you
    typically don't.

    The user is already flushed (``user.id`` is populated) but not yet
    committed. Hooks stage rows on ``db``; the caller commits.
    """
    for hook in _post_user_created_hooks:
        await hook(db, user)


def _reset_hooks_for_tests() -> None:
    """Drop every registered hook. Test-only — production code should
    never need this.
    """
    _post_user_created_hooks.clear()
