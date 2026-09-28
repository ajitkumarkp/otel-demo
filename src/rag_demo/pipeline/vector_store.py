"""Vector store module using ChromaDB with Amazon Titan Embeddings.

Manages document embedding, storage, and semantic retrieval.
This is the local equivalent of a managed vector database (for example
 Aurora pgvector or OpenSearch) in a production architecture.
"""

import json
import logging
import time
from typing import Optional

import boto3
import chromadb
from opentelemetry import trace

from rag_demo.config import BedrockConfig, VectorStoreConfig
from rag_demo.instrumentation.attributes import (
    ATTR_DOCS_RETRIEVED,
    ATTR_EMBEDDING_DIMENSIONS,
    ATTR_MODEL_ID,
    ATTR_RETRIEVAL_LATENCY_MS,
    ATTR_RETRIEVAL_QUERY,
    ATTR_RETRIEVAL_TOP_SCORE,
    SPAN_EMBEDDING_GENERATION,
    SPAN_VECTOR_RETRIEVAL,
)

logger = logging.getLogger(__name__)


class RetrievalResult:
    """A single retrieval result with content and metadata."""

    def __init__(self, doc_id: str, content: str, score: float, metadata: dict):
        self.doc_id = doc_id
        self.content = content
        self.score = score
        self.metadata = metadata

    def __repr__(self):
        return f"RetrievalResult(id={self.doc_id}, score={self.score:.3f})"


class VectorStore:
    """ChromaDB-based vector store with Bedrock Titan embeddings.

    Provides:
    - Document ingestion with embedding generation
    - Semantic similarity search
    - OTel instrumentation for both embedding and retrieval spans
    """

    def __init__(self, bedrock_config: BedrockConfig, store_config: VectorStoreConfig):
        self.bedrock_config = bedrock_config
        self.store_config = store_config
        self._bedrock = boto3.client("bedrock-runtime", region_name=bedrock_config.region)

        # Initialize ChromaDB with persistent storage
        self._chroma_client = chromadb.Client()
        self._collection = self._chroma_client.get_or_create_collection(
            name=store_config.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._initialized = False

    @property
    def document_count(self) -> int:
        """Number of documents in the collection."""
        return self._collection.count()

    def ingest_documents(self, documents: list[dict]) -> int:
        """Ingest documents into the vector store.

        Args:
            documents: List of dicts with 'id', 'content', 'title', 'category' keys.

        Returns:
            Number of documents ingested.
        """
        if self._collection.count() > 0:
            logger.info(
                f"Collection already has {self._collection.count()} documents, skipping ingest"
            )
            self._initialized = True
            return 0

        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span("document_ingestion") as span:
            span.set_attribute("rag.ingestion.document_count", len(documents))

            ids = []
            embeddings = []
            contents = []
            metadatas = []

            for doc in documents:
                embedding = self._generate_embedding(doc["content"])
                if embedding:
                    ids.append(doc["id"])
                    embeddings.append(embedding)
                    contents.append(doc["content"])
                    metadatas.append(
                        {
                            "title": doc["title"],
                            "category": doc["category"],
                        }
                    )

            if ids:
                self._collection.add(
                    ids=ids,
                    embeddings=embeddings,
                    documents=contents,
                    metadatas=metadatas,
                )

            span.set_attribute("rag.ingestion.success_count", len(ids))
            span.set_status(trace.StatusCode.OK)
            self._initialized = True

            logger.info(f"Ingested {len(ids)} documents into vector store")
            return len(ids)

    def retrieve(self, query: str, top_k: Optional[int] = None) -> list[RetrievalResult]:
        """Retrieve relevant documents for a query.

        Args:
            query: The search query text.
            top_k: Number of results to return (defaults to config value).

        Returns:
            List of RetrievalResult objects sorted by relevance.
        """
        tracer = trace.get_tracer(__name__)
        k = top_k or self.store_config.top_k

        with tracer.start_as_current_span(SPAN_VECTOR_RETRIEVAL) as span:
            span.set_attribute(ATTR_RETRIEVAL_QUERY, query[:200])  # Truncate for span
            start_time = time.perf_counter()

            # Generate query embedding
            query_embedding = self._generate_embedding(query, is_query=True)
            if not query_embedding:
                span.set_status(trace.StatusCode.ERROR, "Failed to generate query embedding")
                return []

            # Search ChromaDB
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=k,
                include=["documents", "metadatas", "distances"],
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Convert to RetrievalResult objects
            retrieval_results = []
            if results["ids"] and results["ids"][0]:
                for i, doc_id in enumerate(results["ids"][0]):
                    # ChromaDB returns distances (lower = more similar for cosine)
                    # Convert to similarity score (1 - distance)
                    distance = results["distances"][0][i]
                    score = 1.0 - distance

                    if score >= self.store_config.similarity_threshold:
                        retrieval_results.append(
                            RetrievalResult(
                                doc_id=doc_id,
                                content=results["documents"][0][i],
                                score=score,
                                metadata=results["metadatas"][0][i],
                            )
                        )

            # Record span attributes
            span.set_attribute(ATTR_DOCS_RETRIEVED, len(retrieval_results))
            span.set_attribute(ATTR_RETRIEVAL_LATENCY_MS, elapsed_ms)
            if retrieval_results:
                span.set_attribute(ATTR_RETRIEVAL_TOP_SCORE, retrieval_results[0].score)
            span.set_attribute("rag.retrieval.top_k_requested", k)
            span.set_status(trace.StatusCode.OK)

            return retrieval_results

    def _generate_embedding(
        self, text: str, is_query: bool = False
    ) -> Optional[list[float]]:
        """Generate an embedding vector using Amazon Titan Embeddings.

        Args:
            text: The text to embed.
            is_query: Whether this is a query (vs document) embedding.

        Returns:
            Embedding vector as a list of floats, or None on failure.
        """
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span(SPAN_EMBEDDING_GENERATION) as span:
            span.set_attribute(ATTR_MODEL_ID, self.bedrock_config.embedding_model_id)
            span.set_attribute(ATTR_EMBEDDING_DIMENSIONS, self.bedrock_config.embedding_dimensions)
            span.set_attribute("rag.embedding.input_type", "query" if is_query else "document")
            span.set_attribute("rag.embedding.input_length", len(text))

            try:
                body = json.dumps(
                    {
                        "inputText": text[:8192],  # Titan max input
                        "dimensions": self.bedrock_config.embedding_dimensions,
                    }
                )

                response = self._bedrock.invoke_model(
                    modelId=self.bedrock_config.embedding_model_id,
                    body=body,
                    contentType="application/json",
                    accept="application/json",
                )

                result = json.loads(response["body"].read())
                embedding = result["embedding"]

                span.set_attribute("rag.embedding.output_dimensions", len(embedding))
                span.set_status(trace.StatusCode.OK)
                return embedding

            except Exception as e:
                logger.error(f"Embedding generation failed: {e}")
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
                return None
