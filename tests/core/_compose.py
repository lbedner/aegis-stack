"""A generated project's compose files, rendered and read as Compose reads
them: YAML with Compose's ``!override`` tag (the dev overlay's ports in
place of the base file's), which a plain YAML loader refuses."""

from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

from aegis.core.component_files import get_copier_defaults, get_template_path


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_constructor("!override", _Loader.construct_sequence)


def render(name: str, **overrides: Any) -> str:
    """The project file ``name`` (``docker-compose.dev.yml.jinja``) rendered
    with the copier defaults and ``overrides``."""
    env = Environment(loader=FileSystemLoader(str(get_template_path())))
    context = {**get_copier_defaults(), "project_slug": "demo", **overrides}
    return env.get_template(f"{{{{ project_slug }}}}/{name}").render(context)


def load(text: str) -> Any:
    """``text`` (a rendered compose file) as data, ``!override`` read."""
    return yaml.load(text, Loader=_Loader)  # noqa: S506 - a SafeLoader subclass
