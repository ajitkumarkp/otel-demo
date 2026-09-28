"""Configuration for the RAG observability demo."""

from dataclasses import dataclass, field


@dataclass
class BedrockConfig:
    """Amazon Bedrock model configuration."""

    region: str = "us-east-1"
    generation_model_id: str = "us.anthropic.claude-sonnet-4-6"
    embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    intent_model_id: str = "amazon.nova-lite-v1:0"
    embedding_dimensions: int = 1024
    max_tokens: int = 1024
    temperature: float = 0.3


@dataclass
class VectorStoreConfig:
    """Local vector store configuration."""

    collection_name: str = "product_docs"
    persist_directory: str = "./chroma_db"
    top_k: int = 5
    similarity_threshold: float = 0.5


@dataclass
class InstrumentationConfig:
    """OpenTelemetry instrumentation configuration."""

    service_name: str = "rag-chatbot"
    service_version: str = "0.1.0"
    # Exporter: "console", "otlp", "cloudwatch"
    exporter_type: str = "console"
    otlp_endpoint: str = "http://localhost:4317"
    # CloudWatch configuration
    cloudwatch_log_group: str = "/agentcore/evaluations/rag-demo"
    cloudwatch_region: str = "us-east-1"


@dataclass
class GuardrailConfig:
    """Guardrail configuration."""

    max_input_length: int = 2000
    blocked_topics: list[str] = field(
        default_factory=lambda: [
            "competitor products",
            "legal advice",
            "medical advice",
            "financial advice",
        ]
    )
    pii_patterns: list[str] = field(
        default_factory=lambda: [
            r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
            r"\b\d{16}\b",  # Credit card
            r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",  # Email
        ]
    )


@dataclass
class AppConfig:
    """Top-level application configuration."""

    bedrock: BedrockConfig = field(default_factory=BedrockConfig)
    vector_store: VectorStoreConfig = field(default_factory=VectorStoreConfig)
    instrumentation: InstrumentationConfig = field(default_factory=InstrumentationConfig)
    guardrail: GuardrailConfig = field(default_factory=GuardrailConfig)
