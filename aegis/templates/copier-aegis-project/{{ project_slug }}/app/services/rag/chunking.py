"""
Document chunking utilities for RAG service.

Provides text splitting with configurable chunk sizes and overlap,
using a recursive character text splitting strategy with language-aware
separators for code files.
"""

import asyncio

from app.core.log import logger

from .models import Document

# Base separators for general text (in order of preference)
BASE_SEPARATORS = [
    "\n\n\n",  # Triple newline (major sections)
    "\n\n",  # Double newline (paragraphs)
    "\n",  # Single newline
    ". ",  # Sentence end
    "? ",  # Question end
    "! ",  # Exclamation end
    "; ",  # Semicolon
    ", ",  # Clause
    " ",  # Word
    "",  # Character (last resort)
]

# Python-specific separators (split on function/class boundaries first)
PYTHON_SEPARATORS = [
    "\n\nclass ",  # Class definitions (double newline)
    "\n\nasync def ",  # Async functions (double newline)
    "\n\ndef ",  # Functions (double newline)
    "\nclass ",  # Class (single newline)
    "\nasync def ",  # Async function (single newline)
    "\ndef ",  # Function (single newline)
    "\n\n",  # Double newline (paragraphs/blocks)
    "\n",  # Single newline
    ". ",  # Sentence
    " ",  # Word
    "",  # Character
]

# JavaScript/TypeScript separators
JS_SEPARATORS = [
    "\n\nexport class ",
    "\n\nexport function ",
    "\n\nexport async function ",
    "\n\nexport const ",
    "\n\nclass ",
    "\n\nfunction ",
    "\n\nasync function ",
    "\n\nconst ",
    "\nexport class ",
    "\nexport function ",
    "\nexport const ",
    "\nclass ",
    "\nfunction ",
    "\nconst ",
    "\n\n",
    "\n",
    " ",
    "",
]

# Markdown separators (split on headers)
MARKDOWN_SEPARATORS = [
    "\n## ",  # H2 headers
    "\n### ",  # H3 headers
    "\n#### ",  # H4 headers
    "\n# ",  # H1 headers
    "\n\n",  # Paragraphs
    "\n",  # Lines
    ". ",  # Sentences
    " ",  # Words
    "",  # Characters
]

# YAML/TOML separators (split on top-level keys)
CONFIG_SEPARATORS = [
    "\n\n",  # Double newline (major sections)
    "\n",  # Single newline
    " ",  # Word
    "",  # Character
]

# Language to separator mapping
LANGUAGE_SEPARATORS: dict[str, list[str]] = {
    "python": PYTHON_SEPARATORS,
    "javascript": JS_SEPARATORS,
    "typescript": JS_SEPARATORS,
    "markdown": MARKDOWN_SEPARATORS,
    "yaml": CONFIG_SEPARATORS,
    "toml": CONFIG_SEPARATORS,
    "json": CONFIG_SEPARATORS,
}

# Per-source chunking presets: strategy name -> (chunk_size, chunk_overlap).
# ``knowledge_base_source.chunking_strategy`` selects one of these; the
# chunker's language-aware separators apply within any preset.
CHUNKING_STRATEGIES: dict[str, tuple[int, int]] = {
    "paragraph": (2000, 400),  # default: prose and mixed documents
    "sentence": (600, 100),  # fine-grained: FAQ / short-answer content
    "fixed": (1000, 100),  # predictable windows for uniform content
    "code": (1500, 200),  # source files; separators do the real work
}


def chunk_params_for_strategy(strategy: str) -> tuple[int, int]:
    """Resolve a strategy name to (chunk_size, chunk_overlap).

    Unknown names fall back to ``paragraph`` with a warning: a stale
    source row must not break ingestion.
    """
    params = CHUNKING_STRATEGIES.get(strategy)
    if params is None:
        logger.warning(
            "Unknown chunking strategy; using paragraph", strategy=strategy
        )
        return CHUNKING_STRATEGIES["paragraph"]
    return params


