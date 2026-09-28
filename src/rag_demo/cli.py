"""CLI interface for the RAG chatbot demo.

Provides a rich terminal interface for interacting with the RAG chatbot
while showing OTel instrumentation in action.
"""

import argparse
import logging
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from rich.theme import Theme

from rag_demo.config import AppConfig, InstrumentationConfig
from rag_demo.evaluations.agentcore_integration import print_integration_guide
from rag_demo.instrumentation.tracing import setup_tracing
from rag_demo.pipeline.rag_pipeline import RAGPipeline

# Custom theme for the demo CLI
app_theme = Theme(
    {
        "app.accent": "bold blue",
        "app.heading": "bold white on blue",
        "app.info": "dim cyan",
        "app.success": "green",
        "app.warn": "yellow",
        "app.error": "bold red",
        "app.metrics": "dim magenta",
    }
)

console = Console(theme=app_theme)


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="rag-demo",
        description="RAG Chatbot with OpenTelemetry Instrumentation Demo",
    )
    parser.add_argument(
        "--exporter",
        choices=["console", "otlp", "cloudwatch"],
        default="console",
        help="OTel trace exporter type (default: console)",
    )
    parser.add_argument(
        "--region",
        default="us-east-1",
        help="AWS region for Bedrock and CloudWatch (default: us-east-1)",
    )
    parser.add_argument(
        "--model",
        default="us.anthropic.claude-sonnet-4-6",
        help="Bedrock model ID for generation",
    )
    parser.add_argument(
        "--log-group",
        default="/agentcore/evaluations/rag-demo",
        help="CloudWatch log group for trace export",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging (shows OTel span details)",
    )
    parser.add_argument(
        "--show-guide",
        action="store_true",
        help="Show the AgentCore Evaluations integration guide and exit",
    )
    parser.add_argument(
        "--setup-evaluations",
        action="store_true",
        help="Run AgentCore Evaluations setup (creates IAM role + eval config)",
    )
    return parser.parse_args()


def print_banner():
    """Display the demo banner."""
    banner = Text()
    banner.append("RAG Chatbot", style="bold blue")
    banner.append(" │ ", style="dim")
    banner.append("OTel", style="bold cyan")
    banner.append(" + ", style="dim")
    banner.append("AgentCore Evaluations", style="bold green")
    banner.append(" Demo", style="bold white")
    console.print(Panel(banner, border_style="blue", padding=(0, 2)))
    console.print()


def print_help():
    """Display available commands."""
    console.print("[app.info]Available commands:[/app.info]")
    console.print("  [bold]/help[/bold]      - Show this help message")
    console.print("  [bold]/metrics[/bold]   - Show conversation metrics")
    console.print("  [bold]/guide[/bold]     - Show AgentCore Evaluations integration guide")
    console.print("  [bold]/new[/bold]       - Start a new conversation")
    console.print("  [bold]/quit[/bold]      - Exit the chatbot")
    console.print()


def print_metrics(pipeline: RAGPipeline, conversation_id: str):
    """Display conversation metrics."""
    if conversation_id not in pipeline._conversations:
        console.print("[app.warn]No active conversation.[/app.warn]")
        return

    state = pipeline._conversations[conversation_id]
    console.print(Panel(
        f"[bold]Conversation ID:[/bold] {state.conversation_id}\n"
        f"[bold]Turns:[/bold] {state.turn_number}\n"
        f"[bold]History messages:[/bold] {len(state.history)}\n"
        f"[bold]Vector store docs:[/bold] {pipeline.vector_store.document_count}",
        title="📊 Conversation Metrics",
        border_style="magenta",
    ))


def run_setup_evaluations(config: AppConfig):
    """Run the AgentCore Evaluations setup process."""
    from rag_demo.evaluations.agentcore_integration import AgentCoreEvaluationsSetup

    console.print("[app.heading] AgentCore Evaluations Setup [/app.heading]")
    console.print()

    setup = AgentCoreEvaluationsSetup(config.instrumentation)

    console.print("[bold]Option 1:[/bold] Generate setup script (recommended for demo)")
    console.print("[bold]Option 2:[/bold] Run setup programmatically (requires AWS credentials)")
    console.print()

    choice = console.input("[app.info]Choose (1/2): [/app.info]")

    if choice == "1":
        script = setup.generate_setup_script()
        console.print(Panel(script, title="Setup Script", border_style="green"))
        console.print("[app.success]Copy and run this script in your terminal.[/app.success]")
    elif choice == "2":
        try:
            console.print("[app.info]Creating IAM role...[/app.info]")
            role_arn = setup.setup_evaluation_role()
            console.print(f"[app.success]✅ Role: {role_arn}[/app.success]")

            console.print("[app.info]Creating online evaluation config...[/app.info]")
            result = setup.create_online_evaluation(role_arn=role_arn)
            console.print(
                f"[app.success]✅ Evaluation config created: "
                f"{result.get('onlineEvaluationConfigId')}[/app.success]"
            )
        except Exception as e:
            console.print(f"[app.error]Setup failed: {e}[/app.error]")
            console.print("[app.warn]Ensure you have valid AWS credentials configured.[/app.warn]")
    else:
        console.print("[app.warn]Invalid choice.[/app.warn]")


