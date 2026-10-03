"""
Component name parsing utilities for Aegis Stack.

This module provides centralized utilities for parsing component names with engine
information (e.g., 'database[sqlite]') to eliminate code duplication and improve
robustness throughout the codebase.
"""

import re

# A comma not followed by a ``]`` that closes before the next ``[``: the
# commas of ``inference[ollama,docker]`` stay inside their item.
_TOP_LEVEL_COMMA = re.compile(r",(?![^\[]*\])")


def split_bracket_list(value: str) -> list[str]:
    """Split ``a[x,y],b`` on its top-level commas: ``['a[x,y]', 'b']``.

    Items are stripped; empty ones are kept so callers can refuse them.
    """
    return [item.strip() for item in _TOP_LEVEL_COMMA.split(value)]


def parse_component_name(component: str) -> tuple[str, str | None]:
    """
    Parse a component name with optional engine information.

    Args:
        component: Component name like 'database[sqlite]' or 'scheduler'

    Returns:
        Tuple of (base_name, engine) where engine is None if not specified

    Examples:
        parse_component_name('database[sqlite]') -> ('database', 'sqlite')
        parse_component_name('scheduler') -> ('scheduler', None)
        parse_component_name('database[]') -> ('database', None)
        parse_component_name('inference[ollama,docker]') -> ('inference', 'ollama,docker')

    Raises:
        ValueError: If component name format is invalid
    """
    if not component or not isinstance(component, str):
        raise ValueError(
            f"Component name must be a non-empty string, got: {component!r}"
        )

    component = component.strip()
    if not component:
        raise ValueError("Component name cannot be empty or whitespace")

    # Use regex for robust parsing. The bracket holds one token or a comma
    # list (a component with several option axes, ``inference[ollama,docker]``);
    # each spec validates its own values.
    pattern = (
        r"^([a-zA-Z][a-zA-Z0-9_-]*?)"
        r"(?:\[([a-zA-Z0-9_-]+(?:\s*,\s*[a-zA-Z0-9_-]+)*)?\])?$"
    )
    match = re.match(pattern, component)

    if not match:
        raise ValueError(
            f"Invalid component name format: '{component}'. "
            "Expected format: 'name', 'name[engine]' or 'name[a,b]'"
        )

    base_name, engine = match.groups()

    # Handle empty engine brackets
    if engine == "":
        engine = None

    return base_name, engine


def extract_base_component_name(component: str) -> str:
    """
    Extract the base component name without engine information.

    Args:
        component: Component name like 'database[sqlite]' or 'scheduler'

    Returns:
        Base component name

    Examples:
        extract_base_component_name('database[sqlite]') -> 'database'
        extract_base_component_name('scheduler') -> 'scheduler'
    """
    base_name, _ = parse_component_name(component)
    return base_name


def extract_base_service_name(service: str) -> str:
    """
    Extract the base service name from a service string with optional bracket syntax.

    Unlike extract_base_component_name, this handles multi-value bracket syntax
    like 'ai[langchain, openai]' which is specific to AI service configuration.

    Args:
        service: Service name like 'ai[langchain, openai]', 'ai[sqlite]', or 'auth'

    Returns:
        Base service name

    Examples:
        extract_base_service_name('ai[langchain, openai]') -> 'ai'
        extract_base_service_name('ai[sqlite]') -> 'ai'
        extract_base_service_name('auth') -> 'auth'
    """
    if "[" in service:
        return service.split("[")[0].strip()
    return service.strip()


def extract_engine_info(component: str) -> str | None:
    """
    Extract engine information from a component name.

    Args:
        component: Component name like 'database[sqlite]' or 'scheduler'

    Returns:
        Engine name or None if not specified

    Examples:
        extract_engine_info('database[sqlite]') -> 'sqlite'
        extract_engine_info('scheduler') -> None
        extract_engine_info('database[]') -> None
    """
    _, engine = parse_component_name(component)
    return engine


def format_component_with_engine(base: str, engine: str | None) -> str:
    """
    Format a component name with engine information.

    Args:
        base: Base component name
        engine: Engine name or None

    Returns:
        Formatted component name

    Examples:
        format_component_with_engine('database', 'sqlite') -> 'database[sqlite]'
        format_component_with_engine('scheduler', None) -> 'scheduler'
    """
    if not base or not isinstance(base, str):
        raise ValueError(
            f"Base component name must be a non-empty string, got: {base!r}"
        )

    base = base.strip()
    if not base:
        raise ValueError("Base component name cannot be empty or whitespace")

    if engine is not None:
        if not isinstance(engine, str) or not engine.strip():
            raise ValueError(f"Engine must be a non-empty string, got: {engine!r}")
        return f"{base}[{engine.strip()}]"

    return base


def clean_component_names(components: list[str]) -> list[str]:
    """
    Extract base component names from a list, removing engine information.

    Args:
        components: List of component names (some may have engine info)

    Returns:
        List of base component names

    Examples:
        clean_component_names(['redis', 'database[sqlite]']) -> ['redis', 'database']
    """
    return [extract_base_component_name(comp) for comp in components]


def restore_engine_info(
    resolved_components: list[str], original_components: list[str]
) -> list[str]:
    """
    Restore engine information from original components to resolved components.

    This function matches resolved base component names with their original
    engine-specific versions and restores the engine information.

    Args:
        resolved_components: List of resolved base component names
        original_components: List of original components with engine info

    Returns:
        List with engine information restored where applicable

    Examples:
        resolved = ['redis', 'database', 'scheduler']
        original = ['database[sqlite]', 'scheduler']
        restore_engine_info(resolved, original)
        -> ['redis', 'database[sqlite]', 'scheduler']
    """
    # Build mapping of base names to original components with engine info
    engine_mapping: dict[str, str] = {}
    for orig in original_components:
        base_name = extract_base_component_name(orig)
        if base_name != orig:  # Has engine info
            engine_mapping[base_name] = orig

    # Restore engine info where available
    result = []
    for comp in resolved_components:
        if comp in engine_mapping:
            result.append(engine_mapping[comp])
        else:
            result.append(comp)

    return result


def find_components_with_engine(components: list[str], base_name: str) -> list[str]:
    """
    Find all components that match a base name (with or without engine info).

    Args:
        components: List of component names to search
        base_name: Base component name to match

    Returns:
        List of matching components

    Examples:
        components = ['redis', 'database[sqlite]', 'database[postgres]', 'scheduler']
        find_components_with_engine(components, 'database')
        -> ['database[sqlite]', 'database[postgres]']
    """
    matches = []
    for comp in components:
        if extract_base_component_name(comp) == base_name:
            matches.append(comp)
    return matches


def has_engine_info(component: str) -> bool:
    """
    Check if a component name includes engine information.

    Args:
        component: Component name to check

    Returns:
        True if component has engine info, False otherwise

    Examples:
        has_engine_info('database[sqlite]') -> True
        has_engine_info('scheduler') -> False
    """
    return extract_engine_info(component) is not None
