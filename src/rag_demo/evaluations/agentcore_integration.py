"""Amazon Bedrock AgentCore Evaluations integration.

This module provides:
1. Setup automation for connecting OTel traces to AgentCore Evaluations
2. Online evaluation configuration management
3. Custom evaluator creation for product-specific quality metrics
4. Results retrieval and display

Architecture:
    RAG Chatbot (OTel SDK) → CloudWatch Logs → AgentCore Evaluations
                                                     ↓
                                              Evaluation Results (CloudWatch Metrics)

The key insight: AgentCore Evaluations reads OTel traces from CloudWatch Logs.
No migration to AgentCore Runtime is required. Any agent that exports OTel traces
to CloudWatch can be evaluated.
"""

import json
import logging
import time
from typing import Optional

import boto3

from rag_demo.config import InstrumentationConfig

logger = logging.getLogger(__name__)


# Built-in evaluator IDs available in AgentCore Evaluations
BUILTIN_EVALUATORS = {
    "helpfulness": "Builtin.Helpfulness",
    "goal_success": "Builtin.GoalSuccessRate",
    "tool_accuracy": "Builtin.ToolSelectionQuality",
    "faithfulness": "Builtin.Faithfulness",
    "harmfulness": "Builtin.Harmfulness",
    "answer_relevance": "Builtin.Relevance",
}

# Default evaluators for the RAG demo
DEFAULT_EVALUATORS = [
    "Builtin.Helpfulness",
    "Builtin.Faithfulness",
    "Builtin.Relevance",
]


