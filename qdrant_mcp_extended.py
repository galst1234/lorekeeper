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

# ---------------------------------------------------------------------------
# Tool descriptions & server instructions
# ---------------------------------------------------------------------------

TOOL_FIND_DESCRIPTION = (
    "Semantic search over D&D campaign lore stored in Qdrant (session summaries, "
    "wiki pages, characters). Use this as the FIRST step when answering any campaign "
    "question.\n\n"
    "Returns <entry> elements each containing:\n"
    "  - <content>: the matching text chunk\n"
    "  - <metadata>: JSON with these fields:\n"
    "      id           - document ID (32-char hex string, used by other tools)\n"
    "      type         - WikiPage | Post | Character\n"
    "      chunk_index  - position of this chunk within the document\n"
    "      total_chunks - how many chunks the document has\n"
    "      title        - (WikiPage only) page title\n"
    "      name         - (Character only) character name\n"
    "      source_url, tags, gm_only, created_at, updated_at\n\n"
    "After reviewing results, use the metadata to chain into other tools:\n"
    "  - qdrant-expand-context(document_id=metadata.id, chunk_index=metadata.chunk_index) "
    "to fetch surrounding chunks from the same document.\n"
    "  - qdrant-get-document-chunks(document_id=metadata.id) to fetch the entire document."
)

TOOL_GET_CHUNK_DESCRIPTION = (
    "Fetch a single chunk by its Qdrant point UUID. Use this when you already have a "
    "point_id from a previous qdrant-expand-context or qdrant-get-document-chunks "
    "result.\n\n"
    "NOTE: qdrant-find results do NOT include point_ids, so you cannot chain "
    "qdrant-find -> qdrant-get-chunk directly. Use qdrant-expand-context or "
    "qdrant-get-document-chunks first to obtain point_ids."
)

TOOL_EXPAND_CONTEXT_DESCRIPTION = (
    "Retrieve adjacent chunks from the same document to expand context around a "
    "known chunk. Use this AFTER qdrant-find when a result is relevant but you "
    "need more surrounding text.\n\n"
    "Typical workflow:\n"
    "  1. qdrant-find -> get matching chunks with metadata\n"
    "  2. Pick a relevant result and note its metadata.id and metadata.chunk_index\n"
    "  3. qdrant-expand-context(document_id=<metadata.id>, chunk_index=<metadata.chunk_index>, "
    "before=N, after=N)\n\n"
    "Parameters:\n"
    "  - document_id: the 'id' field from metadata (32-char hex string)\n"
    "  - chunk_index: the 'chunk_index' field from metadata\n"
    "  - before: number of preceding chunks to fetch (default 1, set 0 to skip)\n"
    "  - after: number of following chunks to fetch (default 1, set 0 to skip)\n\n"
    "This is more efficient than multiple qdrant-find queries when you need "
    "contiguous text from a single document."
)

TOOL_GET_DOCUMENT_CHUNKS_DESCRIPTION = (
    "Retrieve ALL chunks for an entire document, ordered by chunk_index. Use this "
    "when you need the complete text of a document (e.g. a full wiki page or "
    "character bio).\n\n"
    "Parameters:\n"
    "  - document_id: the 'id' field from metadata (32-char hex string). This is "
    "the document's own ID, NOT the campaign ID.\n\n"
    "Prefer qdrant-expand-context when you only need a few neighboring chunks - "
    "this tool fetches everything and may return a large amount of text."
)

SERVER_INSTRUCTIONS = (
    "Retrieval workflow for campaign lore:\n"
    "1. Start with qdrant-find to semantically search for relevant chunks.\n"
    "2. Inspect the metadata of each result (especially id, chunk_index, type).\n"
    "3. Use qdrant-expand-context to fetch surrounding chunks when a result is "
    "relevant but incomplete.\n"
    "4. Use qdrant-get-document-chunks to retrieve a full document when needed.\n"
    "5. Cross-reference information via additional qdrant-find queries with "
    "different search terms.\n"
    "Always gather sufficient context before answering."
)


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
            document_id: Annotated[str, Field(description="The document ID from metadata (32-char hex string)")],
            chunk_index: Annotated[int, Field(description="The chunk index of the current chunk")],
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
            :param document_id: The document ID from the chunk's metadata.
            :param chunk_index: The chunk index of the current chunk.
            :param before: Number of chunks to retrieve before the current chunk (default: 1). Set to 0 to skip.
            :param after: Number of chunks to retrieve after the current chunk (default: 1). Set to 0 to skip.
            :return: List of adjacent chunks including the original, ordered by chunk_index.
            """
            await ctx.debug(f"Expanding context for document_id: {document_id}, chunk_index: {chunk_index} with "
                            f"before={before}, after={after}")

            client = self.qdrant_connector._client

            # Get the current chunk to find total_chunks
            search_results = await client.scroll(
                collection_name=self.qdrant_settings.collection_name,
                scroll_filter=Filter(
                    must=[
                        FieldCondition(key="metadata.id", match=MatchValue(value=document_id)),
                        FieldCondition(key="metadata.chunk_index", match=MatchValue(value=chunk_index)),
                    ],
                ),
                limit=1,
            )

            if not search_results[0]:
                return [f"<error>Chunk not found for document {document_id} at index {chunk_index}</error>"]

            current = search_results[0][0]
            metadata = current.payload.get("metadata", {})
            total_chunks = metadata.get("total_chunks")

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
        self.tool(get_chunk, name="qdrant-get-chunk", description=TOOL_GET_CHUNK_DESCRIPTION)
        self.tool(
            expand_context,
            name="qdrant-expand-context",
            description=TOOL_EXPAND_CONTEXT_DESCRIPTION,
        )
        self.tool(
            get_document_chunks,
            name="qdrant-get-document-chunks",
            description=TOOL_GET_DOCUMENT_CHUNKS_DESCRIPTION,
        )


# Create the server instance
mcp = ExtendedQdrantMCPServer(
    tool_settings=ToolSettings(TOOL_FIND_DESCRIPTION=TOOL_FIND_DESCRIPTION),
    qdrant_settings=QdrantSettings(),
    embedding_provider_settings=EmbeddingProviderSettings(),
    name="mcp-server-qdrant-extended",
    instructions=SERVER_INSTRUCTIONS,
)

if __name__ == "__main__":
    asyncio.run(mcp.run_async(transport="streamable-http", port=8000))
