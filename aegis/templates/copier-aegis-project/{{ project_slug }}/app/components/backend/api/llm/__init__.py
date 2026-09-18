"""LLM catalog API routes."""

# The module is ``routes`` because the exported object cannot share a name
# with it. While both were called ``router``, the package attribute
# shadowed the submodule: asking for the module handed back the APIRouter.
# Only the ``from <pkg>.<module> import name`` form worked, which is why
# the trap stayed hidden until something needed the module itself.
from .routes import router

__all__ = ["router"]
