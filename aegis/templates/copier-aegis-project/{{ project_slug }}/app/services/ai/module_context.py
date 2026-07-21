"""Memory-module context assembly: priority order, token budget, hybrid.

Turns an agent's ``memory_modules`` list into one labeled context block.
Each module renders its static ``prompt_content`` first, then its
``fetch_function`` output (live per-user data). Modules render in
priority order (lower number first); when a token budget is given,
higher-priority modules claim it first and any module that does not fit
the remaining budget is dropped - deterministic and logged.

``MemoryModuleContextProvider`` adapts this into the chat_kit
``ContextProvider`` protocol; ``build_chat_agent`` wires it in
automatically when the agent config lists modules, so an agent with no
modules produces context byte-identical to a module-less runtime.
"""

from collections.abc import Sequence
from dataclasses import dataclass

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db import get_async_session
from app.core.log import logger
from app.services.ai.fetchers import FetchContext, run_fetcher
from app.services.ai.models.agents import MemoryModule

# Rough chars-per-token heuristic for modules without an explicit
# token_estimate. Deliberately conservative and cheap; authors who care
# set token_estimate on the row.
_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class _RenderedModule:
    context_key: str
    priority: int
    content: str
    tokens: int


def _estimate_tokens(module: MemoryModule, content: str) -> int:
    if module.token_estimate > 0:
        return module.token_estimate
    return max(1, len(content) // _CHARS_PER_TOKEN)


async def _load_modules(
    session: AsyncSession, slugs: Sequence[str]
) -> list[MemoryModule]:
    result = await session.exec(
        select(MemoryModule).where(MemoryModule.slug.in_(slugs))  # type: ignore[attr-defined]
    )
    modules = {module.slug: module for module in result.all()}
    missing = [slug for slug in slugs if slug not in modules]
    if missing:
        logger.warning(
            "Agent references unknown memory modules; skipping",
            module_slugs=missing,
        )
    active = [m for m in modules.values() if m.is_active]
    return sorted(active, key=lambda m: (m.priority, m.slug))


async def _render_module(
    module: MemoryModule, user_id: str, session: AsyncSession | None
) -> str | None:
    """Static block first, then the live fetcher data."""
    parts: list[str] = []
    if module.prompt_content:
        parts.append(module.prompt_content.strip())
    if module.fetch_function:
        dynamic = await run_fetcher(
            module.fetch_function,
            FetchContext(
                user_id=user_id,
                days_back=(
                    module.default_days_back if module.supports_days_back else None
                ),
                session=session,
            ),
        )
        if dynamic:
            parts.append(dynamic.strip())
    if not parts:
        return None
    return "\n\n".join(parts)


def _apply_budget(
    rendered: list[_RenderedModule], token_budget: int | None
) -> list[_RenderedModule]:
    """Greedy-fit in priority order: higher priority claims budget first.

    A module that does not fit the remaining budget is dropped (logged)
    and the walk continues, so a smaller lower-priority module can still
    use leftover budget. Deterministic: same modules + same budget always
    keep the same set.
    """
    if token_budget is None:
        return rendered
    kept: list[_RenderedModule] = []
    remaining = token_budget
    for module in rendered:
        if module.tokens <= remaining:
            kept.append(module)
            remaining -= module.tokens
        else:
            logger.warning(
                "Memory module dropped to fit token budget",
                module=module.context_key,
                module_tokens=module.tokens,
                token_budget=token_budget,
            )
    return kept


async def render_memory_modules(
    module_slugs: Sequence[str],
    *,
    user_id: str,
    token_budget: int | None = None,
    session: AsyncSession | None = None,
) -> str | None:
    """Render an agent's memory modules into one labeled block, or None."""
    if not module_slugs:
        return None

    if session is None:
        # Open ONE session for the whole render so every module's fetcher
        # reuses it (via FetchContext.session) instead of opening its own.
        async with get_async_session() as owned_session:
            return await render_memory_modules(
                module_slugs,
                user_id=user_id,
                token_budget=token_budget,
                session=owned_session,
            )

    modules = await _load_modules(session, module_slugs)

    rendered: list[_RenderedModule] = []
    for module in modules:
        content = await _render_module(module, user_id, session)
        if content is None:
            continue
        rendered.append(
            _RenderedModule(
                context_key=module.context_key,
                priority=module.priority,
                content=content,
                tokens=_estimate_tokens(module, content),
            )
        )

    kept = _apply_budget(rendered, token_budget)
    if not kept:
        return None
    return "\n\n".join(
        f'<module name="{module.context_key}">\n{module.content}\n</module>'
        for module in kept
    )


class MemoryModuleContextProvider:
    """chat_kit ContextProvider over an agent's memory modules.

    Reads ``user_id`` off the agent deps (duck-typed); deps without one
    contribute nothing, so the provider is safe on any deps shape.
    """

    name = "memory-modules"

    def __init__(
        self,
        module_slugs: Sequence[str],
        token_budget: int | None = None,
    ) -> None:
        self._module_slugs = tuple(module_slugs)
        self._token_budget = token_budget

    async def build(self, deps: object) -> str | None:
        user_id = getattr(deps, "user_id", None)
        if not user_id:
            logger.debug(
                "Memory module provider needs deps.user_id; skipping",
                provider=self.name,
            )
            return None
        return await render_memory_modules(
            self._module_slugs,
            user_id=str(user_id),
            token_budget=self._token_budget,
        )
