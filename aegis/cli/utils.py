"""
CLI utility functions.

This module contains utility functions used by CLI commands for
component detection, dependency expansion, and other common tasks.
"""

from ..constants import AnswerKeys, ComponentNames, StorageBackends, WorkerBackends
from ..core.component_utils import (
    clean_component_names,
    extract_base_component_name,
    extract_engine_info,
)


def detect_scheduler_backend(components: list[str]) -> str:
    """
    Detect scheduler backend from component list.

    Args:
        components: List of component names, possibly including scheduler[backend]

    Returns:
        Backend name: "memory", "sqlite", or "postgres"
    """
    for component in components:
        base_name = extract_base_component_name(component)
        if base_name == ComponentNames.SCHEDULER:
            engine = extract_engine_info(component)
            if engine:
                # Direct scheduler[backend] syntax
                return engine
            else:
                # Check if database is also present (legacy detection)
                clean_names = clean_component_names(components)
                if ComponentNames.DATABASE in clean_names:
                    # Use the database engine if specified, otherwise sqlite
                    for comp in components:
                        if extract_base_component_name(comp) == ComponentNames.DATABASE:
                            db_engine = extract_engine_info(comp)
                            if db_engine:
                                return db_engine
                    return StorageBackends.SQLITE  # Default database backend
    return StorageBackends.MEMORY  # Default to memory-only


def detect_worker_backend(components: list[str]) -> str:
    """
    Detect worker backend from component list.

    Args:
        components: List of component names, possibly including worker[backend]

    Returns:
        Backend name: "arq", "taskiq", or "dramatiq"
    """
    for component in components:
        base_name = extract_base_component_name(component)
        if base_name == ComponentNames.WORKER:
            engine = extract_engine_info(component)
            if engine:
                return engine
    return WorkerBackends.ARQ  # Default to arq


def detect_ai_backend(services: list[str]) -> str:
    """
    Detect AI backend from service list.

    Args:
        services: List of service names, possibly including ai[backend]

    Returns:
        Backend name: "memory" or "sqlite"
    """
    for service in services:
        base_name = extract_base_component_name(service)
        if base_name == AnswerKeys.SERVICE_AI:
            engine = extract_engine_info(service)
            if engine:
                return engine
    return StorageBackends.MEMORY  # Default to memory
