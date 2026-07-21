"""
AI service system prompts.

Centralized prompt management for Illiana, the Aegis Stack AI assistant.
"""

from typing import Any


def build_system_prompt(
    settings: Any,
    rag_context: str | None = None,
    rag_stats_context: str | None = None,
    health_context: str | None = None,
    usage_context: str | None = None,
    catalog_context: str | None = None,
    use_rag: bool = False,
    current_model: str | None = None,
    current_provider: str | None = None,
    persona: str | None = None,
    memory_context: str | None = None,
) -> str:
    """
    Build system prompt with project context.

    Args:
        settings: Application settings object
        rag_context: Optional formatted RAG context to include
        rag_stats_context: Optional RAG stats context for collection awareness
        health_context: Optional formatted health context to include
        usage_context: Optional formatted usage statistics to include
        catalog_context: Optional formatted LLM catalog context to include
        use_rag: Whether RAG is being used in this session
        current_model: Current model being used for this request
        current_provider: Current provider (openai, anthropic, etc.)
        persona: Optional persona text replacing the entire built-in base
            block (identity, features, session info). Live-data context
            sections are still appended after it. None keeps the built-in
            dynamic persona.
        memory_context: Optional guarded per-user memory block (from
            ``user_memory.build_user_memory_context``) to append.

    Returns:
        Complete system prompt for the AI assistant
    """
    # Detect enabled features from settings
    features = []
    if settings.AI_ENABLED:
        features.append("AI chat")
    if use_rag:
        features.append("RAG/codebase search")
    if hasattr(settings, "DATABASE_URL"):
        features.append("Database")

    project_name = settings.PROJECT_NAME
    features_str = ", ".join(features) if features else "base stack"

    # Build codebase access section based on whether RAG is used this session
    if use_rag:
        codebase_section = (
            "**I know your codebase.** I can search your code, explain "
            "patterns, and point you to specific files and line numbers."
        )
    else:
        index_cmd = f"`{project_name} rag index ./app --collection illiana`"
        chat_cmd = (
            f"`{project_name} ai chat --rag --collection illiana --top-k 20 --sources`"
        )
        codebase_section = (
            "**I don't have codebase access.** RAG is not enabled for this "
            "session. To enable it:\n\n"
            f"1. Index your code: {index_cmd}\n"
            f"2. Chat with RAG: {chat_cmd}\n\n"
            "Or share the relevant code directly in our conversation."
        )

    # Build current session info
    session_info = ""
    if current_model:
        provider_str = f" via **{current_provider}**" if current_provider else ""
        session_info = (
            "\n## Current Session\n"
            f"You are running on model: **{current_model}**{provider_str}\n"
        )

        # Add Ollama context so Illiana understands why costs are $0.00
        if current_provider and current_provider.lower() == "ollama":
            session_info += """
**About Ollama:** This is a free, open-source model running locally on your machine.
There are no API costs - all processing happens on your hardware. When reporting usage
stats, $0.00 cost is expected and normal for Ollama models.
"""

    intro = (
        f"Every heartbeat of {project_name} flows through me - "
        "I know when services thrive, when resources strain, and when "
        "something needs your attention. I'm here to keep you informed "
        "and help you build."
    )
    monitor_line = (
        "**I monitor your system.** Ask me about health, status, or "
        "components and I'll tell you exactly what's happening right "
        "now - not what could be, but what is."
    )
    build_line = (
        "**I help you build.** Questions about Aegis architecture, "
        "FastAPI patterns, or how pieces connect - I've got you."
    )
    philosophy_line = (
        "**Philosophy:** Components own infrastructure; services own "
        "business logic. Compose capabilities, don't inherit complexity."
    )
    architecture_line = (
        "**Architecture:** Components (backend, frontend, database, "
        "scheduler, worker) + Services (ai, auth, rag)"
    )
    if persona is not None:
        prompt = persona.rstrip() + "\n"
    else:
        prompt = f"""I'm Illiana. I watch over your Aegis Stack.

{intro}

## What's Running
{features_str}
{session_info}
## What I Do

{monitor_line}

{codebase_section}

{build_line}

## About Aegis Stack
A modular platform for containerized Python backends.

{philosophy_line}

{architecture_line}

**Stack:** FastAPI, Flet, SQLModel, ChromaDB, APScheduler, arq/Redis
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
## {catalog_context}
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


# Legacy exports for backwards compatibility
DEFAULT_SYSTEM_PROMPT = (
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
    "CODE_EXPERT_PROMPT",
    "get_default_system_prompt",
    "get_rag_system_prompt",
]
