# `backend/`

The FastAPI app. Split into focused modules rather than one large file —
`main.py` is just app setup + router wiring:

| File | Purpose |
|---|---|
| `main.py` | Creates the `FastAPI` app, wires up the session middleware (`SessionMiddleware`, signed httpOnly cookie — no CORS: frontend and backend are always same-origin, see [`../frontend/README.md`](../frontend/README.md)), the startup hook (`db.init_db()`), the routers below, rate limiting, and `/metrics`. |
| `config.py` | Every environment-derived setting in one place — DB/logging/Slack, OAuth client IDs/secrets, `SESSION_SECRET_KEY` (random per-process if unset, never a fixed fallback — see [Session/secret hygiene](#sessionsecret-hygiene)), `AWS_KMS_KEY_ID`, model IDs, file paths. |
| `auth.py` | OAuth (Google/GitHub) client setup via `authlib`, the `get_current_user`/`get_current_user_with_key` FastAPI dependencies, and per-user Anthropic API key encryption (AWS KMS, with a Fernet fallback for pre-migration rows) — see [Auth & per-user API keys](#auth--per-user-api-keys). |
| `rate_limit.py` | The shared `slowapi` `Limiter`, keyed per-user (falls back to IP only for the theoretical unauthenticated case, which `Depends(get_current_user...)` already rejects with a 401 before a rate-limited handler ever runs). |
| `observability.py` | The Loki logging handler + stdout logging, and the Prometheus metrics the app defines itself (`resume_generation_total`, `llm_inference_seconds`). |
| `llm.py` | `tailor_resume()` — calls Bedrock, falls back to the Anthropic API (BYOK: the caller's own key in the web app, `ANTHROPIC_API_KEY` for the standalone CLI pipeline) on any AWS error, strips a stray ```` ```json ```` fence, parses the result. Also `extract_master_resume()` for the "import from an old resume" feature. |
| `notifications.py` | `notify_slack()` — best-effort Slack push (used after `/generate` and nowhere else; never raises). |
| `db.py` | SQLite persistence — `users`, and per-user `generation_history`/`master_resume_versions`. Every query is scoped by `user_id`; see [Persistence](#persistence) below. |
| `schemas.py` | Pydantic models: `GenerateRequest`, `MasterResume` (+ `Contact`/`ExperienceEntry`/`ProjectEntry`/`EducationEntry`/`CustomSection`), `EditableResume` (a `MasterResume` plus per-render layout: `section_order`/`hidden_sections`/`section_titles`/`theme`/`color`/`photo`), `HistoryItem`/`HistoryDetail`, `RenameHistoryRequest`, `MasterResumeVersion`. |
| `routers/auth.py` | `GET /auth/login/{provider}`, `GET /auth/callback/{provider}`, `POST /auth/logout`, `GET /auth/me`, `PUT`/`DELETE /auth/api-key`. |
| `routers/generate.py` | `POST /generate` — tailor *the caller's* master resume, render PDF, store both, notify Slack. Rate-limited. |
| `routers/history.py` | `GET /history`, `GET /history/{id}`, `GET /history/{id}/preview` (the History editor's live iframe — same `template.html` the PDF uses), `GET /history/{id}/download`, `PUT /history/{id}` (save edits + re-render), `PATCH /history/{id}/name`, `DELETE /history/{id}`, `POST /history/{id}/save-as`. |
| `routers/master_resume.py` | `GET`/`PUT /master-resume`, `POST /master-resume/import` (extract a master resume from pasted/uploaded old resumes via the caller's own key, rate-limited), `GET /master-resume/versions`, `POST /master-resume/versions/{id}/restore`. |
| `tailor_cli.py` | Standalone entrypoint for the CI-only pipeline (`.github/workflows/generate-resume.yml`) — not used by the web app. See [`../app/README.md`](../app/README.md). |
| `dockerfile` | **Built with the repo root as context**, not `backend/` — `main.py` needs `app/` and `resume_contact.py` at runtime. `docker build -t resume-backend:local -f backend/dockerfile .` |

## API

Every endpoint below except `/auth/login`, `/auth/callback`, and `/metrics`
requires a logged-in session (`Depends(get_current_user)`, or
`get_current_user_with_key` for the two that also need the caller's
decrypted Anthropic key) and only ever touches *that user's own* rows.

| Method | Path | Notes |
|---|---|---|
| `GET` | `/auth/login/{provider}` | `provider` is `google` or `github` — redirects into the OAuth flow. |
| `GET` | `/auth/callback/{provider}` | OAuth callback — creates/updates the user, sets the session cookie. |
| `POST` | `/auth/logout` | Clears the session. |
| `GET` | `/auth/me` | The logged-in user's profile + whether they have an API key saved (never the key itself). |
| `PUT` | `/auth/api-key` | Body: `{"anthropic_api_key": "..."}`. Full-replace only — there's no "reveal" endpoint. |
| `DELETE` | `/auth/api-key` | Removes the stored key. |
| `POST` | `/generate` | Body: `{"job_description": "...", "theme": "...", "color": "...", "photo": "..."}`. Tailors the caller's current master resume, renders a PDF, stores both, returns `download_url`. Rate-limited. |
| `GET` | `/history` | The caller's past attempts (success or error), newest first. |
| `GET` | `/history/{id}` | Full stored data for one entry (for the History editor). |
| `GET` | `/history/{id}/preview` | That entry rendered through the real `template.html` — loaded into the History editor's iframe, so what's edited can never visually drift from the actual PDF. |
| `GET` | `/history/{id}/download` | That attempt's PDF. |
| `PUT` | `/history/{id}` | Body: an `EditableResume`. Re-renders and overwrites this entry's content/PDF in place. |
| `PATCH` | `/history/{id}/name` | Body: `{"name": "..."}`. Empty clears back to showing the job description. |
| `DELETE` | `/history/{id}` | Permanently deletes that entry. |
| `POST` | `/history/{id}/save-as` | Same edit as `PUT`, but as a new history entry — the original is left untouched. |
| `GET` | `/master-resume` | The caller's current master resume. |
| `PUT` | `/master-resume` | Body: a full `MasterResume` object. Saves a new version. |
| `POST` | `/master-resume/import` | Multipart: pasted text and/or uploaded PDFs of old resumes. Consolidates them into a master resume via the caller's own key — auto-saved if they have none yet, returned for review otherwise. Rate-limited. |
| `GET` | `/master-resume/versions` | The caller's version history. |
| `POST` | `/master-resume/versions/{id}/restore` | Copies an old version's data into a new current version (rollback-as-new-commit — history stays linear). |
| `GET` | `/metrics` | Prometheus exposition — the app's own metrics plus per-route request count/latency from `prometheus-fastapi-instrumentator`. Not publicly routed (see [`../helm/resume-builder/README.md`](../helm/resume-builder/README.md)). |

## Auth & per-user API keys

OAuth only (Google/GitHub via `authlib`) — no passwords ever stored.
Identity is keyed on `(oauth_provider, oauth_subject)`, never email
(GitHub can return no verified email even with the right scope). Sessions
are a signed httpOnly cookie holding only `{"user_id": int}` — no
server-side session store, which is fine for a single backend pod.

Each user's own Anthropic API key (BYOK) is encrypted with **AWS KMS**
before it ever touches the database (`encrypt_api_key`/`decrypt_api_key`
in `auth.py`) — never a static local key, and never returned to the
client (only a masked preview, e.g. `sk-ant-...abcd`). Rows saved before
the KMS migration (a local Fernet key, `API_KEY_ENCRYPTION_KEY`) are
handled by a fallback-and-lazy-migrate path: a decrypt that KMS reports as
not-its-ciphertext falls back to the old key and immediately re-encrypts
that one row via KMS — each user's key upgrades itself the next time they
generate, no downtime or batch job. See [`../infra/README.md`](../infra/README.md)
for the KMS key/IAM setup and [`../README.md#security`](../README.md#security)
for the full security posture.

### Session/secret hygiene

`SESSION_SECRET_KEY` signs every session cookie. If it's ever unset,
`config.py` generates a random one for that process instead of falling
back to a fixed value — a missing env var just logs everyone out on that
restart, rather than silently signing sessions with a value anyone could
read out of this public repo.

## Persistence

SQLite at `DB_PATH` (default `app/resume_builder.db`, so this works
without a PVC for local runs — in the deployed app it's
`/data/resume_builder.db` on a PersistentVolumeClaim, see
[`../helm/resume-builder/README.md`](../helm/resume-builder/README.md)).
Three tables: `users` (OAuth identity, profile, encrypted API key),
`generation_history`, and `master_resume_versions` (versioned, with an
`is_current` flag) — the latter two both carry a `user_id` and every
`db.py` query is scoped by it, the app's core IDOR protection. **No
seeding from `app/master_resume.json` happens** — every new user starts
with an empty master resume and fills it in via the Edit Master Resume
tab (or the "import from an old resume" auto-fill); that file is only a
schema example/placeholder, not live data for anyone's account.

## Running locally

```bash
pip install -r requirements.txt
playwright install chromium
uvicorn backend.main:app --reload --port 8000    # run from the repo root
```

Nothing above is strictly required to boot, but logging in (and therefore
using any endpoint except `/metrics`) needs real values for:

| Env var | What it's for |
|---|---|
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth app (redirect URI: `http://localhost:8000/auth/callback/google`). |
| `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` | GitHub OAuth app (redirect URI: `http://localhost:8000/auth/callback/github`). |
| `API_KEY_ENCRYPTION_KEY` | Fernet key so BYOK API keys can be saved without `AWS_KMS_KEY_ID` set (see [Auth & per-user API keys](#auth--per-user-api-keys)) — `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. |

Optional: `AWS_KMS_KEY_ID` + real AWS credentials to exercise the KMS path
instead of the Fernet fallback; `ANTHROPIC_API_KEY` only matters for the
*standalone CLI pipeline* (`tailor_cli.py`) — the web app always uses
BYOK. `SESSION_SECRET_KEY` doesn't need setting for local dev (a random
per-process one is generated automatically, see
[Session/secret hygiene](#sessionsecret-hygiene)).
