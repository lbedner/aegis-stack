"""
RAG context models for AI chat integration.

This module provides data structures for managing RAG context injection
into AI chat conversations.
"""

from typing import Any

from app.services.rag.models import SearchResult
from pydantic import BaseModel, Field


class RAGContext(BaseModel):
    """
    Context from RAG search for injection into AI prompts.

    Holds search results and provides formatting methods for prompt injection
    and source citation display.
    """

    query: str = Field(..., description="Original search query")
    collection: str = Field(..., description="Collection that was searched")
    results: list[SearchResult] = Field(
        default_factory=list,
        description="Search results from RAG",
    )

    def format_for_prompt(self, include_metadata: bool = True) -> str:
        """
        Format RAG results for injection into system prompt.

        Args:
            include_metadata: Whether to include file paths and metadata

        Returns:
            Formatted markdown string for prompt injection
        """
        if not self.results:
            return ""

        context_parts = ["## Relevant Code Context", ""]

        for i, result in enumerate(self.results, 1):
            # Header with source info
            if include_metadata:
                file_name = result.metadata.get("file_name", "Unknown")
                start_line = result.metadata.get("start_line")
                end_line = result.metadata.get("end_line")

                # Build location info: prefer line numbers, fall back to chunk index
                if start_line and end_line:
                    location_info = f" (lines {start_line}-{end_line})"
                elif "chunk_index" in result.metadata:
                    location_info = f" (chunk {result.metadata['chunk_index']})"
                else:
                    location_info = ""

                context_parts.append(f"### [{i}] {file_name}{location_info}")

                # Add source path if available
                source = result.metadata.get("source", "")
                if source:
                    context_parts.append(f"*Source: {source}*")
            else:
                context_parts.append(f"### Context {i}")

            # Content with syntax highlighting
            lang = self._get_language_hint(result.metadata.get("extension", ""))
            context_parts.append(f"```{lang}")
            context_parts.append(result.content)
            context_parts.append("```")
            context_parts.append("")

        return "\n".join(context_parts)

    def format_sources_footer(self) -> str:
        """
        Format sources as footer references for display after AI response.

        Returns:
            Formatted markdown string with source citations
        """
        if not self.results:
            return ""

        lines = ["", "---", "**Sources:**"]

        for i, result in enumerate(self.results, 1):
            file_name = result.metadata.get("file_name", "Unknown")
            start_line = result.metadata.get("start_line")
            end_line = result.metadata.get("end_line")
            score = result.score

            # Build location info: prefer line numbers, fall back to chunk index
            if start_line and end_line:
                location = f"lines {start_line}-{end_line}"
            else:
                chunk_idx = result.metadata.get("chunk_index", 0)
                location = f"chunk {chunk_idx}"

            lines.append(f"[{i}] `{file_name}` ({location}) - score: {score:.2f}")

        return "\n".join(lines)

    def to_metadata(self) -> list[dict[str, Any]]:
        """
        Convert RAG context to metadata format for storage in conversation.

        Returns:
            List of source metadata dictionaries
        """
        return [
            {
                "file": result.metadata.get("file_name", "Unknown"),
                "source": result.metadata.get("source", "Unknown"),
                "chunk_index": result.metadata.get("chunk_index", 0),
                "start_line": result.metadata.get("start_line"),
                "end_line": result.metadata.get("end_line"),
                "score": result.score,
            }
            for result in self.results
        ]

    @staticmethod
    def _get_language_hint(extension: str) -> str:
        """Get syntax highlighting language hint from file extension."""
        lang_map = {
            ".py": "python",
            ".js": "javascript",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".jsx": "javascript",
            ".java": "java",
            ".go": "go",
            ".rs": "rust",
            ".rb": "ruby",
            ".php": "php",
            ".c": "c",
            ".cpp": "cpp",
            ".h": "c",
            ".hpp": "cpp",
            ".cs": "csharp",
            ".swift": "swift",
            ".kt": "kotlin",
            ".scala": "scala",
            ".json": "json",
            ".yaml": "yaml",
            ".yml": "yaml",
            ".toml": "toml",
            ".xml": "xml",
            ".sql": "sql",
            ".md": "markdown",
            ".html": "html",
            ".css": "css",
            ".scss": "scss",
            ".sh": "bash",
            ".bash": "bash",
        }
        return lang_map.get(extension, "")


__all__ = ["RAGContext"]
