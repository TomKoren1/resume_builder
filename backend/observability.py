"""Logging (Loki + stdout) and Prometheus metrics, shared across the app."""
import logging
import sys

import logging_loki
from prometheus_client import Counter, Histogram

from . import config

loki_handler = logging_loki.LokiHandler(
    url=config.LOKI_URL,
    tags={"app": "resume_backend"},
    version="1",
)
logger = logging.getLogger("resume_builder")
logger.setLevel(logging.INFO)
logger.addHandler(loki_handler)
logger.addHandler(logging.StreamHandler(sys.stdout))  # Also log to Docker console

GENERATE_COUNT = Counter('resume_generation_total', 'Total resumes generated', ['status'])
LLM_LATENCY = Histogram('llm_inference_seconds', 'Time spent waiting for LLM', ['provider'])
