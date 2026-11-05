"""The sandbox rules' example script (``code_mode.EXAMPLE``) passes the type
check Code Mode holds a first script to, against the real stub of the tool
it calls. A tool typed ``A | B`` must be narrowed before it is indexed;
an example that indexes it straight teaches every first script to fail.

Lives in the chat_kit test package: Code Mode (and Monty) ship with the
pydantic-ai loop, which langchain-framework stacks prune.
"""

from pydantic_ai import Tool
from pydantic_ai_harness.code_mode._toolset import CodeModeToolset
import pydantic_monty
import pytest

from app.services.ai.domains.chat.code_mode import EXAMPLE
from app.services.system.tools import errors


def test_the_example_passes_the_sandbox_type_check() -> None:
    stubs = CodeModeToolset._build_type_check_stubs(
        {"errors": Tool(errors, takes_ctx=False).tool_def}
    )
    with (
        pydantic_monty.Monty() as monty,
        monty.checkout(type_check=True, type_check_stubs=stubs) as session,
    ):
        # Past the check it runs, where the stub has no body to call.
        with pytest.raises(pydantic_monty.MontyRuntimeError, match="NameError"):
            session.feed_run(EXAMPLE)
