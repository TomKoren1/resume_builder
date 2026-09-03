import requests

from . import config
from .observability import logger


def notify_slack(text):
    """Best-effort Slack push. Never raises - a notification failure
    shouldn't fail the /generate request. Incoming webhooks can only post
    text/links, not upload files, so this sends a download link rather
    than the PDF itself."""
    if not config.SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(config.SLACK_WEBHOOK_URL, json={"text": text}, timeout=5)
    except Exception as e:
        logger.warning(f"Slack notification failed: {e}")