def main():
    """Main entry point for the CLI."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.WARNING
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Handle special modes
    if args.show_guide:
        print_integration_guide()
        return

    # Build configuration
    config = AppConfig()
    config.bedrock.region = args.region
    config.bedrock.generation_model_id = args.model
    config.instrumentation.exporter_type = args.exporter
    config.instrumentation.cloudwatch_log_group = args.log_group
    config.instrumentation.cloudwatch_region = args.region

    if args.setup_evaluations:
        run_setup_evaluations(config)
        return

    # Initialize OpenTelemetry tracing
    print_banner()
    console.print(f"[app.info]Trace exporter: {args.exporter}[/app.info]")
    console.print(f"[app.info]Region: {args.region}[/app.info]")
    console.print(f"[app.info]Model: {args.model}[/app.info]")
    console.print()

    try:
        tracer = setup_tracing(config.instrumentation)
    except Exception as e:
        console.print(f"[app.error]Failed to initialize tracing: {e}[/app.error]")
        console.print("[app.warn]Continuing without trace export...[/app.warn]")

    # Initialize the RAG pipeline
    console.print("[app.info]Initializing RAG pipeline...[/app.info]")
    try:
        pipeline = RAGPipeline(config)
        if not pipeline.initialize():
            console.print("[app.error]Failed to initialize pipeline. Check AWS credentials.[/app.error]")
            sys.exit(1)
    except Exception as e:
        console.print(f"[app.error]Pipeline initialization failed: {e}[/app.error]")
        console.print(
            "[app.warn]Ensure you have:\n"
            "  1. Valid AWS credentials configured\n"
            "  2. Access to Amazon Bedrock in the specified region\n"
            "  3. Titan Embeddings and Claude models enabled[/app.warn]"
        )
        sys.exit(1)

    console.print(
        f"[app.success]✅ Pipeline ready! "
        f"{pipeline.vector_store.document_count} documents loaded.[/app.success]"
    )
    console.print()

    print_help()

    # Start conversation
    conversation = pipeline.get_or_create_conversation()
    console.print(
        f"[app.info]Conversation: {conversation.conversation_id[:8]}...[/app.info]"
    )
    console.print()

    # Chat loop
    while True:
        try:
            user_input = console.input("[bold blue]You:[/bold blue] ").strip()

            if not user_input:
                continue

            # Handle commands
            if user_input.startswith("/"):
                command = user_input.lower()
                if command == "/quit" or command == "/exit":
                    console.print("[app.info]Goodbye! 👋[/app.info]")
                    break
                elif command == "/help":
                    print_help()
                    continue
                elif command == "/metrics":
                    print_metrics(pipeline, conversation.conversation_id)
                    continue
                elif command == "/guide":
                    print_integration_guide()
                    continue
                elif command == "/new":
                    conversation = pipeline.get_or_create_conversation()
                    console.print(
                        f"[app.success]New conversation: "
                        f"{conversation.conversation_id[:8]}...[/app.success]"
                    )
                    continue
                else:
                    console.print(f"[app.warn]Unknown command: {user_input}[/app.warn]")
                    print_help()
                    continue

            # Process the query
            console.print()
            with console.status("[app.info]Thinking...[/app.info]"):
                response = pipeline.process_query(
                    query=user_input,
                    conversation_id=conversation.conversation_id,
                )

            # Display response
            console.print("[bold blue]Assistant:[/bold blue]")
            console.print(Markdown(response.answer))
            console.print()

            # Show metadata
            console.print(
                f"[app.metrics]  ⏱ {response.latency_ms:.0f}ms │ "
                f"🎯 {response.intent} │ "
                f"📄 {response.docs_retrieved} docs │ "
                f"💬 turn {response.turn_number}[/app.metrics]"
            )

            if response.blocked:
                console.print(
                    f"[app.warn]  ⚠️ Blocked: {response.block_reason}[/app.warn]"
                )
            console.print()

        except KeyboardInterrupt:
            console.print("\n[app.info]Goodbye! 👋[/app.info]")
            break
        except EOFError:
            break
        except Exception as e:
            console.print(f"[app.error]Error: {e}[/app.error]")
            if args.verbose:
                console.print_exception()
            console.print()


if __name__ == "__main__":
    main()
