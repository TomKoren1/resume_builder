"""All environment-derived configuration in one place."""
import os

DB_PATH = os.environ.get("DB_PATH", "app/resume_builder.db")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100/loki/api/v1/push")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BEDROCK_REGION = "us-east-1"
ANTHROPIC_MODEL_ID = "claude-sonnet-4-5-20250929"

TEMPLATE_PATH = "app/template.html"
TAILORED_OUTPUT_PATH = "app/tailored_resume.json"
PDF_SCRATCH_PATH = "/tmp/resume_render.pdf"  # scratch only - the DB blob is canonical
