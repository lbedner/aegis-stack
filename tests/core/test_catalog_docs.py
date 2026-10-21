"""The README's and the docs' component and service tables are rendered
from the specs (``aegis.core.catalog_docs``), so a part added, renamed or
described anew shows everywhere at once. A hand edit inside a table's
markers, or a spec the tables do not list, fails here."""

import re
from pathlib import Path

import pytest
import yaml

from aegis.core import catalog_docs
from aegis.core.components import COMPONENTS
from aegis.core.services import SERVICES

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("path", catalog_docs.FILES)
def test_every_table_is_what_the_specs_say(path: Path) -> None:
    text = path.read_text()
    assert text == catalog_docs.rendered(text), f"{path} is stale: run `make readme`"


@pytest.mark.parametrize("path", catalog_docs.FILES)
def test_every_file_carries_a_table(path: Path) -> None:
    text = path.read_text()
    assert any(catalog_docs.start(kind) in text for kind in catalog_docs.KINDS), path


@pytest.mark.parametrize(
    ("kind", "specs"), [("components", COMPONENTS), ("services", SERVICES)]
)
def test_every_spec_has_a_row(kind: str, specs: dict) -> None:
    table = catalog_docs.table(kind)
    for spec in specs.values():
        assert f"**[{spec.display_title}]" in table, spec.name
        assert spec.description in table, spec.name


def test_an_edit_inside_a_table_is_undone() -> None:
    marked = f"{catalog_docs.start('services')}\n| a hand edit |\n{catalog_docs.end('services')}"
    assert "a hand edit" not in catalog_docs.rendered(marked)
    assert catalog_docs.table("services") in catalog_docs.rendered(marked)


def test_an_empty_table_is_filled() -> None:
    marked = f"{catalog_docs.start('components')}\n{catalog_docs.end('components')}"
    assert catalog_docs.table("components") in catalog_docs.rendered(marked)


def test_the_dead_docs_index_is_gone() -> None:
    """``scripts/gen_docs.py`` writes the docs index from the README; a file
    on disk under that name is shadowed and never published."""
    assert not (ROOT / "docs" / "index.md").exists()


class _Untagged(yaml.SafeLoader):
    """``mkdocs.yml`` carries ``!!python/name`` tags; the nav needs none."""


_Untagged.add_multi_constructor("", lambda loader, suffix, node: None)
SPECS = {**COMPONENTS, **SERVICES}


def _nav() -> dict[str, list[str]]:
    """Each page in the docs nav, by path: the titles leading to it."""
    found: dict[str, list[str]] = {}

    def walk(items: list, trail: list[str]) -> None:
        for item in items:
            for title, value in item.items() if isinstance(item, dict) else ():
                if isinstance(value, list):
                    walk(value, [*trail, title])
                else:
                    found[value] = [*trail, title]

    walk(yaml.load((ROOT / "mkdocs.yml").read_text(), Loader=_Untagged)["nav"], [])
    return found


def _trail(spec: object) -> list[str]:
    nav = _nav()
    path = spec.docs_path  # type: ignore[attr-defined]
    page = next(p for p in (f"{path}.md", f"{path}/index.md") if p in nav)
    return nav[page]


@pytest.mark.parametrize("name", sorted(SPECS))
def test_a_parts_docs_sit_under_its_category(name: str) -> None:
    """The nav files each part's page under the section its category
    names (``PluginSpec.category``), the way Overseer groups the app."""
    spec = SPECS[name]
    section = _trail(spec)[1]
    assert section.lower() == spec.category.value, (
        f"{name}: its docs sit under {section!r}, its category is "
        f"{spec.category.value!r}: move the page in mkdocs.yml's nav"
    )


@pytest.mark.parametrize("name", sorted(SPECS))
def test_the_nav_calls_a_part_experimental_only_when_its_spec_does(name: str) -> None:
    spec = SPECS[name]
    labelled = any("(Experimental)" in title for title in _trail(spec))
    assert labelled == spec.experimental, name


def test_every_component_has_its_name_in_the_app() -> None:
    """A component the CLI calls ``redis`` the app calls ``cache``: every
    spec's app name is one ``ComponentName`` has, so each rename is said."""
    constants = (
        ROOT
        / "aegis/templates/copier-aegis-project/{{ project_slug }}/app/core/constants.py"
    ).read_text()
    names = constants.split("class ComponentName")[1].split("\nclass ")[0]
    known = set(re.findall(r'=\s*"([a-z_]+)"', names))
    assert {s.app_name for s in COMPONENTS.values()} <= known


def _project(tmp_path: Path, answers: dict[str, object]) -> Path:
    (tmp_path / ".copier-answers.yml").write_text(yaml.safe_dump(answers))
    (tmp_path / "README.md").write_text(
        f"# app\n\n{catalog_docs.PARTS_START}\n{catalog_docs.PARTS_END}\n\nMore.\n"
    )
    return tmp_path


def test_a_projects_readme_lists_exactly_what_it_has(tmp_path: Path) -> None:
    """Generated from the project's answers (``include_<name>``), so Redis
    shows where ``include_redis`` is on, and a part it lacks is absent."""
    project = _project(tmp_path, {"include_redis": True, "include_blog": True})
    catalog_docs.fill_readme(project)
    readme = (project / "README.md").read_text()
    for spec in (COMPONENTS["backend"], COMPONENTS["redis"], SERVICES["blog"]):
        assert f"**{spec.display_title}**: {spec.description}" in readme, spec.name
    assert COMPONENTS["backend"].readme.reach in readme
    assert f"**{COMPONENTS['worker'].display_title}**" not in readme
    assert "stack.md" in readme  # where each part's routes, jobs and tables are
    assert readme.endswith("More.\n")


def test_a_readme_without_the_markers_is_left_alone(tmp_path: Path) -> None:
    project = _project(tmp_path, {"include_blog": True})
    (project / "README.md").write_text("# mine\n")
    catalog_docs.fill_readme(project)
    assert (project / "README.md").read_text() == "# mine\n"
