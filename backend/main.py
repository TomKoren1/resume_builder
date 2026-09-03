from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from . import db
from .routers import generate, history, master_resume

app = FastAPI()


@app.on_event("startup")
def _startup():
    db.init_db()


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
