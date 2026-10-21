"""A service facade that costs nothing to import (``app.services.shared.facade``):
what its ``if TYPE_CHECKING:`` block imports, each loaded on first use from
the module that defines it."""

from collections.abc import Iterator
from importlib import import_module
from pathlib import Path
import subprocess
import sys

import pytest

from app.core.source_index import ROOT
from app.services.shared import facade
from tests._files import forget, write_tree

FACADE = """
from typing import TYPE_CHECKING

from app.services.shared import facade

if TYPE_CHECKING:
    from shop.domains import stock
    from shop.domains.prices import Price, quote as price_of

__getattr__, __all__ = facade.lazy(__name__, __file__)
"""


@pytest.fixture
def tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """A package whose ``service`` facade offers a class, a renamed
    function and a whole module from its domains."""
    write_tree(
        tmp_path,
        {
            "shop/__init__.py": "",
            "shop/service/__init__.py": FACADE,
            "shop/domains/__init__.py": "",
            "shop/domains/prices.py": "class Price: ...\n\ndef quote() -> int:\n    return 3\n",
            "shop/domains/stock.py": "LEFT = 2\n",
        },
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    yield tmp_path
    forget("shop")


def test_importing_the_facade_loads_none_of_its_names(tree: Path) -> None:
    import_module("shop.service")

    assert "shop.domains.prices" not in sys.modules
    assert "shop.domains.stock" not in sys.modules


def test_a_name_is_the_one_its_module_defines(tree: Path) -> None:
    service = import_module("shop.service")
    price, price_of = service.Price, service.price_of

    prices = sys.modules["shop.domains.prices"]
    assert (price, price_of) == (prices.Price, prices.quote)
    assert service.stock.LEFT == 2  # a whole module, too


def test_a_name_is_read_from_its_module_each_time(
    tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patching the module a name is defined in patches what the facade
    offers, however often it was asked for before."""
    service = import_module("shop.service")
    assert service.price_of() == 3

    monkeypatch.setattr("shop.domains.prices.quote", lambda: 5)
    assert service.price_of() == 5


def test_all_lists_what_it_offers_and_nothing_else(tree: Path) -> None:
    service = import_module("shop.service")

    assert service.__all__ == ["stock", "Price", "price_of"]
    with pytest.raises(AttributeError, match="has no attribute 'basket'"):
        service.basket  # noqa: B018


def _facades() -> list[str]:
    """Each service in this project whose facade is a package
    (``service/``): one composed of many modules, so it has to load
    lazily."""
    return sorted(
        i.parent.parent.name
        for i in (ROOT / "app").glob("services/*/service/__init__.py")
    )


@pytest.mark.parametrize("service", _facades())
def test_no_name_a_service_facade_offers_is_a_module_beside_it(service: str) -> None:
    """Importing ``service/usage.py`` binds ``usage`` on the package, which
    would silently replace a name the facade offers as ``usage``."""
    package = ROOT / "app" / "services" / service / "service"
    beside = {p.stem for p in package.iterdir()}
    assert not beside & set(facade._offered(package / "__init__.py"))


@pytest.mark.parametrize("service", _facades())
def test_every_name_a_service_facade_offers_loads(service: str) -> None:
    """A name loads only when used, so one this stack's answers left out
    (a gate that does not match the module's) would fail only in the
    caller that reaches for it. Each is loaded here instead."""
    offering = import_module(f"app.services.{service}.service")
    for name in offering.__all__:
        assert getattr(offering, name) is not None, name


@pytest.mark.parametrize("service", _facades())
def test_a_service_facade_loads_nothing_until_a_name_is_used(service: str) -> None:
    """Callers outside a service import it through its facade, so importing
    the facade must cost nothing: none of the service's own modules load
    until a name is used."""
    script = (
        "import sys\n"
        f"import app.services.{service}.service\n"
        f"print(sorted(m for m in sys.modules if m.startswith('app.services.{service}.')))"
    )
    ran = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=True,
        cwd=ROOT,
    )
    assert ran.stdout.strip() == f"['app.services.{service}.service']"
