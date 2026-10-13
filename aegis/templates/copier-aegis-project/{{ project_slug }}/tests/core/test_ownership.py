"""Who owns a file or module (``ownership.owner``): the one installed
service or component it belongs to, from where it is and, for a route or
a test, what it imports."""

from pathlib import Path

import pytest

from app.core import source_index
from app.core.ownership import Owner, owner
from tests._files import write_tree

# A project: what a route, a core client and a test import decides theirs.
FILES = {
    "app/services/ai/domains/llm/__init__.py": "",
    "app/services/ai/domains/voice/x.py": "",
    "app/services/ai/domains/spend.py": "",  # a domain that is one module
    "app/services/ai/domains/__init__.py": "",
    "app/services/auth/service.py": "",
    "app/services/scheduler/jobs.py": "",
    "app/services/random_helper/helper.py": "",
    "app/components/backend/api/llm/routes.py": "",
    "app/components/backend/api/orgs/__init__.py": "",
    "app/components/backend/api/orgs/router.py": (
        "from app.services.auth.service import AuthService\n"
    ),
    "app/components/backend/api/secrets/router.py": "",
    "app/components/backend/api/health.py": "",
    "app/components/scheduler/main.py": "",
    "app/components/web_frontend/overseer_auth.py": "",
    "app/components/web_frontend/overseer_redis.py": "",
    "app/components/web_frontend/templates/pages/overseer/auth/_body.html": "",
    "app/core/cache.py": "from app.core.constants import ComponentName\n"
    "FRONTS = ComponentName.CACHE\n",
    "app/core/log.py": "",
    "app/cli/ai/chat.py": "",
    "tests/services/test_auth_only.py": "from app.services.auth import service\n",
    "tests/services/test_auth_and_ai.py": (
        "from app.services.auth import service\nimport app.services.ai.domains.llm\n"
    ),
    "tests/components/test_scheduler.py": "from app.components.scheduler import main\n",
    # A folder that is part of another part says so beside its code.
    "app/services/rag/__init__.py": "from app.core.constants import ServiceName\n"
    "PART_OF = ServiceName.AI\n",
    "app/services/rag/indexer.py": "",
    "app/services/system/__init__.py": 'PART_OF = "stack"\n',
    "app/services/system/health.py": "",
    "app/services/ops/__init__.py": 'PART_OF = "deploy"\n',
    "app/services/ops/audit.py": "",
    "app/components/deploy/docker.py": "",
    "app/components/inference/client.py": "",
    "app/integrations/main.py": "",
}


@pytest.fixture
def index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> source_index.Index:
    write_tree(tmp_path, FILES)
    from app.services.system import health

    monkeypatch.setattr(
        health,
        "registered_health_names",
        lambda: {"components": (), "services": ("scheduler",)},
    )
    return source_index.at(tmp_path)


@pytest.mark.parametrize(
    "where, expected",
    [
        ("app/services/ai/domains/voice/x.py", Owner("service", "ai", "voice")),
        ("app/services/ai/domains/spend.py", Owner("service", "ai", "spend")),
        ("app/services/ai/domains/__init__.py", Owner("service", "ai")),
        ("app/components/backend/api/llm/routes.py", Owner("service", "ai", "llm")),
        ("app/components/backend/api/orgs/router.py", Owner("service", "auth")),
        # The rest of a route's folder goes with what the folder imports.
        ("app/components/backend/api/orgs/__init__.py", Owner("service", "auth")),
        ("app/components/backend/api/secrets/router.py", Owner("component", "secrets")),
        ("app/components/backend/api/health.py", Owner("component", "backend")),
        ("app/core/cache.py", Owner("component", "cache")),
        ("app/core/log.py", None),
        ("app/services/scheduler/jobs.py", Owner("service", "scheduler")),
        ("app/components/scheduler/main.py", Owner("component", "scheduler")),
        ("app/services/random_helper/helper.py", None),
        ("app/cli/ai/chat.py", Owner("service", "ai")),
        ("app/services/rag/indexer.py", Owner("service", "ai", "rag")),
        ("app/services/system/health.py", Owner("stack", "system")),
        ("app/services/ops/audit.py", Owner("component", "deploy", "ops")),
        # A part with no health check, known from its spec (``parts``).
        ("app/components/deploy/docker.py", Owner("component", "deploy")),
        # A folder named for its CLI name: inference is Ollama's.
        ("app/components/inference/client.py", Owner("component", "ollama")),
        # The app's own assembly: the server's.
        ("app/integrations/main.py", Owner("component", "backend")),
        # A component's Overseer page goes with what it shows.
        ("app/components/web_frontend/overseer_auth.py", Owner("service", "auth")),
        ("app/components/web_frontend/overseer_redis.py", Owner("component", "cache")),
        (
            "app/components/web_frontend/templates/pages/overseer/auth/_body.html",
            Owner("service", "auth"),
        ),
        ("tests/services/test_auth_only.py", Owner("service", "auth")),
        ("tests/services/test_auth_and_ai.py", None),
        ("tests/components/test_scheduler.py", Owner("component", "scheduler")),
        # A module, by its dotted name; a deployed or Windows path.
        ("app.services.auth", Owner("service", "auth")),
        ("app.core.cache.get_cache", Owner("component", "cache")),
        ("/code/app/services/auth/service.py", Owner("service", "auth")),
        (r"C:\project\app\services\auth\service.py", Owner("service", "auth")),
        ("/code/vendor/services/ai/chat.py", None),
        ("/code/app/services/../core.py", None),
        ("/code/app/services/ai", None),
    ],
)
def test_the_owner_of(
    index: source_index.Index, where: str, expected: Owner | None
) -> None:
    assert owner(where, index) == expected
