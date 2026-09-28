"""Run on-demand AgentCore Evaluations against recent RAG pipeline traces.

Usage:
    python run_evaluations.py
"""

import boto3
import json
from datetime import datetime, timezone

logs_client = boto3.client("logs", region_name="us-east-1")
eval_client = boto3.client("bedrock-agentcore", region_name="us-east-1")

LOG_GROUP = "/agentcore/evaluations/rag-demo"
LOG_STREAM = "rag-chatbot-traces"
EVALUATORS = ["Builtin.Helpfulness", "Builtin.Correctness", "Builtin.GoalSuccessRate"]


def ns_to_iso(ns):
    dt = datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


KIND_MAP = {0: "SPAN_KIND_INTERNAL", 1: "SPAN_KIND_SERVER", 2: "SPAN_KIND_CLIENT"}
STATUS_MAP = {0: "STATUS_CODE_UNSET", 1: "STATUS_CODE_OK", 2: "STATUS_CODE_ERROR"}


def get_traces():
    """Fetch all trace spans from CloudWatch and group by trace ID."""
    traces = {}
    kwargs = {
        "logGroupName": LOG_GROUP,
        "logStreamName": LOG_STREAM,
        "startFromHead": True,
    }

    # Paginate through all events
    while True:
        resp = logs_client.get_log_events(**kwargs)
        events = resp.get("events", [])
        if not events:
            break

        for event in events:
            msg = json.loads(event["message"])
            span = msg["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            tid = span["traceId"].replace("0x", "")
            if tid not in traces:
                traces[tid] = []
            traces[tid].append(msg)

        # CloudWatch pagination: nextForwardToken stays the same when no more data
        next_token = resp.get("nextForwardToken")
        if next_token == kwargs.get("nextToken"):
            break
        kwargs["nextToken"] = next_token

    return traces


def get_user_query(span):
    """Extract user query from a span's events (gen_ai.user.message)."""
    # Try events first (AgentCore-compatible format)
    for ev in span.get("events", []):
        if ev["name"] == "gen_ai.user.message":
            for a in ev.get("attributes", []):
                if a["key"] == "content":
                    try:
                        content = json.loads(a["value"]["stringValue"])
                        if isinstance(content, list) and content:
                            return content[0].get("text", "?")[:80]
                    except (json.JSONDecodeError, KeyError):
                        return a["value"]["stringValue"][:60]
    # Fall back to attributes
    for attr in span.get("attributes", []):
        if attr["key"] == "gen_ai.input.messages":
            try:
                messages = json.loads(attr["value"]["stringValue"])
                if isinstance(messages, list) and messages:
                    return messages[0].get("content", "?")[:80]
            except (json.JSONDecodeError, KeyError):
                return attr["value"]["stringValue"][:60]
    return "?"


def flatten_trace(entries):
    """Convert OTLP-format entries to flat span format for evaluate API."""
    flat = []
    for entry in entries:
        res = entry["resourceSpans"][0]["resource"]
        scope_spans = entry["resourceSpans"][0]["scopeSpans"][0]
        scope = scope_spans.get("scope", {})
        span = scope_spans["spans"][0]
        resource_attrs = {
            a["key"]: a["value"]["stringValue"]
            for a in res.get("attributes", [])
        }
        span_attrs = {
            a["key"]: a["value"]["stringValue"]
            for a in span.get("attributes", [])
        }
        status_code = span.get("status", {}).get("code", 0)
        events = []
        for ev in span.get("events", []):
            ev_attrs = {
                a["key"]: a["value"]["stringValue"]
                for a in ev.get("attributes", [])
            }
            events.append({
                "name": ev["name"],
                "timestamp": ns_to_iso(ev["timeUnixNano"]),
                "attributes": ev_attrs,
            })

        flat.append({
            "trace_id": span["traceId"].replace("0x", ""),
            "span_id": span["spanId"].replace("0x", ""),
            "parent_span_id": (span.get("parentSpanId") or "").replace("0x", "") or None,
            "name": span["name"],
            "kind": KIND_MAP.get(span.get("kind", 0), "SPAN_KIND_INTERNAL"),
            "start_time": ns_to_iso(span["startTimeUnixNano"]),
            "end_time": ns_to_iso(span["endTimeUnixNano"]),
            "attributes": span_attrs,
            "events": events,
            "resource": resource_attrs,
            "status": {
                "code": STATUS_MAP.get(status_code, "STATUS_CODE_UNSET"),
                "message": span.get("status", {}).get("message", ""),
            },
            "scope": scope,
        })
    return flat


def evaluate_trace(flattened, evaluator_id):
    """Run a single evaluator against a trace."""
    try:
        response = eval_client.evaluate(
            evaluatorId=evaluator_id,
            evaluationInput={"sessionSpans": flattened},
        )
        r = response.get("evaluationResults", [{}])[0]
        if r.get("errorCode"):
            return {"status": "error", "error": r["errorCode"]}
        return {
            "status": "success",
            "score": r.get("score"),
            "explanation": r.get("explanation", ""),
        }
    except Exception as e:
        return {"status": "exception", "error": str(e)[:100]}


def main():
    print("=" * 80)
    print("  RAG Chatbot — AgentCore Evaluations Report")
    print("=" * 80)
    print()

    traces = get_traces()

    # Find pipeline traces by looking for the chat span (LLM generation)
    # which contains gen_ai.user.message event (the user query)
    pipeline_traces = []
    for tid, entries in traces.items():
        for entry in entries:
            span = entry["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
            if span["name"] == "chat":
                # Check for gen_ai.user.message event or gen_ai.input.messages attr
                has_user_msg = False
                for ev in span.get("events", []):
                    if ev["name"] == "gen_ai.user.message":
                        has_user_msg = True
                        break
                if not has_user_msg:
                    attrs = {a["key"]: a["value"]["stringValue"] for a in span.get("attributes", [])}
                    has_user_msg = "gen_ai.input.messages" in attrs
                if has_user_msg:
                    query = get_user_query(span)
                    pipeline_traces.append((tid, query))
                    break

    print(f"  Sessions found: {len(pipeline_traces)}")
    print(f"  Evaluators: {', '.join(EVALUATORS)}")
    print()
    print("-" * 80)

    for i, (tid, query) in enumerate(pipeline_traces, 1):
        print(f"\n  [{i}] \"{query}\"")
        print(f"      Trace: {tid[:16]}...")
        flattened = flatten_trace(traces[tid])

        for eval_id in EVALUATORS:
            result = evaluate_trace(flattened, eval_id)
            eval_name = eval_id.replace("Builtin.", "")

            if result["status"] == "success":
                expl = result["explanation"][:120]
                print(f"      ✅ {eval_name}: {expl}")
            else:
                print(f"      ❌ {eval_name}: {result.get('error', 'unknown')}")

    print()
    print("=" * 80)
    print(f"  Total: {len(pipeline_traces)} sessions × {len(EVALUATORS)} evaluators")
    print(f"       = {len(pipeline_traces) * len(EVALUATORS)} evaluations completed")
    print("=" * 80)


if __name__ == "__main__":
    main()
