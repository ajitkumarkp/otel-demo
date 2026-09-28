"""RAG pipeline orchestrator.

Coordinates the full RAG pipeline: guardrail → intent → retrieve → generate.
Manages conversation state and provides the top-level instrumented span.
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from opentelemetry import trace

from rag_demo.config import AppConfig
from rag_demo.instrumentation.attributes import (
    ATTR_CONVERSATION_ID,
    ATTR_DOCS_RETRIEVED,
    ATTR_INTENT_TYPE,
    ATTR_TURN_NUMBER,
    ATTR_USER_QUERY,
    SPAN_PIPELINE_EXECUTION,
)
from rag_demo.knowledge_base.product_docs import get_all_documents
from rag_demo.pipeline.generation import LLMGenerator
from rag_demo.pipeline.guardrail import GuardrailChecker
from rag_demo.pipeline.intent import IntentClassifier
from rag_demo.pipeline.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class PipelineResponse:
    """Response from the RAG pipeline."""

    answer: str
    intent: str
    docs_retrieved: int
    conversation_id: str
    turn_number: int
    blocked: bool = False
    block_reason: str = ""
    latency_ms: float = 0.0


@dataclass
class ConversationState:
    """Tracks conversation state (simulates DynamoDB in production)."""

    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turn_number: int = 0
    history: list[dict] = field(default_factory=list)

    def add_turn(self, user_message: str, assistant_message: str):
        """Add a conversation turn to history."""
        self.history.append({"role": "user", "content": [{"text": user_message}]})
        self.history.append({"role": "assistant", "content": [{"text": assistant_message}]})
        self.turn_number += 1


class RAGPipeline:
    """Orchestrates the full RAG pipeline with OTel instrumentation.

    Pipeline stages:
    1. Guardrail check - validates input safety
    2. Intent classification - categorizes the query
    3. Vector retrieval - finds relevant documents
    4. LLM generation - produces the response

    Each stage is instrumented with its own OTel span, nested under
    a parent pipeline span for end-to-end tracing.
    """

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or AppConfig()

        # Initialize pipeline components
        self.guardrail = GuardrailChecker(self.config.guardrail)
        self.intent_classifier = IntentClassifier(
            self.config.bedrock, use_llm_fallback=False
        )
        self.vector_store = VectorStore(self.config.bedrock, self.config.vector_store)
        self.generator = LLMGenerator(self.config.bedrock)

        # Conversation state store (in-memory, simulates DynamoDB)
        self._conversations: dict[str, ConversationState] = {}

    def initialize(self) -> bool:
        """Initialize the pipeline by loading documents into the vector store.

        Returns:
            True if initialization succeeded.
        """
        try:
            documents = get_all_documents()
            count = self.vector_store.ingest_documents(documents)
            if count > 0:
                logger.info(f"Initialized vector store with {count} documents")
            else:
                logger.info(
                    f"Vector store already initialized with "
                    f"{self.vector_store.document_count} documents"
                )
            return True
        except Exception as e:
            logger.error(f"Failed to initialize pipeline: {e}")
            return False

    def get_or_create_conversation(
        self, conversation_id: Optional[str] = None
    ) -> ConversationState:
        """Get existing or create new conversation state."""
        if conversation_id and conversation_id in self._conversations:
            return self._conversations[conversation_id]

        state = ConversationState()
        self._conversations[state.conversation_id] = state
        return state

    def process_query(
        self, query: str, conversation_id: Optional[str] = None
    ) -> PipelineResponse:
        """Process a user query through the full RAG pipeline.

        Args:
            query: The user's question.
            conversation_id: Optional existing conversation ID.

        Returns:
            PipelineResponse with the answer and metadata.
        """
        tracer = trace.get_tracer(__name__)
        conversation = self.get_or_create_conversation(conversation_id)

        with tracer.start_as_current_span(SPAN_PIPELINE_EXECUTION) as span:
            start_time = time.perf_counter()
            span.set_attribute("gen_ai.operation.name", "invoke_agent")
            span.set_attribute("gen_ai.system", "strands-agents")
            span.set_attribute("gen_ai.agent.name", "rag-chatbot")
            span.set_attribute("gen_ai.request.model", self.config.bedrock.generation_model_id)
            span.set_attribute(ATTR_CONVERSATION_ID, conversation.conversation_id)
            span.set_attribute(ATTR_TURN_NUMBER, conversation.turn_number + 1)
            span.set_attribute(ATTR_USER_QUERY, query[:500])  # Truncate for span

            # Record user input event (required by AgentCore Evaluations)
            span.add_event("gen_ai.user.message", attributes={
                "content": json.dumps([{"text": query}]),
            })

            # Stage 1: Guardrail check
            guardrail_result = self.guardrail.check(query)
            if not guardrail_result.passed:
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                span.set_attribute("rag.pipeline.blocked", True)
                span.set_attribute("rag.pipeline.block_reason", guardrail_result.reason)
                span.set_status(trace.StatusCode.OK)

                return PipelineResponse(
                    answer=(
                        f"I'm unable to process that request. {guardrail_result.reason}. "
                        "Please rephrase your question about the product."
                    ),
                    intent="blocked",
                    docs_retrieved=0,
                    conversation_id=conversation.conversation_id,
                    turn_number=conversation.turn_number + 1,
                    blocked=True,
                    block_reason=guardrail_result.reason,
                    latency_ms=elapsed_ms,
                )

            # Stage 2: Intent classification
            intent, confidence = self.intent_classifier.classify(query)
            span.set_attribute(ATTR_INTENT_TYPE, intent.value)

            # Handle greetings without retrieval
            if intent.value == "greeting":
                greeting_response = (
                    "Hello! I'm your product support assistant. I can help you with:\n"
                    "• Account setup and login\n"
                    "• Billing, plans, and refunds\n"
                    "• Troubleshooting errors and performance issues\n"
                    "• API and third-party integrations\n"
                    "• Security, privacy, and compliance\n"
                    "• Projects, workspaces, and collaboration\n"
                    "• Contacting support\n\n"
                    "What can I help you with today?"
                )
                elapsed_ms = (time.perf_counter() - start_time) * 1000
                conversation.add_turn(query, greeting_response)
                span.set_status(trace.StatusCode.OK)

                return PipelineResponse(
                    answer=greeting_response,
                    intent=intent.value,
                    docs_retrieved=0,
                    conversation_id=conversation.conversation_id,
                    turn_number=conversation.turn_number,
                    latency_ms=elapsed_ms,
                )

            # Stage 3: Vector retrieval
            results = self.vector_store.retrieve(query)
            span.set_attribute(ATTR_DOCS_RETRIEVED, len(results))

            # Stage 4: LLM generation
            answer = self.generator.generate(
                query=query,
                context_docs=results,
                conversation_history=conversation.history,
                intent=intent.value,
            )

            elapsed_ms = (time.perf_counter() - start_time) * 1000

            # Update conversation state
            conversation.add_turn(query, answer)

            span.set_attribute("rag.pipeline.total_latency_ms", elapsed_ms)
            span.set_attribute("rag.pipeline.blocked", False)

            # Record final response event (required by AgentCore Evaluations)
            span.add_event("gen_ai.choice", attributes={
                "finish_reason": "end_turn",
                "message": json.dumps([{"text": answer}]),
            })
            span.set_status(trace.StatusCode.OK)

            return PipelineResponse(
                answer=answer,
                intent=intent.value,
                docs_retrieved=len(results),
                conversation_id=conversation.conversation_id,
                turn_number=conversation.turn_number,
                latency_ms=elapsed_ms,
            )
