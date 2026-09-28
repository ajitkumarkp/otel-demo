# AgentCore Evaluations Integration Guide

## Executive Summary

This guide explains how to connect an existing RAG chatbot to Amazon Bedrock AgentCore Evaluations for continuous quality monitoring. The key point: **no architectural changes are required**. You add a small amount of OpenTelemetry instrumentation to your application, export traces to CloudWatch Logs, and AgentCore Evaluations continuously scores every conversation.

Your existing test suite keeps passing. Your existing pipeline stays exactly as-is.

---

## What You Get

| Capability | How |
|-----------|-----|
| Continuous quality monitoring | AgentCore scores every conversation (or a sample %) on helpfulness, faithfulness, relevance |
| Custom evaluators | Define your own rubrics (domain accuracy, safety caveats, grounding) |
| Quality diagnostics | Drill into individual conversations to see why they scored poorly |
| Drift detection | Track score trends over time — catch prompt or retrieval degradation early |
| On-demand evaluation | Run evaluations against historical traces for regression testing |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Your application (unchanged)                    │
│                                                                   │
│  Guardrail → Intent → Retrieval → Generation                     │
│       │          │          │           │                         │
│       └──────────┴──────────┴───────────┘                        │
│                     OTel Spans (NEW)                             │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
                   CloudWatch Logs (OTel traces)
                              │
                              ▼
              ┌───────────────────────────────┐
              │   AgentCore Evaluations        │
              │   - Builtin.Helpfulness        │
              │   - Builtin.Faithfulness       │
              │   - Builtin.Relevance          │
              │   - Custom: Response_Quality   │
              └───────────────────────────────┘
                              │
                              ▼
                   CloudWatch Metrics + Logs
                   (evaluation results)
```

---

## Implementation Steps

### Step 1: Add OTel SDK Dependencies

Add to your application's `requirements.txt`:

```
opentelemetry-api==1.25.0
opentelemetry-sdk==1.25.0
```

If you run on AWS Lambda, you can instead use the **AWS Distro for OpenTelemetry (ADOT) Lambda Layer**, which bundles the SDK and handles CloudWatch export automatically. This is the recommended approach for Lambda.

**ADOT Layer ARN (us-east-1):**

```
arn:aws:lambda:us-east-1:901920570463:layer:aws-otel-python-amd64-ver-1-25-0:1
```

---

### Step 2: Initialize Tracing (one-time setup)

Add to your application's initialization (for Lambda, the cold start path):

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider

# Initialize once at startup
resource = Resource.create({
    "service.name": "rag-chatbot",
    "service.version": "1.0.0",
})
provider = TracerProvider(resource=resource)
trace.set_tracer_provider(provider)

# If using the ADOT layer, the exporter is configured automatically.
# If NOT using ADOT, add the CloudWatch exporter (see Appendix A).
```

If NOT using the ADOT layer, you'll need a custom exporter to write spans to CloudWatch Logs. See Appendix A for the implementation.

---

### Step 3: Instrument the Generation Step (critical)

This is the **minimum required change**. Where you call the Bedrock generation API, wrap the call with a span that includes the attributes AgentCore needs:

```python
import json
from opentelemetry import trace

tracer = trace.get_tracer("rag-chatbot")

def generate_response(user_query, assembled_prompt, model_id, ...):
    with tracer.start_as_current_span("llm_generation") as span:
        # === REQUIRED: These 4 attributes are what AgentCore evaluates ===
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.request.model", model_id)
        span.set_attribute("gen_ai.input.messages", json.dumps(
            [{"role": "user", "content": user_query}]
        ))

        # ... your existing generation call ...
        response_text = call_bedrock(assembled_prompt, model_id)

        span.set_attribute("gen_ai.output.messages", json.dumps(
            [{"role": "assistant", "content": response_text}]
        ))

        # === OPTIONAL but recommended ===
        span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", output_tokens)

        return response_text
```

**The 4 required attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `gen_ai.operation.name` | string | Always `"chat"` for conversational AI |
| `gen_ai.request.model` | string | The Bedrock model ID (e.g., `us.anthropic.claude-sonnet-4-6`) |
| `gen_ai.input.messages` | string (JSON) | Serialized array of input messages |
| `gen_ai.output.messages` | string (JSON) | Serialized array of output messages |

These follow the [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/).

---

### Step 4: (Optional) Instrument Other Pipeline Stages

For richer diagnostics, wrap other stages. These are not required for evaluation scoring but help with root-cause analysis when scores are low:

```python
# Guardrail check
with tracer.start_as_current_span("guardrail_check") as span:
    span.set_attribute("rag.guardrail.passed", True)
    # ... existing guardrail logic ...

# Intent classification
with tracer.start_as_current_span("intent_classification") as span:
    span.set_attribute("rag.intent.type", "billing")
    span.set_attribute("rag.intent.confidence", 0.92)
    # ... existing intent logic ...

# Retrieval
with tracer.start_as_current_span("vector_retrieval") as span:
    span.set_attribute("rag.retrieval.documents_count", 5)
    span.set_attribute("rag.retrieval.top_score", 0.87)
    # ... existing vector search ...
```