class DocumentChunker:
    """Splits documents into smaller chunks for indexing."""

    # Default separators for unknown languages
    SEPARATORS = BASE_SEPARATORS

    def __init__(
        self,
        chunk_size: int = 2000,
        chunk_overlap: int = 400,
        min_chunk_size: int = 50,
    ):
        """
        Initialize document chunker.

        Args:
            chunk_size: Maximum chunk size in characters
            chunk_overlap: Overlap between chunks in characters
            min_chunk_size: Minimum chunk size to keep (smaller chunks filtered out)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size

    async def chunk(
        self,
        documents: list[Document],
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
    ) -> list[Document]:
        """
        Split documents into chunks.

        Args:
            documents: Documents to split
            chunk_size: Override default chunk size
            chunk_overlap: Override default overlap

        Returns:
            list[Document]: Chunked documents with preserved metadata
        """
        size = chunk_size or self.chunk_size
        overlap = chunk_overlap or self.chunk_overlap

        # Run chunking in thread pool (CPU-bound)
        chunks = await asyncio.to_thread(
            self._chunk_documents_sync, documents, size, overlap
        )

        logger.debug(
            "document_chunker.chunk",
            input_docs=len(documents),
            output_chunks=len(chunks),
            chunk_size=size,
            overlap=overlap,
        )

        return chunks

    def _get_separators(self, language: str | None) -> list[str]:
        """
        Get separators for a specific language.

        Args:
            language: Programming language or file type

        Returns:
            List of separators in order of preference
        """
        if language and language.lower() in LANGUAGE_SEPARATORS:
            return LANGUAGE_SEPARATORS[language.lower()]
        return self.SEPARATORS

    def _chunk_documents_sync(
        self,
        documents: list[Document],
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[Document]:
        """Synchronous chunking implementation with line tracking."""
        chunks: list[Document] = []

        for doc in documents:
            content = doc.content
            language = doc.metadata.get("language")

            # Get language-specific separators
            separators = self._get_separators(language)

            # Split with line tracking
            doc_chunks = self._split_text_with_lines(
                content, chunk_size, chunk_overlap, separators
            )

            # Filter out low-quality chunks and track valid ones
            valid_chunks: list[tuple[str, int, int]] = []
            for chunk_text, start_line, end_line in doc_chunks:
                if not self._is_low_quality_chunk(chunk_text, language):
                    valid_chunks.append((chunk_text, start_line, end_line))

            for i, (chunk_text, start_line, end_line) in enumerate(valid_chunks):
                # Prepend filename to content for better searchability
                # This ensures the filename gets embedded and is searchable
                file_name = doc.metadata.get("file_name", "")
                if file_name:
                    content_with_context = f"File: {file_name}\n\n{chunk_text}"
                else:
                    content_with_context = chunk_text

                chunk = Document(
                    content=content_with_context,
                    metadata={
                        **doc.metadata,
                        "chunk_index": i,
                        "total_chunks": len(valid_chunks),
                        "chunk_size": len(content_with_context),
                        "start_line": start_line,
                        "end_line": end_line,
                    },
                )
                chunks.append(chunk)

        return chunks

    def _is_low_quality_chunk(self, content: str, language: str | None) -> bool:
        """
        Check if a chunk is low-quality and should be filtered out.

        Filters:
        - Chunks smaller than min_chunk_size characters
        - Chunks that are mostly import statements (for code files)

        Args:
            content: The chunk content
            language: The programming language (if known)

        Returns:
            True if the chunk should be filtered out
        """
        # Filter very small chunks (use configurable min_chunk_size)
        if len(content.strip()) < self.min_chunk_size:
            return True

        # For Python files, filter chunks that are mostly imports
        if language and language.lower() == "python":
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            if not lines:
                return True

            import_lines = sum(
                1
                for line in lines
                if line.startswith(("import ", "from ")) or line.startswith("#")
            )

            # Filter if more than 70% of lines are imports/comments
            if len(lines) > 0 and (import_lines / len(lines)) > 0.7:
                return True

        # For JS/TS files, filter chunks that are mostly imports
        if language and language.lower() in ("javascript", "typescript"):
            lines = [line.strip() for line in content.split("\n") if line.strip()]
            if not lines:
                return True

            import_lines = sum(
                1
                for line in lines
                if line.startswith(("import ", "export {", "export *", "require("))
                or line.startswith("//")
            )

            # Filter if more than 70% of lines are imports/comments
            if len(lines) > 0 and (import_lines / len(lines)) > 0.7:
                return True

        return False

    def _split_text_with_lines(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        separators: list[str],
    ) -> list[tuple[str, int, int]]:
        """
        Split text into chunks while tracking line numbers.

        Args:
            text: Text to split
            chunk_size: Maximum chunk size
            chunk_overlap: Overlap between chunks
            separators: Separators to use for splitting

        Returns:
            List of (chunk_text, start_line, end_line) tuples
        """
        # Get raw chunks first
        raw_chunks = self._split_text(text, chunk_size, chunk_overlap, separators)

        # Calculate line numbers for each chunk
        result: list[tuple[str, int, int]] = []
        current_pos = 0
        last_chunk_end = 0

        for chunk in raw_chunks:
            # Find where this chunk starts in the original text
            chunk_start = text.find(chunk, current_pos)
            if chunk_start == -1:
                # Fallback: use last known chunk end to avoid incorrect line mapping
                logger.warning(
                    "chunker.chunk_not_found",
                    chunk_preview=chunk[:50] if len(chunk) > 50 else chunk,
                )
                chunk_start = last_chunk_end

            chunk_end = chunk_start + len(chunk)

            # Calculate line numbers (1-indexed)
            start_line = text[:chunk_start].count("\n") + 1
            newline_count_to_end = text[:chunk_end].count("\n")
            if chunk.endswith("\n"):
                # When chunk ends with a newline, the last character is the line break
                # so the end line is exactly the number of newlines up to chunk_end
                end_line = newline_count_to_end
            else:
                end_line = newline_count_to_end + 1

            result.append((chunk, start_line, end_line))

            # Move position forward (account for overlap)
            current_pos = max(current_pos, chunk_start + 1)
            last_chunk_end = chunk_end

        return result

    def _split_text(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
        separators: list[str],
        depth: int = 0,
    ) -> list[str]:
        """Recursively split text into chunks using separators."""
        # If text fits in one chunk, return as-is
        if len(text) <= chunk_size:
            return [text] if text.strip() else []

        # Prevent infinite recursion - fall back to length-based splitting
        if depth > 10:
            return self._split_by_length(text, chunk_size, chunk_overlap)

        # Find best separator
        for separator in separators:
            if separator and separator in text:
                return self._split_with_separator(
                    text, separator, chunk_size, chunk_overlap, separators, depth
                )

        # No separator found, split by fixed length
        return self._split_by_length(text, chunk_size, chunk_overlap)

    def _split_with_separator(
        self,
        text: str,
        separator: str,
        chunk_size: int,
        chunk_overlap: int,
        separators: list[str],
        depth: int = 0,
    ) -> list[str]:
        """Split text using a separator."""
        splits = text.split(separator)
        chunks: list[str] = []
        current_chunk = ""

        for split in splits:
            # Check if adding this split would exceed chunk size
            potential_chunk = (
                current_chunk + separator + split if current_chunk else split
            )

            if len(potential_chunk) <= chunk_size:
                current_chunk = potential_chunk
            else:
                # Save current chunk if non-empty
                if current_chunk.strip():
                    chunks.append(current_chunk)

                # Start new chunk with overlap from previous
                if chunk_overlap > 0 and current_chunk:
                    # Get overlap from end of current chunk
                    overlap_text = current_chunk[-chunk_overlap:]
                    current_chunk = overlap_text + separator + split
                else:
                    current_chunk = split

                # If single split is too large, recursively split it
                if len(current_chunk) > chunk_size:
                    sub_chunks = self._split_text(
                        current_chunk, chunk_size, chunk_overlap, separators, depth + 1
                    )
                    if sub_chunks:
                        chunks.extend(sub_chunks[:-1])
                        current_chunk = sub_chunks[-1]
                    else:
                        current_chunk = ""

        # Don't forget the last chunk
        if current_chunk.strip():
            chunks.append(current_chunk)

        return chunks

    def _split_by_length(
        self,
        text: str,
        chunk_size: int,
        chunk_overlap: int,
    ) -> list[str]:
        """Split text by fixed length (last resort)."""
        chunks: list[str] = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            if chunk.strip():
                chunks.append(chunk)
            start = end - chunk_overlap

            # Safety: prevent infinite loop
            if start <= 0 and end >= len(text):
                break

        return chunks


def estimate_chunks(content_length: int, chunk_size: int, chunk_overlap: int) -> int:
    """
    Estimate the number of chunks for a given content length.

    Args:
        content_length: Length of content in characters
        chunk_size: Chunk size
        chunk_overlap: Overlap between chunks

    Returns:
        Estimated number of chunks
    """
    if content_length <= chunk_size:
        return 1

    effective_size = chunk_size - chunk_overlap
    if effective_size <= 0:
        return 1

    return max(1, (content_length - chunk_overlap) // effective_size + 1)
