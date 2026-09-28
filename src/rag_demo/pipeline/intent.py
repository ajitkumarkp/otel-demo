"""Intent classification module.

Classifies user queries into intent categories to optimize retrieval
and response generation. Uses a rule-based classifier with optional
LLM-based classification via Amazon Nova Lite.
"""

import json
import logging
import time
from enum import Enum

import boto3
from opentelemetry import trace

from rag_demo.config import BedrockConfig
from rag_demo.instrumentation.attributes import (
    ATTR_INTENT_CONFIDENCE,
    ATTR_INTENT_TYPE,
    ATTR_MODEL_ID,
    SPAN_INTENT_CLASSIFICATION,
)

logger = logging.getLogger(__name__)


class IntentType(str, Enum):
    """Supported intent categories for the RAG chatbot."""

    ACCOUNT = "account"
    BILLING = "billing"
    TROUBLESHOOTING = "troubleshooting"
    TECHNOLOGY = "technology"
    SECURITY = "security"
    FEATURES = "features"
    SUPPORT = "support"
    GENERAL = "general"
    GREETING = "greeting"
    OUT_OF_SCOPE = "out_of_scope"


# Keyword-based rules for fast classification
INTENT_KEYWORDS: dict[IntentType, list[str]] = {
    IntentType.ACCOUNT: [
        "sign up", "account", "register", "profile", "password",
        "log in", "login", "mfa", "two-factor", "verify email",
        "free trial", "onboarding",
    ],
    IntentType.BILLING: [
        "billing", "invoice", "payment", "refund", "subscription",
        "plan", "pricing", "upgrade", "downgrade", "cancel",
        "charge", "seat", "renewal",
    ],
    IntentType.TROUBLESHOOTING: [
        "error", "not working", "problem", "issue", "broken",
        "cannot", "can't", "failing", "fails", "slow",
        "locked out", "timeout", "crash",
    ],
    IntentType.TECHNOLOGY: [
        "api", "integration", "webhook", "rate limit", "token",
        "sdk", "endpoint", "oauth", "sso", "saml",
        "connect", "sync",
    ],
    IntentType.SECURITY: [
        "security", "encryption", "compliance", "gdpr", "soc 2",
        "audit log", "permission", "role", "access control",
        "data retention", "privacy",
    ],
    IntentType.FEATURES: [
        "project", "workspace", "feature", "collaborate", "member",
        "invite", "archive", "dashboard", "how do i use",
    ],
    IntentType.SUPPORT: [
        "support", "contact", "ticket", "help desk", "sla",
        "severity", "status page", "incident", "escalate",
    ],
    IntentType.GREETING: [
        "hello", "hi", "hey", "good morning", "good afternoon",
        "help", "what can you do",
    ],
}


class IntentClassifier:
    """Classifies user queries into intent categories.

    Uses a two-stage approach:
    1. Rule-based keyword matching (fast, no API call)
    2. LLM-based classification via Nova Lite (if rules are inconclusive)
    """

    def __init__(self, config: BedrockConfig, use_llm_fallback: bool = False):
        self.config = config
        self.use_llm_fallback = use_llm_fallback
        if use_llm_fallback:
            self._bedrock = boto3.client(
                "bedrock-runtime", region_name=config.region
            )

    def classify(self, query: str) -> tuple[IntentType, float]:
        """Classify a user query into an intent category.

        Args:
            query: The user's question or statement.

        Returns:
            Tuple of (IntentType, confidence_score).
        """
        tracer = trace.get_tracer(__name__)
        with tracer.start_as_current_span(SPAN_INTENT_CLASSIFICATION) as span:
            start_time = time.perf_counter()

            # Stage 1: Rule-based classification
            intent, confidence = self._rule_based_classify(query)

            # Stage 2: LLM fallback if low confidence
            if confidence < 0.6 and self.use_llm_fallback:
                span.set_attribute("rag.intent.method", "llm")
                intent, confidence = self._llm_classify(query, span)
            else:
                span.set_attribute("rag.intent.method", "rule_based")

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute(ATTR_INTENT_TYPE, intent.value)
            span.set_attribute(ATTR_INTENT_CONFIDENCE, confidence)
            span.set_attribute("rag.intent.latency_ms", elapsed_ms)
            span.set_status(trace.StatusCode.OK)

            return intent, confidence

    def _rule_based_classify(self, query: str) -> tuple[IntentType, float]:
        """Classify using keyword matching."""
        query_lower = query.lower()
        scores: dict[IntentType, int] = {}

        for intent, keywords in INTENT_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in query_lower)
            if score > 0:
                scores[intent] = score

        if not scores:
            return IntentType.GENERAL, 0.4

        best_intent = max(scores, key=scores.get)
        max_score = scores[best_intent]
        # Normalize confidence based on keyword matches
        confidence = min(0.5 + (max_score * 0.15), 0.95)

        return best_intent, confidence

    def _llm_classify(self, query: str, span) -> tuple[IntentType, float]:
        """Classify using Amazon Nova Lite for ambiguous queries."""
        try:
            prompt = (
                "Classify the following user query about a SaaS product into exactly "
                "one category. Respond with JSON only.\n\n"
                "Categories: account, billing, troubleshooting, technology, "
                "security, features, support, general, greeting, out_of_scope\n\n"
                f"Query: {query}\n\n"
                'Response format: {{"intent": "<category>", "confidence": <0.0-1.0>}}'
            )

            response = self._bedrock.converse(
                modelId=self.config.intent_model_id,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 100, "temperature": 0.1},
            )

            span.set_attribute(ATTR_MODEL_ID, self.config.intent_model_id)

            # Parse response
            output_text = response["output"]["message"]["content"][0]["text"]
            usage = response.get("usage", {})
            span.set_attribute("gen_ai.usage.input_tokens", usage.get("inputTokens", 0))
            span.set_attribute("gen_ai.usage.output_tokens", usage.get("outputTokens", 0))

            result = json.loads(output_text)
            intent_str = result.get("intent", "general")
            confidence = float(result.get("confidence", 0.7))

            try:
                intent = IntentType(intent_str)
            except ValueError:
                intent = IntentType.GENERAL

            return intent, confidence

        except Exception as e:
            logger.warning(f"LLM intent classification failed: {e}, using rule-based")
            span.set_attribute("rag.intent.llm_error", str(e))
            return IntentType.GENERAL, 0.5
