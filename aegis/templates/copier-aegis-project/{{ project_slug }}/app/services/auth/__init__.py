"""Auth service: who the caller is, and what they may do.

``service`` is the entry point (password checks, tokens, the role
gate). Domain modules at root: ``users`` (accounts, registration,
OAuth identities), ``refresh_tokens`` (mint, rotate, revoke,
reuse-detect), and in org mode ``orgs``, ``memberships``, ``invites``.
The spine is ``deps``, ``hooks``, ``health``, ``jobs``.
"""
