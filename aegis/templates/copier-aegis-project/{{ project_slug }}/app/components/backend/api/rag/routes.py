"""
RAG service API router.

FastAPI router for RAG endpoints implementing document indexing,
search, and collection management.
"""

from typing import Any

from app.core.config import settings
from app.services.rag.config import get_rag_config
from app.services.rag.service import (
    IndexingError,
    LoaderError,
    RAGService,
    SearchError,
)
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/rag", tags=["rag"])

# Initialize RAG service
_rag_config = get_rag_config(settings)
rag_service = RAGService(_rag_config)


# Request/Response models
class IndexRequest(BaseModel):
    """Request model for indexing documents."""

    path: str = Field(..., description="File or directory path to index")
    collection_name: str = Field(..., description="Collection name to store documents")
    extensions: list[str] | None = Field(
        default=None, description="File extensions to include (e.g., ['.py', '.md'])"
    )
    exclude_patterns: list[str] | None = Field(
        default=None, description="Glob patterns to exclude"
    )


class IndexResponse(BaseModel):
    """Response model for indexing operations."""

    collection_name: str
    documents_added: int
    total_documents: int
    duration_ms: float


class SearchRequest(BaseModel):
    """Request model for search queries."""

    query: str = Field(..., description="Search query text")
    collection_name: str = Field(..., description="Collection to search")
    top_k: int = Field(default=5, ge=1, le=50, description="Number of results")
    filter_metadata: dict[str, Any] | None = Field(
        default=None, description="Optional metadata filter"
    )


class SearchResultItem(BaseModel):
    """A single search result."""

    content: str
    metadata: dict[str, Any]
    score: float
    rank: int


class SearchResponse(BaseModel):
    """Response model for search queries."""

    query: str
    collection_name: str
    results: list[SearchResultItem]
    result_count: int


class CollectionInfoResponse(BaseModel):
    """Collection information response."""

    name: str
    count: int  # Total chunks
    doc_count: int = 0  # Unique documents/files
    metadata: dict[str, Any]


class IndexedFileResponse(BaseModel):
    """Response model for indexed file information."""

    source: str
    chunks: int


class CollectionFilesResponse(BaseModel):
    """Response model for collection files list."""

    collection_name: str
    files: list[IndexedFileResponse]
    total_files: int
    total_chunks: int


@router.post("/index", response_model=IndexResponse)
async def index_documents(request: IndexRequest) -> IndexResponse:
    """
    Index documents from a path into a collection.

    Loads files from the specified path, chunks them, and indexes
    them into the ChromaDB collection.

    Args:
        request: Index request with path and collection name

    Returns:
        IndexResponse: Statistics about the indexing operation

    Raises:
        HTTPException: If indexing fails
    """
    try:
        stats = await rag_service.refresh_index(
            path=request.path,
            collection_name=request.collection_name,
            extensions=request.extensions,
            exclude_patterns=request.exclude_patterns,
        )

        return IndexResponse(
            collection_name=stats.collection_name,
            documents_added=stats.documents_added,
            total_documents=stats.total_documents,
            duration_ms=stats.duration_ms,
        )

    except LoaderError as e:
        raise HTTPException(status_code=400, detail=f"Failed to load documents: {e}")
    except IndexingError as e:
        raise HTTPException(status_code=500, detail=f"Indexing failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.post("/search", response_model=SearchResponse)
async def search_documents(request: SearchRequest) -> SearchResponse:
    """
    Search for documents in a collection.

    Performs semantic search using the query text against the
    specified collection.

    Args:
        request: Search request with query and collection

    Returns:
        SearchResponse: Ranked search results

    Raises:
        HTTPException: If search fails
    """
    try:
        results = await rag_service.search(
            query=request.query,
            collection_name=request.collection_name,
            top_k=request.top_k,
            filter_metadata=request.filter_metadata,
        )

        return SearchResponse(
            query=request.query,
            collection_name=request.collection_name,
            results=[
                SearchResultItem(
                    content=r.content,
                    metadata=r.metadata,
                    score=r.score,
                    rank=r.rank,
                )
                for r in results
            ],
            result_count=len(results),
        )

    except SearchError as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")


@router.get("/collections", response_model=list[str])
async def list_collections() -> list[str]:
    """
    List all available collections.

    Returns:
        List of collection names
    """
    try:
        return await rag_service.list_collections()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list collections: {e}")


@router.get("/collections/{collection_name}", response_model=CollectionInfoResponse)
async def get_collection_info(collection_name: str) -> CollectionInfoResponse:
    """
    Get information about a specific collection.

    Args:
        collection_name: Name of the collection

    Returns:
        Collection information including document count

    Raises:
        HTTPException: If collection not found
    """
    try:
        stats = await rag_service.get_collection_stats(collection_name)
        if not stats:
            raise HTTPException(
                status_code=404, detail=f"Collection '{collection_name}' not found"
            )

        return CollectionInfoResponse(
            name=stats["name"],
            count=stats["count"],
            doc_count=stats.get("doc_count", 0),
            metadata=stats.get("metadata", {}),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get collection info: {e}"
        )


@router.get(
    "/collections/{collection_name}/files", response_model=CollectionFilesResponse
)
async def get_collection_files(collection_name: str) -> CollectionFilesResponse:
    """
    Get list of files indexed in a collection.

    Args:
        collection_name: Name of the collection

    Returns:
        List of files with chunk counts

    Raises:
        HTTPException: If collection not found
    """
    try:
        # Check collection exists first
        stats = await rag_service.get_collection_stats(collection_name)
        if not stats:
            raise HTTPException(
                status_code=404, detail=f"Collection '{collection_name}' not found"
            )

        files = await rag_service.list_files(collection_name)
        total_chunks = sum(f.chunks for f in files)

        return CollectionFilesResponse(
            collection_name=collection_name,
            files=[
                IndexedFileResponse(source=f.source, chunks=f.chunks) for f in files
            ],
            total_files=len(files),
            total_chunks=total_chunks,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get collection files: {e}"
        )


@router.delete("/collections/{collection_name}")
async def delete_collection(collection_name: str) -> dict[str, Any]:
    """
    Delete a collection.

    Args:
        collection_name: Name of the collection to delete

    Returns:
        Deletion confirmation

    Raises:
        HTTPException: If deletion fails
    """
    try:
        deleted = await rag_service.delete_collection(collection_name)
        if not deleted:
            raise HTTPException(
                status_code=404, detail=f"Collection '{collection_name}' not found"
            )

        return {"deleted": True, "collection_name": collection_name}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete collection: {e}")


@router.get("/health")
async def rag_health() -> dict[str, Any]:
    """
    RAG service health endpoint.

    Returns health status including configuration and collection count.
    """
    try:
        status = rag_service.get_service_status()
        validation_errors = rag_service.validate_service()
        collections = await rag_service.list_collections()

        return {
            "service": "rag",
            "status": "healthy" if not validation_errors else "unhealthy",
            "enabled": status.get("enabled", False),
            "persist_directory": status.get("persist_directory"),
            "embedding_provider": status.get("embedding_provider"),
            "embedding_model": status.get("embedding_model"),
            "chunk_size": status.get("chunk_size"),
            "chunk_overlap": status.get("chunk_overlap"),
            "default_top_k": status.get("default_top_k"),
            "last_activity": status.get("last_activity"),
            "collection_count": len(collections),
            "validation_errors": validation_errors,
        }

    except Exception as e:
        return {
            "service": "rag",
            "status": "error",
            "error": str(e),
        }
