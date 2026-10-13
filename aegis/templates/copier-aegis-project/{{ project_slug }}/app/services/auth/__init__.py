"""Auth service: who the caller is, and what they may do.

``service`` is the entry point (password checks, tokens, the role gate,
and what callers outside need of its domains). The domains live under
``domains/``: ``users``, ``sessions``, and in org mode ``orgs``. The
spine is ``deps``, ``health``, ``jobs``.
"""
