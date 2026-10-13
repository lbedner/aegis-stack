"""
RAG (Retrieval-Augmented Generation) service module.

Provides document indexing and semantic search functionality for
codebase question answering using ChromaDB with built-in embeddings.
"""

import os

from app.core.constants import ServiceName

# Suppress HuggingFace tokenizer parallelism warnings.
# IMPORTANT: This must be set before any HuggingFace tokenizers (e.g., via
# sentence-transformers or transformers) are imported. This module should be
# imported early in the application startup to ensure this takes effect.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

# Part of AI, not a service of its own (``ownership``).
PART_OF = ServiceName.AI

__all__ = []
