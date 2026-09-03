# `app/`

Resume data and the shared PDF-rendering logic — used both by the web app
(`backend/`) and the standalone CLI pipeline (`.github/workflows/generate-resume.yml`).

| File | Purpose |
|---|---|
| `master_resume.json` | The resume schema and its **seed data**. Committed and meant to be public — only ever holds placeholder contact info (see the root README's [Contact info](../README.md#contact-info) section). |
| `template.html` | The print layout — Jinja2 + CSS, one page, sized for Letter paper. |
| `render_resume.py` | Renders a resume JSON through `template.html` with Jinja2, then prints it to PDF with Playwright (headless Chromium). Imported directly by `backend/routers/generate.py` and `backend/tailor_cli.py` — not just a CLI script. |
| `job_description.txt` | Target job posting for the standalone CLI pipeline only (the web app takes the job description as a request body instead). |
| `contact_info.local.json.example` | Template for `contact_info.local.json` (gitignored) — real contact info for local runs. |

## `master_resume.json` is only ever a *seed*

In the deployed web app, this file is read exactly once — by
`backend/db.py`'s `init_db()`, the first time the database is empty — to
seed the first row of `master_resume_versions`. After that, **the database
is the live source of truth**: edits made through the frontend's "Edit
Master Resume" tab never touch this file. It stays in git purely as the
starting point for a fresh deployment (or the standalone CLI pipeline,
which reads it directly on every run instead of from a database).

## Schema

```jsonc
{
  "name": "...", "title": "...",
  "contact": { "email": "...", "phone": "...", "location": "...", "linkedin": "...", "github": "..." },
  "summary": "... **bold** via double-asterisks ...",
  "skills": ["Category: item, item, item", "..."],
  "languages": ["..."],
  "experience": [{ "company": "...", "role": "...", "start_date": "...", "end_date": "...", "location": "...", "bullets": ["..."] }],
  "projects": [{ "name": "...", "url": "...", "bullets": ["..."] }],
  "education": [{ "school": "...", "degree": "...", "start_date": "...", "end_date": "...", "notes": ["..."] }],
  "certifications": ["..."]
}
```

This exact shape is also what `backend/schemas.py`'s `MasterResume` Pydantic
model validates, and what the frontend's structured edit form assumes —
keep all three in sync if the schema ever changes.

## `render_resume.py` standalone usage

```bash
python app/render_resume.py [resume.json] [template.html] [output.pdf]
# defaults: app/tailored_resume.json (falling back to master_resume.json
# if it doesn't exist), app/template.html, app/output.pdf
```

It also does the required-field validation (`validate_resume_data`) that
guards the render step against a malformed/incomplete resume — a missing
`experience` list or a job entry without `role`/`company` fails loudly
instead of silently rendering a broken PDF.
