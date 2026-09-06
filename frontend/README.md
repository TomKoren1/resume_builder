# `frontend/`

A static single-page UI — no build step, no framework, no bundler. Plain
HTML/CSS and native **ES modules** (`<script type="module">`), served
as-is by nginx. Kept deliberately dependency-free to match the rest of
this project's minimal-infrastructure style; native `import`/`export` is
enough to split the JS into focused files without needing a build step.

| File | Purpose |
|---|---|
| `index.html` | Page shell: nav (Generate / History / Edit Master Resume / Account) plus tab-less views for Login and the History editor, JS-toggled — no page reloads, no router. |
| `style.css` | All styling — cards, forms, badges, the History editor's two-pane layout. No CSS framework. |
| `nginx.conf` | Overrides nginx's default: `Cache-Control: no-cache` on everything, so a redeploy is never masked by a browser/Cloudflare-edge-cached stale JS file (a real bug hit and fixed during development). |
| `dockerfile` | `FROM nginx:alpine`, copies `index.html`/`style.css` and the whole `js/` directory in. Built from *this* directory as context (unlike the backend's dockerfile, which needs the repo root). |
| `js/main.js` | Entry point — tab-switching wiring and the app-init session check (`GET /auth/me`; a 401 shows the Login view). Imports the other modules below (including for their side effects, e.g. wiring up `generate.js`'s form listener). |
| `js/utils.js` | `apiFetch()` (adds `credentials: 'include'`, redirects to Login on 401), `showView()`, `formatApiError()` (normalizes FastAPI's two error shapes — a plain string or a Pydantic `{loc, msg}` array — into one message), `resizeImageToDataUrl()` (client-side photo downscale before upload). |
| `js/form-builders.js` | Shared, reusable form-building blocks used by both the master-resume editor and the import-review form: `makeListEditor` (add/remove line items), `makeCardList` (add/remove repeatable objects with their own bullet/notes list), `makeCustomSectionsEditor` (user-defined sections, bulleted-list or free-text), `renderResumeFields`/`collectResumeFields`. |
| `js/master-resume.js` | The Edit Master Resume tab: load/save/version-restore, plus the "import from old resumes" flow (paste text and/or upload PDFs → `POST /master-resume/import`). |
| `js/history.js` | The History tab: list, rename (inline), delete. |
| `js/history-editor.js` | The Canva-style click-to-edit view for one resume: loads `GET /history/{id}/preview` (the *real* `template.html`) into an iframe, wires up click-to-edit + add/remove-entry controls directly on that DOM, a Sections panel (show/hide/reorder, and add a brand-new custom section on the spot — useful for a resume generated before a section existed), theme/color/photo controls, Save / Save As New. |
| `js/account.js` | The Account tab: profile display, BYOK API key save/remove (masked display only), log out. |
| `js/generate.js` | The Generate tab's form submit handler. |

## Views

- **Login** (tab-less) — shown whenever `GET /auth/me` 401s. Plain
  `<a href="/auth/login/google">`/`.../github` links, full-page navigation.
- **Generate** — paste a job description (+ theme/color/optional photo),
  submit to `POST /generate`, show the result and a download link.
- **History** — `GET /history`, each attempt with date, job description
  (or a custom name — see `history.js`), status badge, download link,
  Edit/Rename/Delete.
- **History editor** (tab-less, opened via History's "Edit") — the
  click-to-edit Canva-style view; see `js/history-editor.js` above.
- **Edit Master Resume** — `GET /master-resume` rendered via the shared
  `renderResumeFields()` (see `js/form-builders.js`): plain fields for
  name/title/contact/summary, generic list/card editors for
  skills/languages/certifications/experience/projects/education, and a
  Custom Sections editor. "Save" → `PUT /master-resume`; a version-history
  panel lists past versions with "Restore" →
  `POST /master-resume/versions/{id}/restore`. Also hosts the "import from
  old resumes" form.
- **Account** — profile, BYOK Anthropic API key (masked, full-replace
  only), log out.

## How it talks to the backend

All `fetch` calls go through `apiFetch()` (`js/utils.js`) using **relative
paths** (`/generate`, `/history`, `/auth/me`, ...) — the frontend assumes
it's served from the same origin as the backend API, and that the session
cookie should ride along (`credentials: 'include'`). In the deployed app,
the Ingress routes `/generate`, `/history`, `/master-resume`, `/auth` to
the backend Service and everything else to the frontend Service under one
hostname; see [`../helm/resume-builder/README.md`](../helm/resume-builder/README.md).
Running the frontend standalone therefore needs something in front of it
doing the same path-based routing (or just serve both from `uvicorn`
behind a reverse proxy for local testing).