class AgentCoreEvaluationsSetup:
    """Manages the setup and configuration of AgentCore Evaluations.

    This class handles:
    - IAM role creation for the evaluation service
    - Online evaluation config creation
    - Custom evaluator creation for product-specific metrics
    - Results querying
    """

    def __init__(self, config: InstrumentationConfig, account_id: Optional[str] = None):
        self.config = config
        self.region = config.cloudwatch_region
        self._account_id = account_id
        self._agentcore_client = None
        self._iam_client = None
        self._logs_client = None

    @property
    def account_id(self) -> str:
        """Get the AWS account ID."""
        if not self._account_id:
            sts = boto3.client("sts", region_name=self.region)
            self._account_id = sts.get_caller_identity()["Account"]
        return self._account_id

    @property
    def agentcore_client(self):
        """Get or create the bedrock-agentcore-control client."""
        if not self._agentcore_client:
            self._agentcore_client = boto3.client(
                "bedrock-agentcore-control", region_name=self.region
            )
        return self._agentcore_client

    @property
    def iam_client(self):
        """Get or create IAM client."""
        if not self._iam_client:
            self._iam_client = boto3.client("iam", region_name=self.region)
        return self._iam_client

    @property
    def logs_client(self):
        """Get or create CloudWatch Logs client."""
        if not self._logs_client:
            self._logs_client = boto3.client("logs", region_name=self.region)
        return self._logs_client

    def setup_evaluation_role(self, role_name: str = "RAGEvaluationRole") -> str:
        """Create the IAM execution role required by AgentCore Evaluations.

        The role allows the service to:
        - Read traces from CloudWatch Logs
        - Write evaluation results
        - Invoke Bedrock models for evaluation

        Args:
            role_name: Name for the IAM role.

        Returns:
            The ARN of the created/existing role.
        """
        trust_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "TrustPolicyStatement",
                    "Effect": "Allow",
                    "Principal": {
                        "Service": "bedrock-agentcore.amazonaws.com"
                    },
                    "Action": "sts:AssumeRole",
                    "Condition": {
                        "StringEquals": {
                            "aws:SourceAccount": self.account_id,
                            "aws:ResourceAccount": self.account_id,
                        },
                        "ArnLike": {
                            "aws:SourceArn": [
                                f"arn:aws:bedrock-agentcore:{self.region}:{self.account_id}:evaluator/*",
                                f"arn:aws:bedrock-agentcore:{self.region}:{self.account_id}:online-evaluation-config/*",
                            ]
                        },
                    },
                }
            ],
        }

        permissions_policy = {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Sid": "CloudWatchLogReadStatement",
                    "Effect": "Allow",
                    "Action": [
                        "logs:DescribeLogGroups",
                        "logs:GetQueryResults",
                        "logs:StartQuery",
                    ],
                    "Resource": "*",
                },
                {
                    "Sid": "CloudWatchLogWriteStatement",
                    "Effect": "Allow",
                    "Action": [
                        "logs:CreateLogGroup",
                        "logs:CreateLogStream",
                        "logs:PutLogEvents",
                    ],
                    "Resource": (
                        f"arn:aws:logs:{self.region}:{self.account_id}"
                        ":log-group:/aws/bedrock-agentcore/evaluations/*"
                    ),
                },
                {
                    "Sid": "CloudWatchIndexPolicyStatement",
                    "Effect": "Allow",
                    "Action": [
                        "logs:DescribeIndexPolicies",
                        "logs:PutIndexPolicy",
                    ],
                    "Resource": [
                        f"arn:aws:logs:{self.region}:{self.account_id}:log-group:aws/spans",
                        f"arn:aws:logs:{self.region}:{self.account_id}:log-group:aws/spans:*",
                    ],
                },
                {
                    "Sid": "BedrockInvokeStatement",
                    "Effect": "Allow",
                    "Action": [
                        "bedrock:InvokeModel",
                        "bedrock:InvokeModelWithResponseStream",
                    ],
                    "Resource": [
                        f"arn:aws:bedrock:{self.region}::foundation-model/*",
                        f"arn:aws:bedrock:{self.region}:{self.account_id}:inference-profile/*",
                    ],
                },
            ],
        }

        try:
            # Check if role exists
            response = self.iam_client.get_role(RoleName=role_name)
            role_arn = response["Role"]["Arn"]
            logger.info(f"IAM role already exists: {role_arn}")
            return role_arn
        except self.iam_client.exceptions.NoSuchEntityException:
            pass

        # Create role
        response = self.iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description="Execution role for AgentCore Evaluations - RAG demo",
        )
        role_arn = response["Role"]["Arn"]

        # Attach inline policy
        self.iam_client.put_role_policy(
            RoleName=role_name,
            PolicyName="AgentCoreEvaluationsPermissions",
            PolicyDocument=json.dumps(permissions_policy),
        )

        logger.info(f"Created IAM role: {role_arn}")

        # Wait for role propagation
        time.sleep(10)
        return role_arn

    def create_online_evaluation(
        self,
        config_name: str = "rag_chatbot_eval",
        evaluator_ids: Optional[list[str]] = None,
        sampling_percentage: float = 100.0,
        role_arn: Optional[str] = None,
    ) -> dict:
        """Create an online evaluation configuration.

        This tells AgentCore Evaluations to continuously monitor traces from
        the RAG chatbot's CloudWatch log group and score them using the
        specified evaluators.

        Args:
            config_name: Name for the evaluation config (underscores only).
            evaluator_ids: List of evaluator IDs to apply. Defaults to standard set.
            sampling_percentage: Percentage of traces to evaluate (0.01-100).
            role_arn: IAM role ARN. If None, creates one automatically.

        Returns:
            API response dict with config ID and status.
        """
        if evaluator_ids is None:
            evaluator_ids = DEFAULT_EVALUATORS

        if role_arn is None:
            role_arn = self.setup_evaluation_role()

        evaluators = [{"evaluatorId": eid} for eid in evaluator_ids]

        response = self.agentcore_client.create_online_evaluation_config(
            onlineEvaluationConfigName=config_name,
            description=(
                "Continuous evaluation of the RAG chatbot. "
                "Monitors helpfulness, faithfulness, and relevance of responses."
            ),
            rule={
                "samplingConfig": {"samplingPercentage": sampling_percentage}
            },
            dataSourceConfig={
                "cloudWatchLogs": {
                    "logGroupNames": [self.config.cloudwatch_log_group],
                    "serviceNames": [self.config.service_name],
                }
            },
            evaluators=evaluators,
            evaluationExecutionRoleArn=role_arn,
            enableOnCreate=True,
        )

        logger.info(
            f"Created online evaluation: {response.get('onlineEvaluationConfigId')}"
        )
        return response

    def create_custom_evaluator(
        self,
        evaluator_name: str = "Response_Quality",
        role_arn: Optional[str] = None,
    ) -> dict:
        """Create a custom evaluator for product-specific quality metrics.

        This evaluator checks:
        - Accuracy of steps, settings, and values
        - Appropriate caveats for sensitive actions
        - Grounding in the provided documentation
        - Completeness of the answer

        Args:
            evaluator_name: Name for the custom evaluator.
            role_arn: IAM role ARN for the evaluator.

        Returns:
            API response with evaluator ID.
        """
        if role_arn is None:
            role_arn = self.setup_evaluation_role()

        prompt_template = """You are evaluating a product support assistant's response quality.

Given the following interaction:
- User Query: {{input}}
- Assistant Response: {{output}}
- Retrieved Context: {{context}}

Evaluate the response on these criteria:
1. ACCURACY: Are the steps, settings, and values correct per the context?
2. SAFETY: Does the response include appropriate caveats for account- or security-sensitive actions?
3. GROUNDING: Does the response avoid claims not supported by the retrieved context?
4. COMPLETENESS: Does the response fully address the user's question?
5. TONE: Is the response professional and helpful for an end user?

Score from 1-5 where:
5 = Excellent: All criteria met perfectly
4 = Good: Minor issues in one area
3 = Acceptable: Some issues but fundamentally helpful
2 = Poor: Significant issues in multiple areas
1 = Unacceptable: Dangerous, incorrect, or unhelpful

Provide your evaluation as JSON:
{
  "score": <1-5>,
  "reasoning": "<detailed explanation>",
  "accuracy_issues": [],
  "safety_concerns": [],
  "improvement_suggestions": []
}"""

        response = self.agentcore_client.create_evaluator(
            evaluatorName=evaluator_name,
            description="Custom evaluator for product support assistant response quality",
            evaluatorConfig={
                "llmAsJudge": {
                    "promptTemplate": prompt_template,
                }
            },
        )

        logger.info(f"Created custom evaluator: {response.get('evaluatorId')}")
        return response

    def get_evaluation_results(self, config_name: str = "rag_chatbot_eval") -> dict:
        """Retrieve evaluation results from CloudWatch.

        Results are stored in CloudWatch metrics and logs by AgentCore Evaluations.

        Args:
            config_name: The online evaluation config name.

        Returns:
            Dict with evaluation results and metrics.
        """
        try:
            response = self.agentcore_client.get_online_evaluation_config(
                onlineEvaluationConfigName=config_name
            )

            status = response.get("status", "UNKNOWN")
            config_id = response.get("onlineEvaluationConfigId", "")

            # Query CloudWatch for evaluation metrics
            cloudwatch = boto3.client("cloudwatch", region_name=self.region)
            metrics_response = cloudwatch.get_metric_statistics(
                Namespace="AWS/BedrockAgentCore/Evaluations",
                MetricName="EvaluationScore",
                Dimensions=[
                    {"Name": "ConfigName", "Value": config_name},
                ],
                StartTime=time.time() - 86400,  # Last 24 hours
                EndTime=time.time(),
                Period=3600,
                Statistics=["Average", "Minimum", "Maximum"],
            )

            return {
                "config_name": config_name,
                "config_id": config_id,
                "status": status,
                "metrics": metrics_response.get("Datapoints", []),
            }
        except Exception as e:
            logger.error(f"Failed to get evaluation results: {e}")
            return {"error": str(e)}

    def generate_setup_script(self) -> str:
        """Generate a shell script that sets up AgentCore Evaluations.

        Returns a ready-to-run script for the demo environment.
        """
        return f"""#!/bin/bash
# AgentCore Evaluations Setup Script for the RAG Demo
# This script configures the evaluation pipeline:
#   RAG Chatbot (OTel) → CloudWatch Logs → AgentCore Evaluations

set -e

REGION="{self.region}"
LOG_GROUP="{self.config.cloudwatch_log_group}"
SERVICE_NAME="{self.config.service_name}"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
ROLE_NAME="RAGEvaluationRole"

echo "🔧 Setting up AgentCore Evaluations for the RAG Demo"
echo "   Region: $REGION"
echo "   Log Group: $LOG_GROUP"
echo "   Service Name: $SERVICE_NAME"
echo ""

# Step 1: Ensure log group exists
echo "📋 Step 1: Verifying CloudWatch Log Group..."
aws logs create-log-group --log-group-name "$LOG_GROUP" --region "$REGION" 2>/dev/null || true
echo "   ✅ Log group ready: $LOG_GROUP"

# Step 2: Enable Transaction Search (required for AgentCore Evaluations)
echo ""
echo "📋 Step 2: Enable Transaction Search in CloudWatch..."
echo "   ⚠️  Manual step required:"
echo "   1. Go to CloudWatch Console → Settings → Transaction Search"
echo "   2. Enable Transaction Search for your account"
echo "   3. This allows AgentCore Evaluations to query trace data"
echo ""

# Step 3: Create IAM role
echo "📋 Step 3: Creating IAM Execution Role..."
TRUST_POLICY=$(cat <<EOF
{{
  "Version": "2012-10-17",
  "Statement": [{{
    "Effect": "Allow",
    "Principal": {{"Service": "bedrock-agentcore.amazonaws.com"}},
    "Action": "sts:AssumeRole",
    "Condition": {{
      "StringEquals": {{
        "aws:SourceAccount": "$ACCOUNT_ID",
        "aws:ResourceAccount": "$ACCOUNT_ID"
      }}
    }}
  }}]
}}
EOF
)

aws iam create-role \\
  --role-name "$ROLE_NAME" \\
  --assume-role-policy-document "$TRUST_POLICY" \\
  --description "AgentCore Evaluations role for the RAG demo" \\
  --region "$REGION" 2>/dev/null || echo "   Role already exists"

ROLE_ARN="arn:aws:iam::$ACCOUNT_ID:role/$ROLE_NAME"
echo "   ✅ Role: $ROLE_ARN"

# Step 4: Create online evaluation configuration
echo ""
echo "📋 Step 4: Creating Online Evaluation Configuration..."
aws bedrock-agentcore-control create-online-evaluation-config \\
  --online-evaluation-config-name "rag_chatbot_eval" \\
  --description "Continuous evaluation of the RAG chatbot" \\
  --rule '{{"samplingConfig": {{"samplingPercentage": 100.0}}}}' \\
  --data-source-config '{{"cloudWatchLogs": {{"logGroupNames": ["'$LOG_GROUP'"], "serviceNames": ["'$SERVICE_NAME'"]}}}}' \\
  --evaluators '[{{"evaluatorId": "Builtin.Helpfulness"}}, {{"evaluatorId": "Builtin.Faithfulness"}}, {{"evaluatorId": "Builtin.Relevance"}}]' \\
  --evaluation-execution-role-arn "$ROLE_ARN" \\
  --enable-on-create \\
  --region "$REGION"

echo "   ✅ Online evaluation created!"
echo ""
echo "🎉 Setup complete! AgentCore Evaluations will now:"
echo "   1. Read OTel traces from: $LOG_GROUP"
echo "   2. Evaluate 100% of conversations"
echo "   3. Score on: Helpfulness, Faithfulness, Relevance"
echo "   4. Results visible in CloudWatch Observability dashboard"
echo ""
echo "💡 Run the chatbot to generate traces:"
echo "   rag-demo --exporter cloudwatch"
"""


