"""Seed data: ``seed.py`` for baseline reference rows (currencies, import
profiles) run at startup; ``demo_seed.py`` for the full demo ledger driven
by the CLI (``finance seed-demo``)."""

from app.services.finance.seeds import demo_seed, seed

__all__ = [
    "demo_seed",
    "seed",
]
