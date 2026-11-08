"""
AI service bracket-syntax parser.

R3 of the plugin system refactor: this module is now a thin shim around
the generic ``parse_options`` driven by the AI service's declarative
``options`` list (see ``aegis/core/services.py`` and
``aegis/core/option_spec.py``). The typed ``AIServiceConfig`` dataclass
is preserved for back-compat with existing callers that consume
``.framework`` / ``.backend`` / etc. directly.

New plugins do not need a parser module of their own — declaring
``options=[OptionSpec(...)]`` on ``PluginSpec`` is enough.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..constants import AIFrameworks, AIProviders, AnswerKeys, StorageBackends
from ..i18n import t
from .option_spec import is_spec_with_options, parse_options
from .services import SERVICES

# Re-exported for help-string callers (e.g. aegis/commands/init.py).
# These mirror the AI service spec's option choices and exist purely
# as a back-compat surface; the canonical source is SERVICES["ai"].options.
FRAMEWORKS = set(AIFrameworks.ALL)
BACKENDS = {StorageBackends.MEMORY, StorageBackends.SQLITE, StorageBackends.POSTGRES}
PROVIDERS = AIProviders.ALL


@dataclass
class AIServiceConfig:
    """Parsed AI service configuration (back-compat shape)."""

    framework: str
    backend: str
    providers: list[str]
    rag_enabled: bool = False
    voice_enabled: bool = False
    evals_enabled: bool = False


def parse_ai_service_config(service_string: str) -> AIServiceConfig:
    """Parse an ``ai[...]`` string into the legacy typed dataclass."""
    parsed = parse_options(service_string, SERVICES["ai"])
    return AIServiceConfig(
        framework=parsed["framework"],
        backend=parsed["backend"],
        providers=list(parsed["providers"]),
        rag_enabled=bool(parsed.get("rag", False)),
        voice_enabled=bool(parsed.get("voice", False)),
        evals_enabled=bool(parsed.get("evals", False)),
    )


def is_ai_service_with_options(service_string: str) -> bool:
    """True when ``service_string`` uses ``ai[...]`` bracket syntax."""
    s = service_string.strip()
    return s.startswith("ai[") and is_spec_with_options(s)


def evals_rule(answers: Mapping[str, Any]) -> str | None:
    """Why these answers cannot have the eval harness, or None: it scores
    Pydantic AI's tool events and scripts a turn with its ``FunctionModel``,
    which LangChain has neither of."""
    evals = answers.get(AnswerKeys.AI_EVALS) in (True, "yes")
    framework = answers.get(AnswerKeys.AI_FRAMEWORK, AIFrameworks.PYDANTIC_AI)
    if evals and framework != AIFrameworks.PYDANTIC_AI:
        return t("validation.evals_needs_pydantic_ai", framework=framework)
    return None
