"""Extended Qdrant MCP Server with additional retrieval capabilities."""

import asyncio
import json
from typing import Annotated

from fastmcp import Context
from mcp_server_qdrant.mcp_server import QdrantMCPServer
from mcp_server_qdrant.settings import (
    EmbeddingProviderSettings,
    QdrantSettings,
    ToolSettings,
)
from pydantic import Field
from qdrant_client.models import FieldCondition, Filter, MatchValue


class ExtendedQdrantMCPServer(QdrantMCPServer):
    """Extended Qdrant MCP Server with additional tools for chunk retrieval and context expansion."""

    def setup_tools(self) -> None:
        """Register both base tools and extended tools."""
        # Register the base tools (qdrant-find, qdrant-store)
        super().setup_tools()

        # Register our extended tools
        self.register_extended_tools()

    def register_extended_tools(self) -> None:  # noqa: C901, PLR0915
        """Register additional tools for advanced retrieval operations."""

        async def get_chunk(
            ctx: Context,
            point_id: Annotated[str, Field(description="The UUID of the point to retrieve")],
        ) -> str:
            """
            Retrieve a specific chunk by its point ID.

            :param ctx: The context for the request.
            :param point_id: The UUID of the point to retrieve.
            :return: The chunk content with metadata.
            """
            await ctx.debug(f"Retrieving chunk with point_id: {point_id}")

            client = self.qdrant_connector._client

            points = await client.retrieve(
                collection_name=self.qdrant_settings.collection_name,
                ids=[point_id],
            )

            if not points:
                return f"<error>Point {point_id} not found</error>"

            point = points[0]
            content = point.payload.get("document", "")
            metadata = point.payload.get("metadata", {})
            metadata_str = json.dumps(metadata) if metadata else ""

            return (f"<chunk><point_id>{point_id}</point_id><content>{content}</content>"
                    f"<metadata>{metadata_str}</metadata></chunk>")

        async def expand_context(  # noqa: PLR0917
            ctx: Context,
            point_id: Annotated[str, Field(description="The UUID of the current chunk")],
            before: Annotated[
                int, Field(description="Number of chunks to retrieve before the current chunk"),
            ] = 1,
            after: Annotated[
                int, Field(description="Number of chunks to retrieve after the current chunk"),
            ] = 1,
        ) -> list[str]:
            """
            Expand context by retrieving adjacent chunks from the same document.

            :param ctx: The context for the request.
            :param point_id: The UUID of the current chunk.
            :param before: Number of chunks to retrieve before the current chunk (default: 1). Set to 0 to skip.
            :param after: Number of chunks to retrieve after the current chunk (default: 1). Set to 0 to skip.
            :return: List of adjacent chunks including the original, ordered by chunk_index.
            """
            await ctx.debug(f"Expanding context for point_id: {point_id} with before={before}, after={after}")

            client = self.qdrant_connector._client

            # Get the current chunk to find its document_id and chunk_index
            current_points = await client.retrieve(
                collection_name=self.qdrant_settings.collection_name,
                ids=[point_id],
            )

            if not current_points:
                return [f"<error>Point {point_id} not found</error>"]

            current = current_points[0]
            metadata = current.payload.get("metadata", {})
            document_id = metadata.get("id")
            chunk_index = metadata.get("chunk_index")
            total_chunks = metadata.get("total_chunks")

            if document_id is None or chunk_index is None:
                return [
                    "<error>Missing document_id or chunk_index in metadata. "
                    "This chunk may not support context expansion.</error>",
                ]

            # Calculate range
            start_index = max(0, chunk_index - before)
            end_index = min(
                total_chunks - 1 if total_chunks else chunk_index + after,
                chunk_index + after,
            )

            await ctx.debug(
                f"Searching for chunks {start_index} to {end_index} of document {document_id}",
            )

            # Search for all chunks in this range
            results = []
            for idx in range(start_index, end_index + 1):
                search_results = await client.scroll(
                    collection_name=self.qdrant_settings.collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(key="metadata.id", match=MatchValue(value=document_id)),
                            FieldCondition(key="metadata.chunk_index", match=MatchValue(value=idx)),
                        ],
                    ),
                    limit=1,
                )

                if search_results[0]:  # search_results is tuple (points, next_offset)
                    for point in search_results[0]:
                        content = point.payload.get("document", "")
                        metadata = point.payload.get("metadata", {})
                        metadata_str = json.dumps(metadata) if metadata else ""

                        results.append({
                            "point_id": point.id,
                            "content": content,
                            "metadata_str": metadata_str,
                            "chunk_index": idx,
                        })

            # Sort by chunk_index to maintain order
            results.sort(key=lambda x: x.get("chunk_index", 0))

            formatted_results = [
                f"Found {len(results)} chunks (indices {start_index} to {end_index}) from document {document_id}",
            ]

            for result in results:
                formatted_results.append(
                    f"<chunk><point_id>{result['point_id']}</point_id>"
                    f"<chunk_index>{result['chunk_index']}</chunk_index>"
                    f"<content>{result['content']}</content>"
                    f"<metadata>{result['metadata_str']}</metadata></chunk>",
                )

            return formatted_results

        async def get_document_chunks(
            ctx: Context,
            document_id: Annotated[
                str, Field(description="The document ID (32-char hex string from Obsidian Portal)"),
            ],
        ) -> list[str]:
            """
            Retrieve all chunks for a specific document.

            :param ctx: The context for the request.
            :param document_id: The document ID.
            :return: All chunks from the document, ordered by chunk_index.
            """
            await ctx.debug(f"Retrieving all chunks for document_id: {document_id}")

            client = self.qdrant_connector._client

            # Scroll through all points with matching document_id
            results = []
            offset = None

            while True:
                search_results, next_offset = await client.scroll(
                    collection_name=self.qdrant_settings.collection_name,
                    scroll_filter=Filter(
                        must=[
                            FieldCondition(key="metadata.id", match=MatchValue(value=document_id)),
                        ],
                    ),
                    limit=100,
                    offset=offset,
                )

                for point in search_results:
                    content = point.payload.get("document", "")
                    metadata = point.payload.get("metadata", {})

                    results.append({
                        "point_id": point.id,
                        "content": content,
                        "metadata": metadata,
                        "chunk_index": metadata.get("chunk_index", 0),
                    })

                if next_offset is None:
                    break
                offset = next_offset

            # Sort by chunk_index
            results.sort(key=lambda x: x.get("chunk_index", 0))

            formatted_results = [f"Found {len(results)} chunks for document {document_id}"]

            for result in results:
                metadata_str = json.dumps(result["metadata"]) if result["metadata"] else ""
                formatted_results.append(
                    f"<chunk><point_id>{result['point_id']}</point_id>"
                    f"<chunk_index>{result['chunk_index']}</chunk_index>"
                    f"<content>{result['content']}</content>"
                    f"<metadata>{metadata_str}</metadata></chunk>",
                )

            return formatted_results

        # Register the extended tools
        self.tool(get_chunk, name="qdrant-get-chunk", description="Retrieve a specific chunk by its point ID")
        self.tool(
            expand_context,
            name="qdrant-expand-context",
            description="Expand context by retrieving adjacent chunks from the same document",
        )
        self.tool(
            get_document_chunks,
            name="qdrant-get-document-chunks",
            description="Retrieve all chunks for a specific document",
        )


# Create the server instance
mcp = ExtendedQdrantMCPServer(
    tool_settings=ToolSettings(),
    qdrant_settings=QdrantSettings(),
    embedding_provider_settings=EmbeddingProviderSettings(),
    name="mcp-server-qdrant-extended",
    instructions="""
        Extended Qdrant MCP server with additional retrieval capabilities.
        Provides semantic search, storage, and advanced operations like:
        - Fetching specific chunks by point ID
        - Expanding context by retrieving adjacent chunks
        - Retrieving all chunks from a document
    """,
)

if __name__ == "__main__":
    asyncio.run(mcp.run_async(transport="streamable-http", port=8000))
