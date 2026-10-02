"""
RAG service configuration.

Configuration management for RAG service including chunking settings,
vector store paths, and search parameters.
"""

from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, Field

from app.core.secrets import Secret, probe

if TYPE_CHECKING:
    from app.core.config import Settings


async def _verify_hf_token(token: str) -> None:
    """Hugging Face's whoami answers 401 for a token it does not know."""
    await probe(
        "https://huggingface.co/api/whoami-v2",
        headers={"Authorization": f"Bearer {token}"},
    )


# What RAG reads (``app.core.secrets``): the embedding-model download from
# Hugging Face authenticates with this when it is set.
SECRETS = (
    Secret(
        "HF_TOKEN",
        owner="RAG (Hugging Face)",
        label="Hugging Face token",
        verify=_verify_hf_token,
    ),
)


class RAGServiceConfig(BaseModel):
    """
    RAG service configuration that integrates with main app settings.

    Provides chunking, vector store, and search configuration.
    """

    enabled: bool = True
    persist_directory: str = Field(
        default="./data/chromadb",
        description="Directory for ChromaDB persistence",
    )
    embedding_provider: str = Field(
        default="sentence-transformers",
        description="Embedding provider: 'sentence-transformers' or 'openai'",
    )
    embedding_model: str = Field(
        default="BAAI/bge-small-en-v1.5",
        description="Embedding model name for the selected provider",
    )
    model_cache_dir: str | None = Field(
        default=None,
        description="Directory for model cache (None = system default)",
    )
    openai_api_key: str | None = Field(
        default=None,
        description="OpenAI API key for embeddings (if using OpenAI provider)",
    )
    chunk_size: int = Field(
        default=2000,
        gt=0,
        le=10000,
        description="Maximum chunk size in characters",
    )
    chunk_overlap: int = Field(
        default=400,
        ge=0,
        le=1000,
        description="Overlap between chunks in characters",
    )
    default_top_k: int = Field(
        default=15,
        gt=0,
        le=50,
        description="Default number of search results",
    )
    default_extensions: list[str] = Field(
        default=[".py", ".js", ".ts", ".tsx", ".md", ".yaml", ".yml", ".json", ".toml"],
        description="Default file extensions to include",
    )

    @classmethod
    def from_settings(cls, settings: "Settings") -> Self:
        """Create configuration from main application settings."""
        return cls(
            enabled=settings.RAG_ENABLED,
            persist_directory=settings.RAG_PERSIST_DIRECTORY,
            embedding_provider=settings.RAG_EMBEDDING_PROVIDER,
            embedding_model=settings.RAG_EMBEDDING_MODEL,
            model_cache_dir=settings.RAG_MODEL_CACHE_DIR,
            openai_api_key=settings.OPENAI_API_KEY,
            chunk_size=settings.RAG_CHUNK_SIZE,
            chunk_overlap=settings.RAG_CHUNK_OVERLAP,
            default_top_k=settings.RAG_DEFAULT_TOP_K,
        )

    def validate_configuration(self) -> list[str]:
        """
        Validate RAG service configuration and return list of issues.

        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []

        if not self.enabled:
            return errors

        if self.chunk_overlap >= self.chunk_size:
            errors.append(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )

        return errors


def get_rag_config(settings: "Settings") -> RAGServiceConfig:
    """Get RAG service configuration from application settings."""
    return RAGServiceConfig.from_settings(settings)