def print_integration_guide():
    """Print a guide explaining the OTel → AgentCore Evaluations integration."""
    guide = """
╔══════════════════════════════════════════════════════════════════════════╗
║        OTel → AgentCore Evaluations Integration Guide                 ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                        ║
║  ARCHITECTURE:                                                         ║
║                                                                        ║
║  ┌─────────────┐    OTel    ┌──────────────┐    reads    ┌──────────┐ ║
║  │  RAG        │──traces──▶│  CloudWatch   │◀──────────│ AgentCore │ ║
║  │  Chatbot    │           │  Logs         │           │ Evals     │ ║
║  └─────────────┘           └──────────────┘           └──────────┘  ║
║       │                                                     │         ║
║       │ gen_ai.*                                           │ scores   ║
║       │ attributes                                         ▼         ║
║       │                                            ┌──────────────┐  ║
║       └────────────────────────────────────────────│  CloudWatch  │  ║
║                                                    │  Dashboard   │  ║
║                                                    └──────────────┘  ║
║                                                                        ║
║  KEY POINTS:                                                           ║
║                                                                        ║
║  1. NO MIGRATION REQUIRED                                              ║
║     Your agent stays where it is. Only add OTel instrumentation        ║
║     and export traces to CloudWatch Logs.                              ║
║                                                                        ║
║  2. WHAT GETS EVALUATED                                                ║
║     AgentCore Evaluations reads the OTel traces (following gen_ai      ║
║     semantic conventions) and scores each conversation turn using       ║
║     LLM-as-a-Judge.                                                    ║
║                                                                        ║
║  3. BUILT-IN EVALUATORS                                                ║
║     • Builtin.Helpfulness - Was the response useful?                   ║
║     • Builtin.Faithfulness - Is the response grounded in context?      ║
║     • Builtin.Relevance - Does it address the user's question?         ║
║     • Builtin.GoalSuccessRate - Did the agent achieve the goal?        ║
║     • Builtin.Harmfulness - Is the response safe?                      ║
║                                                                        ║
║  4. CUSTOM EVALUATORS                                                  ║
║     Create product-specific evaluators that check:                     ║
║     • Accuracy of steps, settings, and values                          ║
║     • Appropriate caveats for sensitive actions                        ║
║     • Grounding in the provided documentation                          ║
║                                                                        ║
║  5. RESULTS                                                            ║
║     Scores appear in CloudWatch Observability dashboard with           ║
║     per-trace breakdowns and aggregate trends.                         ║
║                                                                        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
    print(guide)
