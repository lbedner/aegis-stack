"""Insights service: a project's adoption metrics, collected, stored and rendered.

- ``domains/`` - what the service KNOWS. ``metrics`` (the bulk and point
  reads the dashboard and API slice, project-scoped), ``events`` (the
  user-authored timeline), ``goals`` (targets over a metric, progress
  derived live from the series), ``projects`` (per-user tenancy and
  encrypted credentials). The last three ship only in per-user mode.
- ``adapters/`` - what it TALKS TO. ``collectors`` pull from GitHub,
  PyPI, Plausible and Reddit; ``collectors.collection`` runs them and
  detects new records.
- ``queries/`` - every read, one module per section.
- ``views/`` - the display-ready shape of each dashboard tab, consumed
  by both the Flet dashboard and the htmx pages.
- ``schemas/`` - what is spoken over the API; ``models`` - what is stored.

The entry point is ``service.InsightService``, injected via ``deps``.
The spine is ``deps``, ``constants``, ``utils``, ``health``, ``jobs``,
``seed``.
"""
