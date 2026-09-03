# `frontend/`

A static single-page UI — no build step, no framework, plain HTML/CSS/JS
served as-is by nginx. Kept deliberately dependency-free to match the rest
of this project's minimal-infrastructure style.

| File | Purpose |
|---|---|
| `index.html` | Page shell: a small nav (Generate / History / Edit Resume) and three view containers, JS-toggled — no page reloads, no router. |
| `style.css` | All styling — cards, forms, badges. No CSS framework. |
| `app.js` | All view logic (see below). |
| `dockerfile` | `FROM nginx:alpine`, copies the three files above in. Built from *this* directory as context (unlike the backend's dockerfile, which needs the repo root). |

## Views (`app.js`)

- **Generate** — the original form: paste a job description, submit to
  `POST /generate`, show the result and a download link.
- **History** — fetches `GET /history`, renders each attempt (date, job
  description, status badge, download link if a PDF exists).
- **Edit Resume** — fetches `GET /master-resume`, renders a structured form
  matching the schema in [`app/README.md`](../app/README.md): plain fields
  for name/title/contact/summary, and two reusable generic editors —
  `makeListEditor` (add/remove line items: skills, languages,
  certifications) and `makeCardList` (add/remove repeatable objects:
  experience/projects/education, each with their own bullet/notes list) —
  so each section doesn't need its own bespoke add/remove logic. "Save"
  → `PUT /master-resume`; a version-history panel lists past versions with
  a "Restore" button → `POST /master-resume/versions/{id}/restore`.

`formatApiError()` at the top of `app.js` normalizes FastAPI's two error
shapes — a plain string for hand-raised `HTTPException`s, or an array of
`{loc, msg}` field errors for Pydantic 422 validation failures — into one
readable message, rather than showing `[object Object]` on a validation
error.

## How it talks to the backend

All `fetch` calls use **relative paths** (`/generate`, `/history`,
`/master-resume`, ...) — the frontend assumes it's served from the same
origin as the backend API. In the deployed app, the Ingress routes those
specific paths to the backend Service and everything else to the frontend
Service under one hostname; see [`helm/resume-builder/README.md`](../helm/resume-builder/README.md).
Running the frontend standalone therefore needs something in front of it
doing the same path-based routing (or just serve both from `uvicorn` behind
a reverse proxy for local testing).
