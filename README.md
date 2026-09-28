# RAG Chatbot — OTel + AgentCore Evaluations Demo

A proof-of-concept demonstrating how to add **OpenTelemetry instrumentation** to an existing RAG chatbot and connect it to **Amazon Bedrock AgentCore Evaluations** for automated quality monitoring — all **without migrating to AgentCore Runtime**.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            RAG Chatbot (Local)                           │
│                                                                         │
│  User Query                                                             │
│      │                                                                  │
│      ▼                                                                  │
│  ┌──────────┐   ┌──────────────┐   ┌────────────┐   ┌──────────────┐  │
│  │Guardrail │──▶│Intent Classif│──▶│Vector Store│──▶│LLM Generation│  │
│  │  Check   │   │  (Rule/LLM)  │   │ (ChromaDB) │   │(Claude Sonnet│  │
│  └──────────┘   └──────────────┘   └────────────┘   └──────────────┘  │
│       │                │                  │                  │          │
│       ▼                ▼                  ▼                  ▼          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              OpenTelemetry SDK (Spans + Attributes)              │   │
│  │  guardrail_check → intent_classification → vector_retrieval →   │   │
│  │  embedding_generation → llm_generation                          │   │
│  └──────────────────────────────────┬──────────────────────────────┘   │
│                                     │                                   │
└─────────────────────────────────────┼───────────────────────────────────┘
                                      │ Export traces
                                      ▼
                          ┌──────────────────────┐
                          │   CloudWatch Logs     │
                          │  /agentcore/evals/    │
                          │    rag-demo           │
                          └──────────┬───────────┘
                                     │ AgentCore reads traces
                                     ▼
                          ┌──────────────────────┐
                          │  AgentCore           │
                          │  Evaluations         │
                          │                      │
                          │  • Helpfulness       │
                          │  • Faithfulness      │
                          │  • Relevance         │
                          │  • Custom            │
                          └──────────┬───────────┘
                                     │ Scores
                                     ▼
                          ┌──────────────────────┐
                          │  CloudWatch          │
                          │  Observability       │
                          │  Dashboard           │
                          └──────────────────────┘
```

## Mapping to a Production Architecture

This demo runs a simplified pipeline locally. The table shows how each local
component maps to a typical production stack — swap in whatever your stack uses.

| Production Component (example) | Demo Equivalent |
|---------------------|-----------------|
| AWS Lambda / container service | Local Python process |
| Managed vector DB (Aurora pgvector, OpenSearch) | ChromaDB (local) |
| Conversation state store (DynamoDB) | In-memory dict |
| Amazon Bedrock (Claude Sonnet) | Same (Bedrock API) |
| Amazon Bedrock (Titan Embeddings) | Same (Bedrock API) |
| CloudWatch Logs | Same (or console exporter) |

## Prerequisites

- Python 3.11+
- AWS credentials configured (`aws configure` or environment variables)
- Access to Amazon Bedrock in your region with these models enabled:
  - `anthropic.claude-sonnet-4-20250514` (generation)
  - `amazon.titan-embed-text-v2:0` (embeddings)
- (Optional) `amazon.nova-lite-v1:0` if using LLM intent classification

## Quick Start

### 1. Install

```bash
cd rag-otel-demo
pip install -e .
```

Or with requirements:

```bash
pip install -r requirements.txt
pip install -e .
```

### 2. Run the Chatbot (Console Traces)

```bash
rag-demo
```

This starts the chatbot with traces printed to console. You'll see OTel spans for each pipeline stage.

### 3. Try Sample Queries

```
You: How do I create an account?
You: What subscription plans are available?
You: How do I authenticate with the API?
You: How is my data encrypted?
You: I can't log in — what should I check?
```

### 4. Export Traces to CloudWatch (for AgentCore Evaluations)

```bash
rag-demo --exporter cloudwatch --region us-east-1
```

### 5. Set Up AgentCore Evaluations

```bash
# Generate the setup script
rag-demo --setup-evaluations

# Or show the integration guide
rag-demo --show-guide
```

## CLI Options

```
rag-demo [OPTIONS]

Options:
  --exporter {console,otlp,cloudwatch}  Trace exporter type (default: console)
  --region REGION                        AWS region (default: us-east-1)
  --model MODEL_ID                       Bedrock generation model
  --log-group LOG_GROUP                  CloudWatch log group for traces
  --verbose, -v                          Show detailed OTel span output
  --show-guide                           Display the integration architecture guide
  --setup-evaluations                    Run AgentCore Evaluations setup wizard
```

### In-Chat Commands

| Command | Description |
|---------|-------------|
| `/help` | Show available commands |
| `/metrics` | Display conversation metrics |
| `/guide` | Show AgentCore Evaluations integration guide |
| `/new` | Start a new conversation |
| `/quit` | Exit the chatbot |

## OpenTelemetry Instrumentation Details

### Span Hierarchy

```
rag_pipeline (parent span)
├── guardrail_check
├── intent_classification
├── embedding_generation (query)
├── vector_retrieval
└── llm_generation
```

### Span Attributes

Each span records attributes following the [OpenTelemetry Gen AI Semantic Conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):

| Attribute | Span | Description |
|-----------|------|-------------|
| `gen_ai.request.model` | embedding, generation | Model ID used |
| `gen_ai.usage.input_tokens` | generation | Input token count |
| `gen_ai.usage.output_tokens` | generation | Output token count |
| `rag.intent.type` | intent_classification | Classified intent |
| `rag.intent.confidence` | intent_classification | Classification confidence |
| `rag.retrieval.documents_count` | vector_retrieval | Documents retrieved |
| `rag.retrieval.latency_ms` | vector_retrieval | Retrieval time |
| `rag.retrieval.top_score` | vector_retrieval | Best similarity score |
| `rag.guardrail.passed` | guardrail_check | Pass/fail result |
| `rag.guardrail.block_reason` | guardrail_check | Why input was blocked |
| `rag.conversation.id` | rag_pipeline | Conversation identifier |
| `rag.conversation.turn_number` | rag_pipeline | Turn within conversation |

### Exporter Options

1. **Console** (default): Prints span data to terminal — great for development
2. **OTLP**: Sends traces to any OTLP-compatible collector (Jaeger, Grafana, AWS ADOT)
3. **CloudWatch**: Writes structured trace JSON to CloudWatch Logs for AgentCore Evaluations

## AgentCore Evaluations Integration

### How It Works (No Migration Required)

1. **Instrument your agent** with OTel SDK (this demo shows how)
2. **Export traces** to a CloudWatch Log Group
3. **Create an online evaluation config** pointing to that log group
4. **AgentCore Evaluations** reads traces and scores each conversation using LLM-as-a-Judge

### Built-in Evaluators

| Evaluator | ID | What It Checks |
|-----------|----|-|
| Helpfulness | `Builtin.Helpfulness` | Was the response useful to the user? |
| Faithfulness | `Builtin.Faithfulness` | Is the response grounded in the retrieved context? |
| Relevance | `Builtin.Relevance` | Does it address the user's question? |
| Goal Success | `Builtin.GoalSuccessRate` | Did the agent achieve the user's goal? |
| Harmfulness | `Builtin.Harmfulness` | Is the response safe and appropriate? |

### Custom Evaluator

The demo includes a custom evaluator template that checks:

- ✅ Accuracy of steps, settings, and values against the retrieved context
- ✅ Appropriate caveats for account- or security-sensitive actions
- ✅ Responses stay grounded in the provided documentation
- ✅ Completeness — the answer fully addresses the question
- ✅ Professional, helpful tone for end users

### Setup Steps (AWS)

```bash
# 1. Ensure CloudWatch log group exists
aws logs create-log-group \
  --log-group-name /agentcore/evaluations/rag-demo

# 2. Enable Transaction Search in CloudWatch Console
#    Settings → Transaction Search → Enable

# 3. Create IAM execution role (see --setup-evaluations wizard)

# 4. Create online evaluation config
aws bedrock-agentcore-control create-online-evaluation-config \
  --online-evaluation-config-name "rag_chatbot_eval" \
  --description "Continuous evaluation of the RAG chatbot" \
  --rule '{"samplingConfig": {"samplingPercentage": 100.0}}' \
  --data-source-config '{"cloudWatchLogs": {"logGroupNames": ["/agentcore/evaluations/rag-demo"], "serviceNames": ["rag-chatbot"]}}' \
  --evaluators '[{"evaluatorId": "Builtin.Helpfulness"}, {"evaluatorId": "Builtin.Faithfulness"}, {"evaluatorId": "Builtin.Relevance"}]' \
  --evaluation-execution-role-arn "arn:aws:iam::ACCOUNT_ID:role/RAGEvaluationRole" \
  --enable-on-create

# 5. Run chatbot with CloudWatch export
rag-demo --exporter cloudwatch

# 6. View results in CloudWatch Observability Dashboard
```

## Project Structure

```
rag-otel-demo/
├── pyproject.toml                              # Package config
├── requirements.txt                            # Dependencies
├── README.md                                   # This file
└── src/rag_demo/
    ├── __init__.py
    ├── cli.py                                  # CLI interface
    ├── config.py                               # Configuration dataclasses
    ├── evaluations/
    │   ├── __init__.py
    │   └── agentcore_integration.py            # AgentCore Evaluations setup
    ├── instrumentation/
    │   ├── __init__.py
    │   ├── attributes.py                       # Span attribute constants
    │   └── tracing.py                          # OTel SDK setup + CW exporter
    ├── knowledge_base/
    │   ├── __init__.py
    │   └── product_docs.py                     # Sample product documentation
    └── pipeline/
        ├── __init__.py
        ├── generation.py                       # Bedrock Claude generation
        ├── guardrail.py                        # Input safety checks
        ├── intent.py                           # Query intent classification
        ├── rag_pipeline.py                     # Pipeline orchestrator
        └── vector_store.py                     # ChromaDB + Titan Embeddings
```

## Demo Walkthrough

### Phase 1: Show the Instrumented Chatbot (5 min)

```bash
rag-demo --verbose
```

1. Ask a few questions to show the chatbot working
2. Point out OTel spans being generated for each stage
3. Show the span attributes (model_id, token counts, latency)

### Phase 2: Show CloudWatch Integration (3 min)

```bash
rag-demo --exporter cloudwatch
```

1. Show traces appearing in CloudWatch Logs
2. Explain the structured format AgentCore Evaluations expects

### Phase 3: Connect to AgentCore Evaluations (5 min)

```bash
rag-demo --setup-evaluations
```

1. Walk through the setup wizard
2. Show the evaluation config being created
3. Show how it points to the CloudWatch log group

### Phase 4: Show the Value Proposition (2 min)

```bash
rag-demo --show-guide
```

Highlight:

- No migration to AgentCore Runtime needed
- Existing compute + vector store architecture stays the same
- Just add OTel SDK + export to CloudWatch
- Get automated quality scoring on every conversation
- Custom evaluators for product-specific quality criteria

## Key Points

1. **Zero Architecture Change**: Add instrumentation library, configure exporter. Done.
2. **Automated Quality Monitoring**: LLM-as-a-Judge scores every conversation.
3. **Custom Evaluators**: Define your own quality criteria (accuracy, safety, grounding).
4. **CloudWatch Native**: Results in CloudWatch dashboards alongside existing metrics.
5. **Scale**: Up to 1M input+output tokens/minute for evaluation.
6. **Framework Agnostic**: Works with any agent that exports OTel traces.

## Troubleshooting

### "Could not resolve model" error

Ensure the Bedrock models are enabled in your account for the specified region. Go to the Bedrock Console → Model access → Enable models.

### ChromaDB errors

```bash
pip install chromadb --upgrade
```

### CloudWatch export failures

Check that your AWS credentials have `logs:CreateLogGroup`, `logs:CreateLogStream`, and `logs:PutLogEvents` permissions.

### OTel import errors

```bash
pip install opentelemetry-api opentelemetry-sdk opentelemetry-exporter-otlp --upgrade
```

## Next Steps

- [ ] Add ADOT Collector sidecar for production-grade trace export
- [ ] Implement streaming responses with Claude
- [ ] Add reranking stage (Bedrock rerank model)
- [ ] Create CloudWatch dashboard template for evaluation metrics
- [ ] Add batch evaluation for regression testing in CI/CD
- [ ] Integrate with your existing conversation state store
