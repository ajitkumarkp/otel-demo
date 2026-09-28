"""OpenTelemetry tracing setup and configuration.

Configures the OTel SDK with exporters for:
- Console (local development/debugging)
- OTLP (Jaeger, OpenTelemetry Collector, or CloudWatch via ADOT)
- CloudWatch Logs (direct export for AgentCore Evaluations)
"""

import json
import logging
from typing import Optional

import boto3
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import StatusCode

from rag_demo.config import InstrumentationConfig

logger = logging.getLogger(__name__)


class CloudWatchLogsExporter(SpanExporter):
    """Custom exporter that writes OTel spans to CloudWatch Logs.

    This enables AgentCore Evaluations to pick up traces for quality analysis.
    Spans are formatted as structured JSON matching the OTel trace format that
    AgentCore Evaluations expects.
    """

    def __init__(self, log_group: str, region: str):
        self.log_group = log_group
        self.region = region
        self.log_stream = "rag-chatbot-traces"
        self._client = boto3.client("logs", region_name=region)
        self._ensure_log_group()
        self._sequence_token: Optional[str] = None

    def _ensure_log_group(self):
        """Create log group and stream if they don't exist."""
        try:
            self._client.create_log_group(logGroupName=self.log_group)
            logger.info(f"Created CloudWatch log group: {self.log_group}")
        except self._client.exceptions.ResourceAlreadyExistsException:
            pass

        try:
            self._client.create_log_stream(
                logGroupName=self.log_group,
                logStreamName=self.log_stream,
            )
            logger.info(f"Created CloudWatch log stream: {self.log_stream}")
        except self._client.exceptions.ResourceAlreadyExistsException:
            pass

    def export(self, spans) -> SpanExportResult:
        """Export spans to CloudWatch Logs as structured JSON."""
        try:
            log_events = []
            for span in spans:
                span_data = self._span_to_dict(span)
                log_events.append(
                    {
                        "timestamp": int(span.start_time / 1_000_000),  # ns to ms
                        "message": json.dumps(span_data),
                    }
                )

            if not log_events:
                return SpanExportResult.SUCCESS

            # Sort by timestamp (required by CloudWatch)
            log_events.sort(key=lambda e: e["timestamp"])

            put_kwargs = {
                "logGroupName": self.log_group,
                "logStreamName": self.log_stream,
                "logEvents": log_events,
            }
            if self._sequence_token:
                put_kwargs["sequenceToken"] = self._sequence_token

            response = self._client.put_log_events(**put_kwargs)
            self._sequence_token = response.get("nextSequenceToken")
            return SpanExportResult.SUCCESS

        except Exception as e:
            logger.error(f"Failed to export spans to CloudWatch: {e}")
            return SpanExportResult.FAILURE

    def _span_to_dict(self, span) -> dict:
        """Convert an OTel span to a structured dictionary for AgentCore Evaluations."""
        context = span.get_span_context()
        parent_id = None
        if span.parent:
            parent_id = f"0x{span.parent.span_id:016x}"

        # Convert span events
        events = []
        for event in span.events or []:
            event_dict = {
                "name": event.name,
                "timeUnixNano": event.timestamp,
                "attributes": [
                    {"key": k, "value": {"stringValue": str(v)}}
                    for k, v in (event.attributes or {}).items()
                ],
            }
            events.append(event_dict)

        return {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": k, "value": {"stringValue": str(v)}}
                            for k, v in (span.resource.attributes or {}).items()
                        ]
                    },
                    "scopeSpans": [
                        {
                            "scope": {
                                "name": "strands.telemetry.tracer"
                            },
                            "spans": [
                                {
                                    "traceId": f"0x{context.trace_id:032x}",
                                    "spanId": f"0x{context.span_id:016x}",
                                    "parentSpanId": parent_id,
                                    "name": span.name,
                                    "kind": span.kind.value if span.kind else 0,
                                    "startTimeUnixNano": span.start_time,
                                    "endTimeUnixNano": span.end_time,
                                    "attributes": [
                                        {
                                            "key": k,
                                            "value": {"stringValue": str(v)},
                                        }
                                        for k, v in (span.attributes or {}).items()
                                    ],
                                    "events": events,
                                    "status": {
                                        "code": (
                                            span.status.status_code.value
                                            if span.status
                                            else StatusCode.UNSET.value
                                        ),
                                        "message": (
                                            span.status.description
                                            if span.status and span.status.description
                                            else ""
                                        ),
                                    },
                                }
                            ],
                        }
                    ],
                }
            ]
        }

    def shutdown(self):
        """Clean shutdown."""
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        """Force flush is a no-op for CloudWatch as we write synchronously."""
        return True


def setup_tracing(config: InstrumentationConfig) -> trace.Tracer:
    """Initialize OpenTelemetry tracing with the configured exporter.

    Args:
        config: Instrumentation configuration specifying exporter type and settings.

    Returns:
        A configured OTel Tracer instance.
    """
    resource = Resource.create(
        {
            "service.name": config.service_name,
            "service.version": config.service_version,
            "deployment.environment": "demo",
            "service.namespace": "rag-observability-demo",
        }
    )

    provider = TracerProvider(resource=resource)

    # Configure exporter based on config
    if config.exporter_type == "console":
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        logger.info("Configured console span exporter")

    elif config.exporter_type == "otlp":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=config.otlp_endpoint)
            processor = BatchSpanProcessor(exporter)
            provider.add_span_processor(processor)
            logger.info(f"Configured OTLP exporter -> {config.otlp_endpoint}")
        except ImportError:
            logger.warning("OTLP exporter not available, falling back to console")
            processor = SimpleSpanProcessor(ConsoleSpanExporter())
            provider.add_span_processor(processor)

    elif config.exporter_type == "cloudwatch":
        cw_exporter = CloudWatchLogsExporter(
            log_group=config.cloudwatch_log_group,
            region=config.cloudwatch_region,
        )
        processor = BatchSpanProcessor(cw_exporter)
        provider.add_span_processor(processor)
        logger.info(
            f"Configured CloudWatch Logs exporter -> {config.cloudwatch_log_group}"
        )

        # Also add console for local visibility
        console_processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(console_processor)

    else:
        raise ValueError(f"Unknown exporter type: {config.exporter_type}")

    # Set global tracer provider
    trace.set_tracer_provider(provider)

    return trace.get_tracer(config.service_name, config.service_version)



