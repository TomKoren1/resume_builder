"""All environment-derived configuration in one place."""
import os
import secrets
import sys

DB_PATH = os.environ.get("DB_PATH", "app/resume_builder.db")
LOKI_URL = os.environ.get("LOKI_URL", "http://loki:3100/loki/api/v1/push")
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# --- Auth (multi-user web app) ---
# This signs every session cookie (see main.py's SessionMiddleware) - if
# it were ever missing in production and silently fell back to a fixed
# string, that string is sitting in this file in the public repo, so
# anyone could forge a valid session cookie for any user_id and log in as
# them. Generating a random per-process key instead means a missing env
# var just logs everyone out on that restart (sessions won't survive it)
# rather than opening an auth bypass with no indication anything is wrong.
SESSION_SECRET_KEY = os.environ.get("SESSION_SECRET_KEY")
if not SESSION_SECRET_KEY:
    SESSION_SECRET_KEY = secrets.token_hex(32)
    print(
        "WARNING: SESSION_SECRET_KEY is not set - using a random key for "
        "this process only. All sessions will be invalidated on the next "
        "restart. Set SESSION_SECRET_KEY in production.",
        file=sys.stderr,
    )
API_KEY_ENCRYPTION_KEY = os.environ.get("API_KEY_ENCRYPTION_KEY")  # Fernet - fallback-only, see auth.py
# AWS KMS key (see infra/kms.tf) that now does the real encryption for
# per-user Anthropic API keys - a dedicated IAM user's credentials
# (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY, see infra/iam_kms_user.tf)
# reach it via boto3's default credential chain, so no separate config
# constant for those two is needed here.
AWS_KMS_KEY_ID = os.environ.get("KMS_KEY_ID")
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
# Bedrock is billed to the app owner's AWS account, not the requesting
# user - only this one account may use it. Every other user's /generate
# call goes straight to their own BYOK Anthropic key, never Bedrock, so
# nobody else's usage ever touches the owner's AWS bill.
BEDROCK_ALLOWED_USER_ID = int(os.environ.get("BEDROCK_ALLOWED_USER_ID", "1"))
ANTHROPIC_MODEL_ID = "claude-sonnet-4-5-20250929"

TEMPLATE_PATH = "app/template.html"
TAILORED_OUTPUT_PATH = "app/tailored_resume.json"
PDF_SCRATCH_PATH = "/tmp/resume_render.pdf"  # scratch only - the DB blob is canonical
