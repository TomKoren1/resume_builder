from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from . import config, db
from .observability import logger
from .rate_limit import limiter
from .routers import auth, generate, history, master_resume

app = FastAPI()
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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


# Signed httpOnly session cookie (holds only {"user_id": int}) - replaces
# the old CORSMiddleware entirely. Frontend and backend are, and always
# will be, served same-origin through one Ingress host (see
# helm/resume-builder/README.md), so there's no cross-origin request to
# configure CORS for - and the previous allow_origins=["*"] +
# allow_credentials=True combination is actively invalid once cookies are
# in play (browsers refuse to honor credentialed responses with a
# wildcard origin).
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET_KEY,
    session_cookie="session",
    same_site="lax",
    https_only=config.SESSION_COOKIE_SECURE,
)

app.include_router(auth.router)
app.include_router(generate.router)
app.include_router(history.router)
app.include_router(master_resume.router)


@app.get("/metrics")
def metrics():
    """Endpoint for Prometheus to scrape metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
