"""All environment-derived configuration in one place."""
import os

DB_PATH = os.environ.get("DB_PATH", "app/resume_builder.db")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100/loki/api/v1/push")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# --- Auth (multi-user web app) ---
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY", "dev-only-insecure-key")
API_KEY_ENCRYPTION_KEY = os.environ.get("API_KEY_ENCRYPTION_KEY")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GITHUB_CLIENT_ID = os.environ.get("GITHUB_CLIENT_ID")
GITHUB_CLIENT_SECRET = os.environ.get("GITHUB_CLIENT_SECRET")
# Must stay "false" while served over plain HTTP (Tailscale/.local today)
# - browsers silently drop Secure cookies over HTTP, which makes login
# look broken with no clear error. Flip to "true" only once Cloudflare
# Tunnel is fronting this with real HTTPS (Phase 4).
SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"

BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BEDROCK_REGION = "us-east-1"
ANTHROPIC_MODEL_ID = "claude-sonnet-4-5-20250929"

TEMPLATE_PATH = "app/template.html"
TAILORED_OUTPUT_PATH = "app/tailored_resume.json"
PDF_SCRATCH_PATH = "/tmp/resume_render.pdf"  # scratch only - the DB blob is canonical
