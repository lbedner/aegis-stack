"""Overseer > Code (``overseer_code``): the project's source, read-only, as
a tree of folders and one file open beside it."""

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.components.web_frontend import overseer_code
from app.components.web_frontend.rendering import with_query
from app.core.config import settings
from app.core.constants import AppEnv
from app.services.system.models import ComponentStatus
from tests.web.dom import none, one, select, text
from tests.web.overseer import CACHE, page_html, reported_only, sign_in, status_with

PAGE = "/overseer/code"
SECRET = "SECRET_KEY=hunter2"
# A project: its source, and what the tree never shows.
FILES = {
    "app/main.py": "import os\n\n\ndef main():\n    return os.getcwd()\n",
    "app/core/config.py": "DEBUG = True\n",
    "docs/index.md": "# Docs\n",
    "Dockerfile": "FROM python\n",
    ".env": SECRET,
    ".git/config": SECRET,
    "app/__pycache__/main.cpython-313.pyc": SECRET,
    "node_modules/x/index.js": SECRET,
    "data/app.db": SECRET,
    "traefik/acme.json": SECRET,
}


def _write(project: Path, files: dict[str, str]) -> None:
    for name, body in files.items():
        (project / name).parent.mkdir(parents=True, exist_ok=True)
        (project / name).write_text(body)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _write(tmp_path, FILES)
    monkeypatch.setattr(overseer_code, "PROJECT_ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def client(app: FastAPI, monkeypatch: pytest.MonkeyPatch, project: Path) -> TestClient:
    monkeypatch.setattr(settings, "APP_ENV", AppEnv.DEV)
    reported_only(monkeypatch)
    auth = ComponentStatus(name="auth", message="ok")
    sign_in(app, monkeypatch, status_with(CACHE, services=[auth]))
    return TestClient(app)


def _tree(html: str) -> list[str]:
    return [a.get("data-path") for a in select(html, "[data-code-tree] a")]


def test_the_sidebar_leads_to_it(client: TestClient) -> None:
    link = one(page_html(client, "/overseer"), f'#overseer-nav a[href="{PAGE}"]')
    assert text(link) == "Code"


def test_the_tree_is_the_source_and_nothing_else(client: TestClient) -> None:
    """Folders first, then files, by name; never a hidden file (``.env``),
    a generated or installed one, data, or what is not source."""
    html = page_html(client, PAGE)
    assert _tree(html) == [
        "app/core/config.py",
        "app/main.py",
        "docs/index.md",
        "Dockerfile",
    ]
    assert SECRET not in html
    folders = [text(s) for s in select(html, "[data-code-tree] summary")]
    assert folders == ["app", "core", "docs"]


def test_a_file_opens_beside_the_tree_numbered_and_highlighted(
    client: TestClient,
) -> None:
    html = page_html(client, f"{PAGE}?file=app/main.py")
    pane = one(html, "#code-file")
    assert "app/main.py" in text(pane)
    assert "def" in [text(k) for k in select(pane, ".highlight .k")]
    # Every line has an address a traceback or a log can link to.
    one(pane, '[id="L-4"]')
    # Its folder open in the tree, and its link marked.
    link = one(html, '[data-code-tree] a[data-path="app/main.py"]')
    assert link.get("aria-current") == "page"
    opened = [
        text(d.find("summary")) for d in select(html, "[data-code-tree] details[open]")
    ]
    assert opened == ["app"]


def test_the_tree_and_the_file_scroll_and_the_page_does_not(
    client: TestClient,
) -> None:
    """Like Chat: the view fills the screen below its header, and each pane
    scrolls on its own."""
    html = page_html(client, f"{PAGE}?file=app/main.py")
    view = one(html, ".overseer-fill")
    for pane in (one(view, "[data-code-tree]"), one(view, "#code-file")):
        assert "overflow-auto" in pane.get("class").split()


def test_a_file_can_be_jumped_to_by_name(client: TestClient) -> None:
    """Every file the tree has, offered as the viewer types (``Cmd-P``
    focuses it); picking one swaps the file as a click in the tree does."""
    html = page_html(client, PAGE)
    jump = one(html, "[data-code-jump]")
    offered = [
        o.get("value") for o in select(html, f"datalist#{jump.get('list')} option")
    ]
    assert offered == _tree(html)
    form = jump.getparent()
    assert form.get("hx-target") == "#code-file"
    assert jump.get("name") == overseer_code.FILE


def test_the_file_says_which_build_it_is_from(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In dev the files are the working tree; deployed, the build's commit."""
    url = f"{PAGE}?file=app/main.py"
    assert "working tree" in text(one(page_html(client, url), "#code-file"))
    monkeypatch.setattr(settings, "BUILD_ID", "abc1234")
    assert "at abc1234" in text(one(page_html(client, url), "#code-file"))


def test_a_click_in_the_tree_swaps_only_the_file(client: TestClient) -> None:
    link = one(page_html(client, PAGE), '[data-code-tree] a[data-path="app/main.py"]')
    assert link.get("href") == with_query(PAGE, file="app/main.py")
    assert link.get("hx-target") == link.get("hx-select") == "#code-file"
    # The swap is the file alone: the tree is not walked into the answer.
    swap = client.get(
        link.get("href"), headers={"HX-Request": "true", "HX-Target": "code-file"}
    ).text
    one(swap, "#code-file .highlight")
    none(swap, "[data-code-tree]")


@pytest.mark.parametrize(
    "path",
    [".env", "data/app.db", "traefik/acme.json", "../outside.py", "/etc/hosts.py"],
)
def test_only_what_the_tree_shows_can_be_opened(
    client: TestClient, project: Path, path: str
) -> None:
    (project.parent / "outside.py").write_text(SECRET)
    html = page_html(client, f"{PAGE}?file={path}")
    one(html, "#code-file [data-code-missing]")
    assert SECRET not in html


def test_a_link_out_of_the_project_is_not_followed(
    client: TestClient, project: Path
) -> None:
    (project.parent / "outside.py").write_text(SECRET)
    (project / "app" / "escape.py").symlink_to(project.parent / "outside.py")
    html = page_html(client, f"{PAGE}?file=app/escape.py")
    assert "app/escape.py" not in _tree(html)
    assert SECRET not in html


def test_off_outside_dev_until_it_is_turned_on(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The source is a map of the app: outside dev, an admin turns it on."""
    monkeypatch.setattr(settings, "APP_ENV", AppEnv.PROD)
    none(page_html(client, "/overseer"), f'#overseer-nav a[href="{PAGE}"]')
    assert client.get(PAGE).status_code == 404
    monkeypatch.setattr(settings, "OVERSEER_CODE_ENABLED", True)
    one(page_html(client, "/overseer"), f'#overseer-nav a[href="{PAGE}"]')


def test_dev_by_any_of_its_names(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """What the rest of the app reads as dev (``settings.is_dev``)."""
    monkeypatch.setattr(settings, "APP_ENV", "local")
    one(page_html(client, "/overseer"), f'#overseer-nav a[href="{PAGE}"]')


# A service's files, spread over the project, and the cache's (whose page,
# and so its files, is named redis).
SPREAD = (
    "app/services/auth/service.py",
    "app/components/web_frontend/overseer_auth.py",
    "tests/services/auth/test_service.py",
)
REDIS = "app/components/web_frontend/overseer_redis.py"


def _add(project: Path, *paths: str) -> None:
    _write(project, dict.fromkeys(paths, "x = 1\n"))


def test_a_component_or_service_keeps_only_its_files_and_their_folders(
    client: TestClient, project: Path
) -> None:
    """How spread out it is: its files wherever they are, every folder down
    to them open, and how many files in how many folders."""
    _add(project, *SPREAD, REDIS)
    html = page_html(client, with_query(PAGE, owner="auth"))
    assert sorted(_tree(html)) == sorted(SPREAD)
    assert not select(html, "[data-code-tree] details:not([open])")
    assert text(one(html, "[data-code-spread]")) == "3 files in 3 folders"
    # A component's files go by its page's name too.
    assert _tree(page_html(client, with_query(PAGE, owner="cache"))) == [REDIS]


def test_every_component_and_service_is_a_choice(client: TestClient) -> None:
    html = page_html(client, PAGE)
    form = one(html, "#code-scope")
    assert form.get("hx-target") == "#code-view"
    owners = [i.get("value") for i in select(form, "input[name=owner]")]
    assert owners == ["", "cache", "auth"]


def test_the_path_above_the_file_scopes_the_tree_to_a_folder(
    client: TestClient,
) -> None:
    html = page_html(client, f"{PAGE}?file=app/core/config.py")
    crumbs = select(one(html, "#code-file"), "[data-code-crumb]")
    assert [text(a) for a in crumbs] == ["app", "core"]
    assert crumbs[1].get("href") == with_query(
        PAGE, file="app/core/config.py", folder="app/core"
    )
    assert crumbs[1].get("hx-target") == "#code-view"
    scoped = page_html(client, crumbs[1].get("href"))
    assert _tree(scoped) == ["app/core/config.py"]


def test_the_tree_keeps_its_scope_as_files_open(
    client: TestClient, project: Path
) -> None:
    _add(project, *SPREAD)
    link = one(
        page_html(client, with_query(PAGE, owner="auth")),
        f'[data-code-tree] a[data-path="{SPREAD[0]}"]',
    )
    assert link.get("href") == with_query(PAGE, file=SPREAD[0], owner="auth")


# A name defined in one module and used in another, imported both ways.
SYMBOLS = {
    "app/core/store.py": "def put(key):\n    return key\n",
    "app/services/use.py": (
        "import os\n"
        "from app.core.store import put\n"
        "from app.core import store\n"
        "\n"
        "\n"
        "def run():\n"
        "    put(1)\n"
        "    store.put(2)\n"
        "    return os.sep\n"
    ),
}
SYMBOL = overseer_code.SYMBOL


def _symbol(client: TestClient, path: str, line: int, col: int) -> str:
    return page_html(
        client, with_query(SYMBOL, file=path, line=str(line), col=str(col))
    )


def test_a_name_leads_to_its_definition_and_every_use(
    client: TestClient, project: Path
) -> None:
    """Click ``put`` where it is called: where it is defined, and each line
    that names it, imported or through its module."""
    _write(project, SYMBOLS)
    html = _symbol(client, "app/services/use.py", 7, 4)
    defined = one(html, "[data-symbol-definition] a")
    assert defined.get("href") == overseer_code.line_url("app/core/store.py", 1)
    used = [a.get("href") for a in select(html, "[data-symbol-references] a")]
    assert used == [
        overseer_code.line_url("app/core/store.py", 1),
        overseer_code.line_url("app/services/use.py", 2),
        overseer_code.line_url("app/services/use.py", 7),
        overseer_code.line_url("app/services/use.py", 8),
    ]
    # The same symbol reached through its module, and from its definition.
    for line, col in ((8, 10), (2, 27)):
        again = _symbol(client, "app/services/use.py", line, col)
        assert one(again, "[data-symbol-definition] a").get("href") == defined.get(
            "href"
        )
    from_def = _symbol(client, "app/core/store.py", 1, 4)
    assert len(select(from_def, "[data-symbol-references] a")) == 4


def test_a_module_name_leads_to_its_file(client: TestClient, project: Path) -> None:
    _write(project, SYMBOLS)
    html = _symbol(client, "app/services/use.py", 2, 5)
    link = one(html, "[data-symbol-definition] a")
    assert link.get("href") == overseer_code.line_url("app/core/store.py", 1)


def test_a_name_from_outside_the_project_says_so(
    client: TestClient, project: Path
) -> None:
    _write(project, SYMBOLS)
    html = _symbol(client, "app/services/use.py", 9, 11)
    none(html, "[data-symbol-definition] a")
    one(html, "[data-symbol-outside]")


def test_a_python_file_offers_its_names(client: TestClient, project: Path) -> None:
    """Its names can be clicked (``app.js`` asks where the click was), the
    answer peeking beside the name, not in the drawer; a file that is not
    Python has none to offer."""
    _write(project, SYMBOLS)
    pane = one(page_html(client, f"{PAGE}?file=app/services/use.py"), "#code-file")
    assert pane.get("data-code-symbol") == with_query(
        SYMBOL, file="app/services/use.py"
    )
    one(pane, "#code-peek[popover]")
    markdown = one(page_html(client, f"{PAGE}?file=docs/index.md"), "#code-file")
    assert markdown.get("data-code-symbol") is None


def test_opening_the_page_warms_the_index_and_a_swap_does_not(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[bool] = []
    monkeypatch.setattr(
        overseer_code, "warm_in_background", lambda: started.append(True)
    )
    page_html(client, PAGE)
    assert started == [True]
    client.get(
        with_query(PAGE, file="app/main.py"),
        headers={"HX-Request": "true", "HX-Target": overseer_code.PANE},
    )
    assert started == [True]


def test_a_click_after_warming_reads_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, project: Path
) -> None:
    """The first click's every-use look-up reads the whole source: warming
    has read it already."""
    _write(project, SYMBOLS)
    overseer_code.warm()

    def unread(*_: object, **__: object) -> str:
        raise AssertionError("read after warming")

    monkeypatch.setattr(Path, "read_text", unread)
    html = _symbol(client, "app/services/use.py", 7, 4)
    assert len(select(html, "[data-symbol-references] a")) == 4


def test_no_symbol_while_code_is_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, project: Path
) -> None:
    _write(project, SYMBOLS)
    monkeypatch.setattr(settings, "APP_ENV", AppEnv.PROD)
    url = with_query(SYMBOL, file="app/services/use.py", line="7", col="4")
    assert client.get(url).status_code == 404


def test_a_frame_is_the_apps_only_when_it_is_a_file_the_tree_shows(
    client: TestClient, project: Path
) -> None:
    """A library can have an ``app`` folder of its own: only a frame in
    this project's files, as the tree shows them, is the app's."""
    _write(project, {"app/y.py": "x = 1\n"})
    library = 'File "/opt/venv/lib/python3.14/site-packages/foo/app/y.py", line 1, in f'
    own = f'File "{project}/app/y.py", line 1, in f'
    assert overseer_code.own_frames(library) == []
    assert [f.path for f in overseer_code.own_frames(own)] == ["app/y.py"]
