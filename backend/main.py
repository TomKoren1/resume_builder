from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator

from . import db
from .observability import logger
from .routers import generate, history, master_resume

app = FastAPI()

# Generic per-route request count/latency metrics for every endpoint (the
# app's own GENERATE_COUNT/LLM_LATENCY in observability.py only ever covered
# /generate - this fills in /history, /master-resume, etc. for free).
# Registers into the same default prometheus_client registry our manual
# /metrics endpoint below already serves, so no second endpoint is needed.
Instrumentator().instrument(app)


@app.on_event("startup")
def _startup():
    db.init_db()
    logger.info("Backend started via GitOps (CI build + ArgoCD sync).")


# Allow the frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(generate.router)
app.include_router(history.router)
app.include_router(master_resume.router)


@app.get("/metrics")
def metrics():
    """Endpoint for Prometheus to scrape metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