---

### Step 5: Ensure Traces Land in CloudWatch Logs

**Option A: ADOT Lambda Layer (recommended for Lambda)**

The ADOT layer automatically exports spans to CloudWatch Logs. Configure via environment variables:

```
OTEL_SERVICE_NAME=rag-chatbot
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument
```

Traces will appear in the `aws/spans` log group.

**Option B: Custom CloudWatch exporter**

If you need more control over the log group name or format, implement a custom exporter (see Appendix A). This writes spans directly to a log group of your choosing.

---

### Step 6: Create the AgentCore Evaluation Configuration

Once traces are flowing to CloudWatch, configure AgentCore Evaluations to monitor them.

**Using the AWS CLI:**

```bash
# 1. Create the IAM execution role (see Appendix B for the trust policy)
aws iam create-role \
  --role-name RAGEvaluationRole \
  --assume-role-policy-document file://trust-policy.json

aws iam put-role-policy \
  --role-name RAGEvaluationRole \
  --policy-name AgentCoreEvaluationsPermissions \
  --policy-document file://permissions-policy.json

# 2. Create the online evaluation config
aws bedrock-agentcore-control create-online-evaluation-config \
  --online-evaluation-config-name rag_chatbot_eval \
  --description "Continuous evaluation of the RAG chatbot" \
  --rule '{"samplingConfig": {"samplingPercentage": 100.0}}' \
  --data-source-config '{
    "cloudWatchLogs": {
      "logGroupNames": ["/aws/spans"],
      "serviceNames": ["rag-chatbot"]
    }
  }' \
  --evaluators '[
    {"evaluatorId": "Builtin.Helpfulness"},
    {"evaluatorId": "Builtin.Faithfulness"},
    {"evaluatorId": "Builtin.Relevance"}
  ]' \
  --evaluation-execution-role-arn arn:aws:iam::ACCOUNT_ID:role/RAGEvaluationRole \
  --enable-on-create
```

---

### Step 7: (Optional) Create a Custom Evaluator

For domain-specific quality checks:

```bash
aws bedrock-agentcore-control create-evaluator \
  --evaluator-name Response_Quality \
  --description "Product-specific quality criteria for the support assistant" \
  --evaluator-config '{
    "llmAsJudge": {
      "promptTemplate": "You are evaluating a product support assistant response.\n\nUser Query: {{input}}\nAssistant Response: {{output}}\nRetrieved Context: {{context}}\n\nEvaluate on:\n1. Are the steps, settings, and values correct per the context?\n2. Are appropriate caveats included for sensitive actions?\n3. Does it stay grounded in the retrieved context?\n4. Is the response complete and helpful?\n\nScore 1-5 and explain."
    }
  }'
```

---

## Running On-Demand Evaluations

For regression testing after prompt changes or model updates, you can run evaluations against historical traces:

```python
import boto3
import json

eval_client = boto3.client("bedrock-agentcore", region_name="us-east-1")

# Prepare trace spans (fetched from CloudWatch Logs)
response = eval_client.evaluate(
    evaluatorId="Builtin.Helpfulness",
    evaluationInput={"sessionSpans": flattened_spans},
)

result = response["evaluationResults"][0]
print(f"Score: {result.get('score')}")
print(f"Explanation: {result.get('explanation')}")
```

A complete evaluation runner script is available in this repository (`run_evaluations.py`).

---

## Timeline and Effort Estimate

| Task | Effort | Risk |
|------|--------|------|
| Add OTel SDK / ADOT layer | 1 day | Low — additive only |
| Instrument generation step (4 attributes) | 2 hours | Low — wraps existing code |
| Instrument other pipeline stages (optional) | 1 day | Low — additive only |
| Verify traces appear in CloudWatch | 1 hour | Low — just check CW console |
| Create IAM role + evaluation config | 2 hours | Low — IAM policy from template |
| Create custom evaluator | 2 hours | Low — prompt template only |
| Validate with existing test suite | 1 day | None — tests are unaffected |
| **Total** | **~3-4 days** | **No architectural risk** |

---

## What NOT to Do

- **Do NOT migrate to AgentCore Runtime** if your pipeline is deterministic rather than agentic — AgentCore Runtime adds latency and complexity for no benefit in that case.
- **Do NOT restructure your pipeline** — OTel instrumentation wraps your existing code, it doesn't replace it.
- **Do NOT change your streaming architecture** — spans are recorded after the response is generated, not in the streaming path.
- **Do NOT disable existing analytics** — they complement OTel traces (you can still use them for batch evaluations).

---

## Appendix A: Custom CloudWatch Logs Exporter

