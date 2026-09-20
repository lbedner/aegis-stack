"""The LLM catalog seed, one module per table.

Four shapes, and the distinction between them is the whole model:
``vendors`` is who you can call, ``models`` is what exists (each model
once, under its owner), ``deployments`` is who serves what, and
``prices`` is what that costs. The loaders that write them into the
database live in ``..llm_fixtures``.

- ``LLMOrg``: API providers (OpenAI, Anthropic, LLM7.io, etc.)
- ``LargeLanguageModel``: unique models (gpt-4o-mini exists ONCE, owned
  by OpenAI)
- ``LLMDeployment``: which vendors offer which models (LLM7.io deploys
  gpt-4o-mini via proxy)
- ``LLMPrice``: per vendor-model pricing (OpenAI charges $0.15,
  LLM7.io charges $0.00)
"""

from .deployments import DEPLOYMENTS
from .models import MODELS
from .prices import PRICES
from .vendors import VENDORS

__all__ = ["DEPLOYMENTS", "MODELS", "PRICES", "VENDORS"]
