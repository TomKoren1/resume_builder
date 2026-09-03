# `backend/`

The FastAPI app. Split into focused modules rather than one large file —
`main.py` is just app setup + router wiring:

| File | Purpose |
|---|---|
| `main.py` | Creates the `FastAPI` app, wires up CORS, the startup hook (`db.init_db()`), the routers below, and `/metrics`. |
| `config.py` | Every environment-derived setting in one place (`DB_PATH`, `LOKI_URL`, `SLACK_WEBHOOK_URL`, `ANTHROPIC_API_KEY`, model IDs, file paths). |
| `observability.py` | The Loki logging handler + stdout logging, and the two Prometheus metrics the app defines itself (`resume_generation_total`, `llm_inference_seconds`). |
| `llm.py` | `tailor_resume()` — calls Bedrock, falls back to the Anthropic API on any AWS error, strips a stray ```` ```json ```` fence, parses the result. Also used standalone by `tailor_cli.py`. |
| `notifications.py` | `notify_slack()` — best-effort Slack push (used after `/generate` and nowhere else; never raises). |
| `db.py` | SQLite persistence — generation history and versioned master-resume rows. See [Persistence](#persistence) below. |
| `schemas.py` | Pydantic models: `GenerateRequest`, `MasterResume` (+ `Contact`/`ExperienceEntry`/`ProjectEntry`/`EducationEntry`), `HistoryItem`, `MasterResumeVersion`. |
| `routers/generate.py` | `POST /generate` — tailor, render PDF, store both, notify Slack. |
| `routers/history.py` | `GET /history`, `GET /history/{id}/download`. |
| `routers/master_resume.py` | `GET`/`PUT /master-resume`, `GET /master-resume/versions`, `POST /master-resume/versions/{id}/restore`. |
| `tailor_cli.py` | Standalone entrypoint for the CI-only pipeline (`.github/workflows/generate-resume.yml`) — not used by the web app. See [`app/README.md`](../app/README.md). |
| `dockerfile` | **Built with the repo root as context**, not `backend/` — `main.py` needs `app/` and `resume_contact.py` at runtime. `docker build -t resume-backend:local -f backend/dockerfile .` |

## API

| Method | Path | Notes |
|---|---|---|
| `POST` | `/generate` | Body: `{"job_description": "..."}`. Tailors the current master resume, renders a PDF, stores both, returns `download_url`. |
| `GET` | `/history` | Every past attempt (success or error), newest first. |
| `GET` | `/history/{id}/download` | That attempt's PDF. |
| `GET` | `/master-resume` | The current master resume. |
| `PUT` | `/master-resume` | Body: a full `MasterResume` object. Saves a new version. |
| `GET` | `/master-resume/versions` | Version history. |
| `POST` | `/master-resume/versions/{id}/restore` | Copies an old version's data into a new current version (rollback-as-new-commit — history stays linear). |
| `GET` | `/metrics` | Prometheus exposition — the app's own metrics plus per-route request count/latency from `prometheus-fastapi-instrumentator`. |

## Persistence

SQLite at `DB_PATH` (default `app/resume_builder.db`, so this works without
a PVC for local runs — in the deployed app it's `/data/resume_builder.db`
on a PersistentVolumeClaim, see [`helm/resume-builder/README.md`](../helm/resume-builder/README.md)).
Two tables: `generation_history` (every `/generate` attempt, PDF bytes
included) and `master_resume_versions` (every save, with an `is_current`
flag). On first startup, if `master_resume_versions` is empty, it's seeded
from `app/master_resume.json` — after that, **the database is the live
source of truth**, not the file.

## Running locally

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn backend.main:app --reload --port 8000    # run from the repo root
```

Needs `ANTHROPIC_API_KEY` set (Bedrock will fail without AWS credentials
and fall back to it automatically) to actually generate anything;
everything else has a working default with no configuration.
