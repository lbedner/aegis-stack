"""Tests that hold Aegis's own code to its standard (the service layout and
its debt, the memory budget, where things are declared) run only in
Aegis's CI, which sets ``AEGIS_CONFORMANCE=1``. A project built on Aegis is
never failed by them; to hold its own code to the rules, it runs
``patterns check --update`` once, then ``patterns check --strict``.

    pytestmark = CONFORMANCE
"""

import os

import pytest

CONFORMANCE = pytest.mark.skipif(
    os.environ.get("AEGIS_CONFORMANCE") != "1",
    reason="Aegis's own standard, checked in Aegis's CI",
)
