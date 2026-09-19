"""The blog's slug shape.

One wrapper over the shared slugifier, because an empty title still
needs a URL. Its own module so every blog module can reach it without
importing ``service``, which imports most of them back.
"""

from app.core.formatting import slugify as core_slugify


def slugify(value: str) -> str:
    """The shared slug shape, with the blog's fallback for empty titles."""
    return core_slugify(value) or "post"
