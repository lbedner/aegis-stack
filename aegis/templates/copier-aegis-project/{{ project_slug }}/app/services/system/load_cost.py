"""What each part of the app costs the webserver in memory just to load.
Every service, and the components' code the webserver runs (its UIs, the
storage client, the deploy runtime), lives inside the webserver, which
Docker can only measure whole. So each part is loaded alone in a fresh
Python (every module in it, as the webserver's routes do), on top of the
app's core (``CORE``) and the other parts it uses (the web frontend's
Overseer pages import every service: it is its own code), and the
difference read: each part's own cost, a library counted with the first
part that needs it.

Measured in the background, one part at a time (each load briefly costs
what it measures), the first time someone asks, by one process of many
(a ``claim``, which a failed run also waits out), then kept a day per
build and per way of measuring. No UI framework imports.
"""

import asyncio
import hashlib
import inspect
from pathlib import Path
import sys
import time

from pydantic import ValidationError

import app.components
from app.core.cache import get_cache
from app.core.config import settings
from app.core.log import logger
import app.services
from app.services.system import service_links
from app.services.system.ui import registry_key

from .models import LoadCosts, LoadReading

# What every part loads on top of: the app's settings and logging.
CORE = ("app.core.config", "app.core.log")
# Components that are their own processes' entry points, not the webserver's.
OWN_PROCESS = frozenset({"worker", "scheduler"})
KEEP_SECONDS = 24 * 3600
CLAIM_SECONDS = 600
_ROOT = Path(app.services.__file__).parents[2]  # where ``app`` imports from
# Run in a Python of its own: the memory in use once the core and the parts
# ``module`` (argv[1]) uses (argv[2:]) are loaded, then once it and every
# module in it are too. A module that needs what this stack left out does
# not import, as in the webserver. The reading is the last line printed
# (an import may print too).
_SCRIPT = f"""
import importlib, json, pkgutil, sys
import psutil
def load(name):
    package = importlib.import_module(name)
    for found in pkgutil.walk_packages(getattr(package, "__path__", []), name + "."):
        try:
            importlib.import_module(found.name)
        except ImportError:
            pass
for name in {CORE!r}:
    importlib.import_module(name)
for name in sys.argv[2:]:
    load(name)
process = psutil.Process()
before = process.memory_info().rss
load(sys.argv[1])
print(json.dumps({{"before": before, "after": process.memory_info().rss}}))
"""
_task: asyncio.Task[None] | None = None
# The last reading this process took from the cache: (key, when, it).
_held: tuple[str, float, LoadCosts] | None = None


class LoadError(RuntimeError):
    """A part that would not load on its own."""


def parts() -> dict[str, str]:
    """``{registry key: package}``: every service, and every component the
    webserver runs, keyed as the name registry keys them (``registry_key``)."""
    found = {}
    for group, package in (("services", app.services), ("components", app.components)):
        for name in service_links.packages(package):
            if name not in OWN_PROCESS:
                found[registry_key(group, name)] = f"{package.__name__}.{name}"
    return dict(sorted(found.items()))


async def costs() -> LoadCosts | None:
    """This build's, or None while it is measured (which the first ask
    starts); read from the cache once per process while it stands."""
    global _held
    key = _key()
    if _held and _held[0] == key and time.monotonic() - _held[1] < KEEP_SECONDS:
        return _held[2]
    found = await get_cache().get(key)
    if found is None:
        _start()
        return None
    _held = (key, time.monotonic(), LoadCosts.model_validate(found))
    return _held[2]


def _start() -> None:
    """Measure in the background, unless this process already is."""
    global _task
    if _task is None or _task.done():
        _task = asyncio.get_running_loop().create_task(measure(), name="load_cost")


async def measure() -> None:
    """Load each part alone, one at a time, and keep what each added; a
    part that will not load alone is left out, and said so. Only the
    process holding the claim measures."""
    if not await get_cache().claim(f"{_key()}:claim", ttl=CLAIM_SECONDS):
        return
    found = LoadCosts()
    befores = []
    every = parts()
    imported = {m: service_links.imports(_path(m)) for m in every.values()}
    for key, module in every.items():
        used = uses(module, imported)
        try:
            read = await _load(module, used)
        except LoadError as exc:
            logger.warning(f"Load cost of {module} not measured: {exc}")
            continue
        befores.append(read.before)
        found.parts[key] = max(read.after - read.before, 0)
    found.core = min(befores, default=0)
    await get_cache().set(_key(), found.model_dump(), ttl=KEEP_SECONDS)


def uses(module: str, imported: dict[str, set[str]]) -> list[str]:
    """The other parts ``module`` uses, by what each part ``imported``
    (``{part's package: modules it imports}``): those it imports that do not
    import it back (the server's routes import every service; loading the
    server first would load the part being measured)."""

    def imports(part: str, other: str) -> bool:
        return any(service_links.within(n, other) for n in imported[part])

    return sorted(
        other
        for other in imported
        if other != module and imports(module, other) and not imports(other, module)
    )


# The way of measuring, in the cache key: the script and the rule for what
# a part is measured on top of. A development build is always ``dev``, so a
# new way would otherwise show the old one's.
_METHOD = hashlib.sha1(
    (_SCRIPT + inspect.getsource(uses)).encode(), usedforsecurity=False
).hexdigest()[:8]


def _path(module: str) -> Path:
    return _ROOT.joinpath(*module.split("."))


def _key() -> str:
    return f"load-cost:{settings.BUILD_ID}:{_METHOD}"


async def _load(module: str, under: list[str]) -> LoadReading:
    """``module``'s memory in use before and after it loads, on top of the
    parts it uses (``under``), in a fresh Python started where ``app``
    imports from."""
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            _SCRIPT,
            module,
            *under,
            cwd=_ROOT,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise LoadError(f"could not start Python: {exc}") from exc
    out, err = await process.communicate()
    if process.returncode != 0:
        raise LoadError(err.decode(errors="replace").strip()[-300:])
    try:
        return LoadReading.model_validate_json(out.strip().splitlines()[-1])
    except (IndexError, ValidationError) as exc:
        raise LoadError(f"no reading in its output: {exc}") from exc
