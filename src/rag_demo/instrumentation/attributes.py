"""Span attribute constants for consistent instrumentation across the pipeline.

These follow OpenTelemetry semantic conventions where applicable,
with custom attributes for RAG-specific telemetry.
"""

# Pipeline stage names (used as span names)
SPAN_GUARDRAIL_CHECK = "guardrail_check"
SPAN_INTENT_CLASSIFICATION = "intent_classification"
SPAN_EMBEDDING_GENERATION = "embedding_generation"
SPAN_VECTOR_RETRIEVAL = "vector_retrieval"
SPAN_RERANKING = "reranking"
SPAN_LLM_GENERATION = "chat"
SPAN_PIPELINE_EXECUTION = "invoke_agent Strands Agents"

# LLM attributes (following gen_ai semantic conventions)
ATTR_MODEL_ID = "gen_ai.request.model"
ATTR_INPUT_TOKENS = "gen_ai.usage.input_tokens"
ATTR_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
ATTR_TOTAL_TOKENS = "gen_ai.usage.total_tokens"
ATTR_TEMPERATURE = "gen_ai.request.temperature"
ATTR_MAX_TOKENS = "gen_ai.request.max_tokens"
ATTR_STOP_REASON = "gen_ai.response.finish_reason"

# RAG-specific attributes
ATTR_INTENT_TYPE = "rag.intent.type"
ATTR_INTENT_CONFIDENCE = "rag.intent.confidence"
ATTR_DOCS_RETRIEVED = "rag.retrieval.documents_count"
ATTR_RETRIEVAL_LATENCY_MS = "rag.retrieval.latency_ms"
ATTR_RETRIEVAL_TOP_SCORE = "rag.retrieval.top_score"
ATTR_RETRIEVAL_QUERY = "rag.retrieval.query"
ATTR_EMBEDDING_DIMENSIONS = "rag.embedding.dimensions"
ATTR_RERANK_ENABLED = "rag.rerank.enabled"
ATTR_RERANK_MODEL = "rag.rerank.model"

# Guardrail attributes
ATTR_GUARDRAIL_PASSED = "rag.guardrail.passed"
ATTR_GUARDRAIL_REASON = "rag.guardrail.block_reason"
ATTR_INPUT_LENGTH = "rag.guardrail.input_length"

# Conversation attributes
ATTR_CONVERSATION_ID = "rag.conversation.id"
ATTR_TURN_NUMBER = "rag.conversation.turn_number"
ATTR_USER_QUERY = "rag.query.text"
ATTR_RESPONSE_LENGTH = "rag.response.length"

# Quality metrics (for AgentCore Evaluations)
ATTR_CONTEXT_RELEVANCE = "rag.quality.context_relevance"
ATTR_ANSWER_FAITHFULNESS = "rag.quality.answer_faithfulness"
ATTR_ANSWER_COMPLETENESS = "rag.quality.answer_completeness"
