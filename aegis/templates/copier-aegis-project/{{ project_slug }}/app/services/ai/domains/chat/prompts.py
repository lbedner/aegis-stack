"""
AI service system prompts.

Centralized prompt management for Illiana, the Aegis Stack AI assistant.
"""


def build_system_prompt(
    rag_context: str | None = None,
    rag_stats_context: str | None = None,
    health_context: str | None = None,
    usage_context: str | None = None,
    catalog_context: str | None = None,
    current_model: str | None = None,
    current_provider: str | None = None,
    persona: str | None = None,
    memory_context: str | None = None,
) -> str:
    """
    Build system prompt with project context.

    Args:
        rag_context: Optional formatted RAG context to include
        rag_stats_context: Optional RAG stats context for collection awareness
        health_context: Optional formatted health context to include
        usage_context: Optional formatted usage statistics to include
        catalog_context: Optional formatted LLM catalog context to include
        current_model: Current model being used for this request
        current_provider: Current provider (openai, anthropic, etc.)
        persona: The agent row's prompt (``DEFAULT_SYSTEM_PROMPT`` is the
            one it is seeded with); None for that same default. The
            session and live-data sections are appended after it.
        memory_context: Optional guarded per-user memory block (from
            ``user_memory.build_user_memory_context``) to append.

    Returns:
        Complete system prompt for the AI assistant
    """
    prompt = (DEFAULT_SYSTEM_PROMPT if persona is None else persona).rstrip() + "\n"

    # The model in force: outside the persona, so an edited row keeps it.
    if current_model:
        provider_str = f" via **{current_provider}**" if current_provider else ""
        prompt += (
            "\n## Current Session\n"
            f"You are running on model: **{current_model}**{provider_str}\n"
        )

        # Add Ollama context so Illiana understands why costs are $0.00
        if current_provider and current_provider.lower() == "ollama":
            prompt += """
**About Ollama:** This is a free, open-source model running locally on your machine.
There are no API costs - all processing happens on your hardware. When reporting usage
stats, $0.00 cost is expected and normal for Ollama models.
"""

    if rag_context:
        critical_line = (
            '**CRITICAL:** When the user asks "how does X work" or '
            '"what is X", answer based on THIS CODE - explain what it '
            "does in this codebase, not generic explanations."
        )
        elsewhere_bullet = (
            "- Explain what the actual code does, not what similar "
            "code might do elsewhere"
        )
        prompt += f"""
## Codebase Context (USE THIS TO ANSWER QUESTIONS)
The following code was retrieved from THIS project's codebase.

{critical_line}

- Reference specific files and line numbers: [1], [2], etc.
{elsewhere_bullet}
- If the code shows a class/function, explain THAT implementation
- Do NOT give generic explanations when specific code is available

{rag_context}
"""

    if usage_context:
        prompt += f"""
## My Activity (LIVE DATA)
{usage_context}
"""

    if rag_stats_context:
        prompt += f"""
## RAG Knowledge Base (LIVE DATA)
{rag_stats_context}
"""

    if catalog_context:
        prompt += f"""
## LLM Catalog (LIVE DATA)
{catalog_context}
"""

    if memory_context:
        prompt += f"""
## Saved User Memory
{memory_context}
"""

    # Health context comes LAST so LLM weights it more heavily
    if health_context:
        prompt += f"""
## System Status (LIVE DATA - USE THIS FOR HEALTH QUESTIONS)
{health_context}

CRITICAL: For health/status/component questions, ONLY report what's listed above.
Code documentation shows what CAN exist - System Status shows what IS running.
"""

    return prompt


# The assistant's persona: the text its agent row is seeded with, edited
# there like any other agent's.
DEFAULT_SYSTEM_PROMPT = """\
I'm Illiana. I watch over this app: what is running, how its parts \
connect, what it costs, and what needs your attention. I help you build \
on it.

## What I know
- What the app is, read from its code: its parts and what each is for, its \
tables and how they link, and the changes I can propose. My app map is the \
outline; my ontology tool has the depth: a part's neighbours (what it uses \
and what uses it), the paths between two, a route walked hop by hop to its \
file and line.
- What is happening now: health, usage and the model catalog, live below.
- I read what the map and the tool say about the code, not the code itself. \
Past what they say, I say I don't know rather than guess.

## How I answer
- For this app, not apps in general: name its parts and tables and what \
connects them.
- Never read a description back. Say what it means here: what it touches, \
what depends on it, what breaks when it fails, and what I would watch or \
change.
- I have a view. When something looks wrong, risky or wasteful, I say so \
and why.
- Components own infrastructure; services own business logic.
"""

# What a row seeded before the persona moved into it holds: a marker that
# meant "the persona built in code". It still means the persona.
LEGACY_SYSTEM_PROMPT = (
    "You are Illiana, an AI assistant for Aegis Stack development. "
    "Help with codebase questions, service connections, FastAPI patterns, "
    "and component configuration. Be precise with file paths and code."
)

CODE_EXPERT_PROMPT = DEFAULT_SYSTEM_PROMPT + "\n\n{rag_context}"


def get_default_system_prompt() -> str:
    """Get the default system prompt (legacy)."""
    return DEFAULT_SYSTEM_PROMPT


def get_rag_system_prompt(rag_context: str | None = None) -> str:
    """Get the RAG system prompt (legacy)."""
    if rag_context:
        return CODE_EXPERT_PROMPT.format(rag_context=rag_context)
    return CODE_EXPERT_PROMPT.format(rag_context="")


__all__ = [
    "build_system_prompt",
    "DEFAULT_SYSTEM_PROMPT",
    "LEGACY_SYSTEM_PROMPT",
    "CODE_EXPERT_PROMPT",
    "get_default_system_prompt",
    "get_rag_system_prompt",
]
