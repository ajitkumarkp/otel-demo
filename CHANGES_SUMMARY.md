# Changes Required for CloudWatch Logging + AgentCore On-Demand Evaluations

Summary of all changes needed to get the right OTel traces into CloudWatch Logs and run on-demand evaluations using Amazon Bedrock AgentCore.

---

## 1. Custom CloudWatch Logs Exporter (the core plumbing)

**File:** `src/rag_demo/instrumentation/tracing.py`

The OTel SDK doesn't ship with a native CloudWatch Logs span exporter, so a custom `CloudWatchLogsExporter` was built that:

- Creates the log group (`/agentcore/evaluations/rag-demo`) and log stream on startup
- Converts each OTel span into the **OTLP JSON format** AgentCore expects — specifically the `resourceSpans → scopeSpans → spans` nested structure with all attributes as `{key, value: {stringValue}}` pairs
- Includes **span events** (used to encode user/assistant messages on the span)
- Handles timestamp conversion (nanoseconds → milliseconds for the CloudWatch PutLogEvents API)
- Manages sequence tokens for ordered log delivery

---

## 2. gen_ai Semantic Convention Attributes

**Files:** `src/rag_demo/instrumentation/attributes.py`, `src/rag_demo/pipeline/generation.py`

AgentCore Evaluations expects specific attribute names to identify what to evaluate. The key additions on the LLM generation span:

```python
span.set_attribute("gen_ai.operation.name", "chat")
span.set_attribute("gen_ai.system", "strands-agents")
span.set_attribute("gen_ai.request.model", model_id)
```

In addition, the user query and assistant response are recorded as span events
(`gen_ai.user.message` and `gen_ai.choice`) so AgentCore has the actual input and
output to evaluate. Without these, AgentCore has no user query or response to score.

---

## 3. Configuration to Switch Exporter Mode

**File:** `src/rag_demo/config.py`

The `InstrumentationConfig` provides a `cloudwatch` exporter type plus the log group and region:

```python
exporter_type: str = "console"  # "console", "otlp", or "cloudwatch"
cloudwatch_log_group: str = "/agentcore/evaluations/rag-demo"
cloudwatch_region: str = "us-east-1"
```

When `exporter_type = "cloudwatch"`, the tracing setup registers the custom `CloudWatchLogsExporter` as a `BatchSpanProcessor`.

---

## 4. On-Demand Evaluation Runner

**File:** `run_evaluations.py`

This script does the actual "run eval" flow:

1. **Fetches traces** from CloudWatch Logs (`get_log_events` on the log group/stream)
2. **Groups spans by trace ID** — each conversation is one trace with multiple spans
3. **Identifies pipeline traces** by looking for the generation (`chat`) span that carries the `gen_ai.user.message` event
4. **Flattens the OTLP JSON** into the format the `bedrock-agentcore` evaluate API expects:
   - Converts nanosecond timestamps to ISO 8601 strings
   - Normalizes span kind enums (`SPAN_KIND_INTERNAL`, `SPAN_KIND_SERVER`, etc.)
   - Normalizes status code enums (`STATUS_CODE_OK`, `STATUS_CODE_ERROR`, etc.)
   - Extracts events with their attributes
5. **Calls `evaluate()`** for each trace against each evaluator:
   - `Builtin.Helpfulness`
   - `Builtin.Correctness`
   - `Builtin.GoalSuccessRate`

---

## 5. AgentCore Evaluations Setup (IAM + Config)

**File:** `src/rag_demo/evaluations/agentcore_integration.py`

For continuous (online) evaluation, the setup creates:

- An **IAM execution role** with trust policy for `bedrock-agentcore.amazonaws.com`, with permissions to:
  - Read CloudWatch Logs (`logs:StartQuery`, `logs:GetQueryResults`, `logs:DescribeLogGroups`)
  - Write evaluation results (`logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` to `/aws/bedrock-agentcore/evaluations/*`)
  - Manage index policies (`logs:DescribeIndexPolicies`, `logs:PutIndexPolicy` on `aws/spans`)
  - Invoke Bedrock models (`bedrock:InvokeModel`, `bedrock:InvokeModelWithResponseStream`)
- An **online evaluation config** via `create_online_evaluation_config()` pointing at the log group and service name, with a sampling percentage and chosen evaluators
- Optionally a **custom evaluator** with an LLM-as-Judge prompt template checking domain accuracy, appropriate caveats for sensitive actions, and grounding in the retrieved context

---

## Quick Reference Table

| Change | Why |
|--------|-----|
| Custom `CloudWatchLogsExporter` writing OTLP-format JSON to CW Logs | AgentCore reads traces from CW Logs, not from Jaeger/OTLP collectors |
| `gen_ai.user.message` / `gen_ai.choice` events on spans | AgentCore needs the actual user query and assistant response to evaluate |
| Log group: `/agentcore/evaluations/rag-demo` | The path AgentCore is configured to read from |
| `run_evaluations.py` flattening traces and calling `bedrock-agentcore evaluate()` | The actual on-demand eval invocation against stored traces |
| IAM role with CW Logs read + Bedrock invoke permissions | Required for the evaluation service to access traces and run LLM-as-Judge |

---

## Results

See `EVALUATION_REPORT.md` for a full run across 13 sessions (including 3 intentionally bad responses used to demonstrate detection).
