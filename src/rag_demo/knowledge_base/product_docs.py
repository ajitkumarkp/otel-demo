"""Sample product knowledge base content for a generic SaaS platform.

This simulates a technical support / product documentation corpus used by a
RAG chatbot. It is intentionally domain-neutral so the demo focuses on the
OpenTelemetry instrumentation and AgentCore Evaluations integration rather
than any specific product or industry.
"""

KNOWLEDGE_BASE_DOCUMENTS = [
    {
        "id": "account_getting_started",
        "title": "Getting Started - Creating Your Account",
        "category": "account",
        "content": (
            "Getting Started with the Acme Cloud Platform:\n\n"
            "Creating an Account:\n"
            "1. Visit console.acme.example and click 'Sign Up'\n"
            "2. Enter your work email and choose a strong password\n"
            "3. Verify your email via the confirmation link (valid for 24 hours)\n"
            "4. Complete your organization profile and choose a region\n\n"
            "Password Requirements:\n"
            "- Minimum 12 characters\n"
            "- At least one uppercase letter, one number, and one symbol\n"
            "- Cannot reuse the last 5 passwords\n\n"
            "Multi-Factor Authentication (MFA):\n"
            "- Strongly recommended for all accounts, required for admins\n"
            "- Supports TOTP authenticator apps and hardware security keys\n"
            "- Enable under Settings > Security > Multi-Factor Authentication\n\n"
            "Free Trial:\n"
            "- 14-day trial with full access to Standard tier features\n"
            "- No credit card required to start\n"
            "- Trial data is retained for 30 days after expiration"
        ),
    },
    {
        "id": "billing_plans",
        "title": "Subscription Plans and Billing",
        "category": "billing",
        "content": (
            "Subscription Plans and Billing Overview:\n\n"
            "Available Plans:\n"
            "- Free: 1 project, 1 GB storage, community support\n"
            "- Standard ($29/user/month): 10 projects, 100 GB storage, email support\n"
            "- Pro ($79/user/month): unlimited projects, 1 TB storage, priority support\n"
            "- Enterprise (custom): SSO, audit logs, dedicated support, custom SLAs\n\n"
            "Billing Cycles:\n"
            "- Monthly or annual billing (annual saves ~17%)\n"
            "- Charges are prorated when adding or removing seats mid-cycle\n"
            "- Invoices are issued on the first of each billing period\n\n"
            "Payment Methods:\n"
            "- Major credit cards and ACH transfer (US)\n"
            "- Enterprise plans can be invoiced with net-30 terms\n\n"
            "Managing Your Plan:\n"
            "- Upgrade or downgrade under Settings > Billing > Plan\n"
            "- Downgrades take effect at the end of the current billing cycle\n"
            "- Cancel anytime; access continues until the period ends"
        ),
    },
    {
        "id": "billing_refunds",
        "title": "Refunds and Cancellation Policy",
        "category": "billing",
        "content": (
            "Refund and Cancellation Policy:\n\n"
            "Cancellation:\n"
            "- Cancel any time from Settings > Billing > Cancel Subscription\n"
            "- Your subscription remains active until the end of the paid period\n"
            "- Data is retained for 30 days after cancellation, then permanently deleted\n\n"
            "Refund Eligibility:\n"
            "- Monthly plans: non-refundable once the billing period starts\n"
            "- Annual plans: prorated refund available within the first 30 days\n"
            "- Duplicate charges or billing errors are always fully refunded\n\n"
            "How to Request a Refund:\n"
            "1. Contact support with your account ID and invoice number\n"
            "2. Refunds are reviewed within 3 business days\n"
            "3. Approved refunds return to the original payment method in 5-10 days\n\n"
            "Note: Usage-based overage charges (storage, API calls) are billed in "
            "arrears and are not refundable."
        ),
    },
    {
        "id": "tech_api_integration",
        "title": "API Integration Guide",
        "category": "technology",
        "content": (
            "REST API Integration Guide:\n\n"
            "Authentication:\n"
            "- All requests use bearer tokens: Authorization: Bearer <API_KEY>\n"
            "- Generate API keys under Settings > Developer > API Keys\n"
            "- Keys are scoped per project; rotate them at least every 90 days\n\n"
            "Base URL and Versioning:\n"
            "- Base URL: https://api.acme.example/v1\n"
            "- The API version is pinned in the path (v1, v2)\n"
            "- Deprecated versions are supported for 12 months after a new release\n\n"
            "Rate Limits:\n"
            "- Standard tier: 60 requests/minute\n"
            "- Pro tier: 600 requests/minute\n"
            "- Exceeding limits returns HTTP 429 with a Retry-After header\n\n"
            "Common Troubleshooting:\n"
            "- 401 Unauthorized: check the API key is active and correctly scoped\n"
            "- 403 Forbidden: the key lacks permission for the requested resource\n"
            "- 429 Too Many Requests: back off and retry per the Retry-After header\n"
            "- Use webhooks (Settings > Developer > Webhooks) for event-driven updates"
        ),
    },
    {
        "id": "tech_integrations",
        "title": "Third-Party Integrations",
        "category": "technology",
        "content": (
            "Third-Party Integrations Guide:\n\n"
            "Supported Integrations:\n"
            "- Single Sign-On: SAML 2.0 and OpenID Connect (Okta, Azure AD, Google)\n"
            "- Chat: Slack and Microsoft Teams notifications\n"
            "- Version control: GitHub, GitLab, and Bitbucket\n"
            "- Data export: scheduled exports to Amazon S3 or Google Cloud Storage\n\n"
            "Connecting an Integration:\n"
            "1. Go to Settings > Integrations\n"
            "2. Choose a provider and click 'Connect'\n"
            "3. Authorize via OAuth and select the resources to sync\n"
            "4. Configure sync frequency (real-time, hourly, or daily)\n\n"
            "Common Troubleshooting:\n"
            "- Sync failing: reauthorize the connection; tokens expire after 60 days\n"
            "- Missing events: confirm the integration has the required scopes\n"
            "- Duplicate notifications: check for overlapping notification rules\n\n"
            "Removing an Integration:\n"
            "- Disconnect under Settings > Integrations; this revokes stored tokens"
        ),
    },
    {
        "id": "security_data_protection",
        "title": "Data Security and Privacy",
        "category": "security",
        "content": (
            "Data Security and Privacy Overview:\n\n"
            "Encryption:\n"
            "- Data in transit is encrypted with TLS 1.2 or higher\n"
            "- Data at rest is encrypted using AES-256\n"
            "- Encryption keys are managed and rotated automatically\n\n"
            "Access Controls:\n"
            "- Role-based access control (RBAC) with Owner, Admin, Member, Viewer roles\n"
            "- Least-privilege defaults; permissions are granted per project\n"
            "- Admins can enforce MFA and session timeout policies\n\n"
            "Compliance:\n"
            "- SOC 2 Type II and ISO 27001 certified\n"
            "- GDPR and CCPA data processing addendums available\n"
            "- Regional data residency options for Enterprise plans\n\n"
            "Data Retention and Deletion:\n"
            "- Deleted resources are recoverable for 30 days\n"
            "- Permanent deletion requests are honored within 30 days\n"
            "- Audit logs are retained for 12 months (Enterprise: configurable)"
        ),
    },
    {
        "id": "troubleshooting_login",
        "title": "Troubleshooting Login Issues",
        "category": "troubleshooting",
        "content": (
            "Troubleshooting Login and Access Issues:\n\n"
            "Cannot Log In:\n"
            "- Confirm you are using the correct email and region-specific console URL\n"
            "- Use 'Forgot Password' to reset; reset links expire after 1 hour\n"
            "- Clear browser cache or try an incognito window\n\n"
            "MFA Problems:\n"
            "- Time-based codes require your device clock to be accurate\n"
            "- Lost your device? Use a backup recovery code from initial setup\n"
            "- No recovery code? An account admin can reset MFA for you\n\n"
            "Account Locked:\n"
            "- Accounts lock for 15 minutes after 5 failed attempts\n"
            "- Repeated lockouts may indicate a credential-stuffing attempt; rotate password\n\n"
            "SSO Login Fails:\n"
            "- Verify the user exists in your identity provider and is assigned the app\n"
            "- Check that the SAML/OIDC configuration matches on both sides\n"
            "- Contact your organization admin if the issue persists"
        ),
    },
    {
        "id": "troubleshooting_performance",
        "title": "Troubleshooting Performance Problems",
        "category": "troubleshooting",
        "content": (
            "Troubleshooting Performance and Reliability Issues:\n\n"
            "Slow Dashboard or UI:\n"
            "- Check the status page at status.acme.example for ongoing incidents\n"
            "- Large projects may load slowly; use filters to reduce result sets\n"
            "- Disable browser extensions that inject scripts into the console\n\n"
            "Slow or Failing API Calls:\n"
            "- Inspect response headers for rate-limit and Retry-After values\n"
            "- Batch requests where possible to reduce round trips\n"
            "- Use pagination for large collections rather than fetching all at once\n\n"
            "Data Not Updating:\n"
            "- Real-time sync can lag up to 60 seconds under heavy load\n"
            "- Confirm the relevant integration or webhook is healthy\n"
            "- Force a manual refresh from the affected resource's detail view\n\n"
            "Reporting an Incident:\n"
            "- Include timestamps (with time zone), request IDs, and affected project IDs\n"
            "- Request IDs appear in API responses under the X-Request-Id header"
        ),
    },
    {
        "id": "features_projects",
        "title": "Projects and Workspaces",
        "category": "features",
        "content": (
            "Working with Projects and Workspaces:\n\n"
            "Projects:\n"
            "- A project is the top-level container for resources and members\n"
            "- Create a project from the dashboard with 'New Project'\n"
            "- Each project has independent settings, members, and API keys\n\n"
            "Workspaces:\n"
            "- Workspaces group related projects under one billing account\n"
            "- Move a project between workspaces from Project Settings > Advanced\n"
            "- Workspace admins can set org-wide policies and defaults\n\n"
            "Collaboration:\n"
            "- Invite members by email from Project Settings > Members\n"
            "- Assign roles: Owner, Admin, Member, or Viewer\n"
            "- Pending invitations expire after 7 days\n\n"
            "Archiving and Deletion:\n"
            "- Archive inactive projects to hide them without losing data\n"
            "- Archived projects can be restored for 90 days\n"
            "- Deleting a project removes all its resources after a 30-day grace period"
        ),
    },
    {
        "id": "support_contact",
        "title": "Contacting Support",
        "category": "support",
        "content": (
            "How to Get Support:\n\n"
            "Support Channels by Plan:\n"
            "- Free: community forum and documentation\n"
            "- Standard: email support, response within 1 business day\n"
            "- Pro: priority email and chat, response within 4 business hours\n"
            "- Enterprise: dedicated support contact and phone support\n\n"
            "Opening a Ticket:\n"
            "1. Click the Help icon in the console and choose 'Contact Support'\n"
            "2. Select a category and severity level\n"
            "3. Include reproduction steps, screenshots, and request IDs\n"
            "4. You will receive a ticket number and email confirmation\n\n"
            "Severity Levels:\n"
            "- S1 Critical: production down or major outage (Enterprise 24/7)\n"
            "- S2 High: significant degradation with no workaround\n"
            "- S3 Normal: minor issue or question\n"
            "- S4 Low: feature request or general guidance\n\n"
            "Status and Incidents:\n"
            "- Subscribe to status.acme.example for real-time incident updates\n"
            "- Post-incident reports are published for all S1 outages"
        ),
    },
]


def get_all_documents() -> list[dict]:
    """Return all knowledge base documents."""
    return KNOWLEDGE_BASE_DOCUMENTS


def get_documents_by_category(category: str) -> list[dict]:
    """Return documents filtered by category."""
    return [doc for doc in KNOWLEDGE_BASE_DOCUMENTS if doc["category"] == category]
