"""Guardrail check module for input validation.

Implements basic content safety checks before processing user queries.
In production, this would integrate with Amazon Bedrock Guardrails.
"""

import re
import time

from opentelemetry import trace

from rag_demo.config import GuardrailConfig
from rag_demo.instrumentation.attributes import (
    ATTR_GUARDRAIL_PASSED,
    ATTR_GUARDRAIL_REASON,
    ATTR_INPUT_LENGTH,
    SPAN_GUARDRAIL_CHECK,
)


class GuardrailResult:
    """Result of a guardrail check."""

    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason


class GuardrailChecker:
    """Validates user input against safety rules.

    Checks:
    - Input length limits
    - PII detection (SSN, credit card, email)
    - Blocked topic detection
    - Prompt injection patterns
    """

    def __init__(self, config: GuardrailConfig):
        self.config = config
        self._pii_patterns = [re.compile(p) for p in config.pii_patterns]
        self._injection_patterns = [
            re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.IGNORECASE),
            re.compile(r"you\s+are\s+now\s+a", re.IGNORECASE),
            re.compile(r"system\s*:\s*", re.IGNORECASE),
            re.compile(r"<\s*/?system\s*>", re.IGNORECASE),
        ]

    def check(self, user_input: str) -> GuardrailResult:
        """Run all guardrail checks on user input with OTel instrumentation.

        Args:
            user_input: The raw user query text.

        Returns:
            GuardrailResult indicating pass/fail and reason.
        """
        tracer = trace.get_tracer(__name__)

        with tracer.start_as_current_span(SPAN_GUARDRAIL_CHECK) as span:
            span.set_attribute(ATTR_INPUT_LENGTH, len(user_input))
            start_time = time.perf_counter()

            # Check input length
            if len(user_input) > self.config.max_input_length:
                result = GuardrailResult(
                    passed=False,
                    reason=f"Input exceeds maximum length of {self.config.max_input_length} characters",
                )
                self._record_span(span, result)
                return result

            # Check for empty input
            if not user_input.strip():
                result = GuardrailResult(passed=False, reason="Empty input")
                self._record_span(span, result)
                return result

            # Check for PII
            for pattern in self._pii_patterns:
                if pattern.search(user_input):
                    result = GuardrailResult(
                        passed=False,
                        reason="Input contains personally identifiable information (PII)",
                    )
                    self._record_span(span, result)
                    return result

            # Check for blocked topics
            input_lower = user_input.lower()
            for topic in self.config.blocked_topics:
                if topic.lower() in input_lower:
                    result = GuardrailResult(
                        passed=False,
                        reason=f"Input contains blocked topic: {topic}",
                    )
                    self._record_span(span, result)
                    return result

            # Check for prompt injection
            for pattern in self._injection_patterns:
                if pattern.search(user_input):
                    result = GuardrailResult(
                        passed=False,
                        reason="Potential prompt injection detected",
                    )
                    self._record_span(span, result)
                    return result

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("rag.guardrail.latency_ms", elapsed_ms)

            result = GuardrailResult(passed=True)
            self._record_span(span, result)
            return result

    def _record_span(self, span, result: GuardrailResult):
        """Record guardrail result attributes on the span."""
        span.set_attribute(ATTR_GUARDRAIL_PASSED, result.passed)
        if not result.passed:
            span.set_attribute(ATTR_GUARDRAIL_REASON, result.reason)
            span.set_status(trace.StatusCode.OK)  # Guardrail working correctly
        else:
            span.set_status(trace.StatusCode.OK)
