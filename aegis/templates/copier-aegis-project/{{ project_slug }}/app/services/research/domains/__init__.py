"""The research service's logic, a package each:

- ``watches``: running them, each source asked and what came back saved
- ``sources``: the sources plugins register, and finding and checking one

A source plugin registers through ``research.service``, which re-exports
what it needs from ``sources``.
"""