If not using the ADOT layer, here's a minimal exporter that writes spans directly to CloudWatch Logs in the OTLP JSON format AgentCore expects:

```python
import json
import boto3
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


class CloudWatchLogsExporter(SpanExporter):
    def __init__(self, log_group: str, region: str = "us-east-1"):
        self.log_group = log_group
        self.log_stream = "rag-chatbot-traces"
        self._client = boto3.client("logs", region_name=region)
        self._sequence_token = None
        self._ensure_log_group()

    def _ensure_log_group(self):
        try:
            self._client.create_log_group(logGroupName=self.log_group)
        except self._client.exceptions.ResourceAlreadyExistsException:
            pass
        try:
            self._client.create_log_stream(
                logGroupName=self.log_group, logStreamName=self.log_stream
            )
        except self._client.exceptions.ResourceAlreadyExistsException:
            pass

    def export(self, spans) -> SpanExportResult:
        log_events = []
        for span in spans:
            span_data = self._span_to_otlp(span)
            log_events.append({
                "timestamp": int(span.start_time / 1_000_000),
                "message": json.dumps(span_data),
            })
        if not log_events:
            return SpanExportResult.SUCCESS
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

    def _span_to_otlp(self, span) -> dict:
        """Convert span to OTLP JSON format."""
        ctx = span.get_span_context()
        return {
            "resourceSpans": [{
                "resource": {
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in (span.resource.attributes or {}).items()
                    ]
                },
                "scopeSpans": [{
                    "scope": {"name": "rag-chatbot"},
                    "spans": [{
                        "traceId": f"0x{ctx.trace_id:032x}",
                        "spanId": f"0x{ctx.span_id:016x}",
                        "parentSpanId": (
                            f"0x{span.parent.span_id:016x}" if span.parent else None
                        ),
                        "name": span.name,
                        "kind": span.kind.value if span.kind else 0,
                        "startTimeUnixNano": span.start_time,
                        "endTimeUnixNano": span.end_time,
                        "attributes": [
                            {"key": k, "value": {"stringValue": str(v)}}
                            for k, v in (span.attributes or {}).items()
                        ],
                        "status": {
                            "code": span.status.status_code.value if span.status else 0,
                        },
                    }],
                }],
            }]
        }

    def shutdown(self):
        pass
```

Register it during initialization:

```python
from opentelemetry.sdk.trace.export import BatchSpanProcessor

exporter = CloudWatchLogsExporter(log_group="/agentcore/evaluations/rag-demo")
provider.add_span_processor(BatchSpanProcessor(exporter))
```

---

## Appendix B: IAM Trust and Permissions Policies

**Trust policy (`trust-policy.json`):**

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Service": "bedrock-agentcore.amazonaws.com"
    },
    "Action": "sts:AssumeRole",
    "Condition": {
      "StringEquals": {
        "aws:SourceAccount": "YOUR_ACCOUNT_ID"
      },
      "ArnLike": {
        "aws:SourceArn": [
          "arn:aws:bedrock-agentcore:us-east-1:YOUR_ACCOUNT_ID:evaluator/*",
          "arn:aws:bedrock-agentcore:us-east-1:YOUR_ACCOUNT_ID:online-evaluation-config/*"
        ]
      }
    }
  }]
}
```

**Permissions policy (`permissions-policy.json`):**

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ReadTraces",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeLogGroups",
        "logs:GetQueryResults",
        "logs:StartQuery"
      ],
      "Resource": "*"
    },
    {
      "Sid": "WriteEvaluationResults",
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:us-east-1:YOUR_ACCOUNT_ID:log-group:/aws/bedrock-agentcore/evaluations/*"
    },
    {
      "Sid": "IndexPolicy",
      "Effect": "Allow",
      "Action": [
        "logs:DescribeIndexPolicies",
        "logs:PutIndexPolicy"
      ],
      "Resource": [
        "arn:aws:logs:us-east-1:YOUR_ACCOUNT_ID:log-group:aws/spans",
        "arn:aws:logs:us-east-1:YOUR_ACCOUNT_ID:log-group:aws/spans:*"
      ]
    },
    {
      "Sid": "InvokeModelsForEvaluation",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/*",
        "arn:aws:bedrock:us-east-1:YOUR_ACCOUNT_ID:inference-profile/*"
      ]
    }
  ]
}
```

---

## References

- [OpenTelemetry GenAI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/gen-ai-spans/) — attribute specification for `gen_ai.*`
- [AWS Distro for OpenTelemetry (ADOT) Lambda Layer](https://aws-otel.github.io/docs/getting-started/lambda) — managed OTel export for Lambda
- [Amazon Bedrock AgentCore Evaluations](https://docs.aws.amazon.com/bedrock/latest/userguide/agentcore-evaluations.html) — service documentation
- Demo repository: `rag-otel-demo` — working reference implementation
