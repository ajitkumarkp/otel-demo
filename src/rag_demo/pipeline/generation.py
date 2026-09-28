"""LLM generation module using Amazon Bedrock Claude Sonnet.

Handles response generation with retrieved context, conversation history,
and proper OpenTelemetry instrumentation.
"""

import json
import logging
import time

import boto3
from opentelemetry import trace

from rag_demo.config import BedrockConfig
from rag_demo.instrumentation.attributes import (
    ATTR_INPUT_TOKENS,
    ATTR_MAX_TOKENS,
    ATTR_MODEL_ID,
    ATTR_OUTPUT_TOKENS,
    ATTR_RESPONSE_LENGTH,
    ATTR_STOP_REASON,
    ATTR_TEMPERATURE,
    ATTR_TOTAL_TOKENS,
    SPAN_LLM_GENERATION,
)
from rag_demo.pipeline.vector_store import RetrievalResult

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a helpful product support assistant, helping users with
questions about the product. You provide accurate, helpful information based on the
official product documentation.

Guidelines:
- Answer based ONLY on the provided context documents
- If the context doesn't contain relevant information, say so clearly
- Be concise but thorough
- Include specific steps, settings, or values when available
- For account- or security-sensitive actions, recommend verifying with an administrator
- Do not speculate beyond the documentation
- If asked about competitor products, politely redirect to questions about this product

Format your responses clearly with bullet points or numbered steps when appropriate."""


class LLMGenerator:
    """Generates responses using Amazon Bedrock Claude Sonnet.

    Constructs prompts with retrieved context, manages conversation flow,
    and records detailed OTel attributes for quality monitoring.
    """

    def __init__(self, config: BedrockConfig):
        self.config = config
        self._bedrock = boto3.client("bedrock-runtime", region_name=config.region)

    def generate(
        self,
        query: str,
        context_docs: list[RetrievalResult],
        conversation_history: list[dict],
        intent: str = "general",
    ) -> str:
        """Generate a response using retrieved context and conversation history.

        Args:
            query: The user's current question.
            context_docs: Retrieved documents from vector store.
            conversation_history: Previous conversation turns.
            intent: Classified intent type for the query.

        Returns:
            Generated response text.
        """
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span(SPAN_LLM_GENERATION) as span:
            # Required gen_ai semantic convention attributes for AgentCore Evaluations
            span.set_attribute("gen_ai.operation.name", "chat")
            span.set_attribute("gen_ai.system", "strands-agents")
            span.set_attribute(ATTR_MODEL_ID, self.config.generation_model_id)
            span.set_attribute(ATTR_TEMPERATURE, self.config.temperature)
            span.set_attribute(ATTR_MAX_TOKENS, self.config.max_tokens)
            span.set_attribute("rag.generation.context_docs_count", len(context_docs))
            span.set_attribute("rag.generation.intent", intent)

            # Record user input as event (AgentCore Evaluations format)
            span.add_event("gen_ai.user.message", attributes={
                "content": json.dumps([{"text": query}]),
            })
            start_time = time.perf_counter()

            try:
                # Build the messages
                messages = self._build_messages(query, context_docs, conversation_history)

                # Call Bedrock Converse API
                response = self._bedrock.converse(
                    modelId=self.config.generation_model_id,
                    system=[{"text": SYSTEM_PROMPT}],
                    messages=messages,
                    inferenceConfig={
                        "maxTokens": self.config.max_tokens,
                        "temperature": self.config.temperature,
                    },
                )

                # Extract response
                output_text = response["output"]["message"]["content"][0]["text"]
                usage = response.get("usage", {})
                stop_reason = response.get("stopReason", "unknown")

                # Record token usage and metrics
                input_tokens = usage.get("inputTokens", 0)
                output_tokens = usage.get("outputTokens", 0)
                elapsed_ms = (time.perf_counter() - start_time) * 1000

                span.set_attribute(ATTR_INPUT_TOKENS, input_tokens)
                span.set_attribute(ATTR_OUTPUT_TOKENS, output_tokens)
                span.set_attribute(ATTR_TOTAL_TOKENS, input_tokens + output_tokens)
                span.set_attribute(ATTR_STOP_REASON, stop_reason)
                span.set_attribute(ATTR_RESPONSE_LENGTH, len(output_text))
                span.set_attribute("rag.generation.latency_ms", elapsed_ms)
                # Record assistant output as event (AgentCore Evaluations format)
                span.add_event("gen_ai.choice", attributes={
                    "finish_reason": stop_reason,
                    "message": json.dumps([{"text": output_text}]),
                })
                span.set_status(trace.StatusCode.OK)

                return output_text

            except Exception as e:
                logger.error(f"LLM generation failed: {e}")
                span.set_status(trace.StatusCode.ERROR, str(e))
                span.record_exception(e)
                return (
                    "I apologize, but I'm having trouble generating a response right now. "
                    "Please try again or contact product support."
                )

    def _build_messages(
        self,
        query: str,
        context_docs: list[RetrievalResult],
        conversation_history: list[dict],
    ) -> list[dict]:
        """Build the message payload for the Converse API.

        Args:
            query: Current user query.
            context_docs: Retrieved context documents.
            conversation_history: Previous conversation turns.

        Returns:
            List of message dicts for the Converse API.
        """
        messages = []

        # Add conversation history (last 5 turns max)
        recent_history = conversation_history[-10:]  # 5 turns = 10 messages
        for turn in recent_history:
            messages.append(turn)

        # Build the current user message with context
        context_text = self._format_context(context_docs)

        user_message = (
            f"Context documents:\n{context_text}\n\n"
            f"User question: {query}\n\n"
            "Please answer the user's question based on the context documents provided. "
            "If the context doesn't contain relevant information, let the user know."
        )

        messages.append({"role": "user", "content": [{"text": user_message}]})

        return messages

    def _format_context(self, context_docs: list[RetrievalResult]) -> str:
        """Format retrieved documents into a context string."""
        if not context_docs:
            return "No relevant documents found."

        parts = []
        for i, doc in enumerate(context_docs, 1):
            title = doc.metadata.get("title", "Unknown")
            parts.append(
                f"[Document {i}] {title} (relevance: {doc.score:.2f})\n{doc.content}"
            )

        return "\n\n---\n\n".join(parts)
