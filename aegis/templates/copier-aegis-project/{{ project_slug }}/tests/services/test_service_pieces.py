"""A service opened up (``service_pieces``): its pieces as the service
standard names them (each standard file, its router, each domain), and
the lines between them and out of it, read from what its modules import."""

from pathlib import Path

from app.services.system import service_parts, service_pieces
from tests._files import write_tree

NOTES = "app/services/notes"


def _folder(root: Path) -> service_parts.Folder:
    return next(f for _, f in service_parts.folders(root) if f.name == "notes")


def _project(root: Path) -> Path:
    write_tree(
        root,
        {
            f"{NOTES}/__init__.py": "",
            f"{NOTES}/service.py": (
                "from app.services.notes.domains.tags import store\n"
                "from app.services.notes import queries\n"
            ),
            f"{NOTES}/queries.py": "from app.core import db\n",
            f"{NOTES}/models.py": "",
            f"{NOTES}/health.py": "",
            f"{NOTES}/slugs.py": "",  # loose: a finding, never a piece
            f"{NOTES}/seed.py": "",  # a loader
            f"{NOTES}/adapters/__init__.py": "",  # what it talks to: a piece
            f"{NOTES}/adapters/plaid.py": "",
            f"{NOTES}/domains/__init__.py": "",
            f"{NOTES}/domains/tags/__init__.py": "",
            f"{NOTES}/domains/tags/store.py": "from app.services.comms import email\n",
            "app/components/backend/api/notes/router.py": (
                "from app.services.notes.service import NoteService\n"
            ),
            "app/services/comms/__init__.py": "",
            "app/services/comms/email.py": "",
            "app/core/db.py": 'FRONTS = "database"\n',
        },
    )
    return root


def test_a_service_is_its_standard_files_its_router_and_its_domains(
    tmp_path: Path,
) -> None:
    found = service_pieces.pieces(_folder(_project(tmp_path)))
    assert [p.title for p in found] == [
        "Router",
        "Facade",
        "Models",
        "Queries",
        "Health",
        "Adapters",
        "Tags",
    ]
    tags = found[-1]
    assert tags.paths == (
        f"{NOTES}/domains/tags/__init__.py",
        f"{NOTES}/domains/tags/store.py",
    )


def test_a_line_is_an_import_between_pieces_or_out_of_the_service(
    tmp_path: Path,
) -> None:
    """Out of it, to the part the imported module is code of (a core
    client is the component it fronts); its own stack code is no line."""
    folder = _folder(_project(tmp_path))
    found = service_pieces.pieces(folder)
    keys = {p.title: p.key for p in found}
    lines = service_pieces.links(
        folder, found, {"service:notes", "service:comms", "component:database"}
    )
    assert lines[keys["Router"]] == [keys["Facade"]]
    assert lines[keys["Facade"]] == [keys["Queries"], keys["Tags"]]  # in order
    assert lines[keys["Queries"]] == ["component:database"]
    assert lines[keys["Tags"]] == ["service:comms"]
    assert lines[keys["Health"]] == []


def test_a_component_sharing_the_services_name_is_still_outside_it() -> None:
    """The scheduler service and the scheduler component are two parts: a
    line to the component leaves the service; one to its own sub-service
    does not."""
    assert service_pieces._out("component:scheduler", "service:scheduler")
    assert not service_pieces._out("service:scheduler.cron", "service:scheduler")
    assert service_pieces._out("service:blog", "service:scheduler")
