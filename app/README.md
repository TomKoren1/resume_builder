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

## `master_resume.json` is only ever a schema example/placeholder

It is **not** auto-loaded into any real user's account. Every new signed-up
user starts with an empty master resume and fills it in via the frontend's
"Edit Master Resume" tab (or the "import from old resumes" auto-fill) —
their data lives entirely in `backend/db.py`'s per-user
`master_resume_versions` table, **the live source of truth**. This file
stays in git purely as (a) a concrete example of the schema below, safe to
make public since it only ever holds placeholder contact info, and (b) the
input the standalone CLI pipeline tailors against directly on every run
(see [Standalone CLI pipeline](../README.md#standalone-cli-pipeline) in
the root README) — that pipeline is unrelated to any web app user's data.

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
  "certifications": ["..."],
  "custom_sections": [{ "id": "custom-...", "title": "...", "type": "bullets", "items": ["..."], "text": "" }]
}
```

`custom_sections` is user-defined sections beyond the fixed set above
(e.g. "Volunteer Work", "Publications") — each one is either a bulleted
list (`type: "bullets"`, use `items`) or free text (`type: "text"`, use
`text`); `id` is a stable slug derived from the title, referenced by a
rendered resume's `section_order`/`hidden_sections` (see `EditableResume`
in `backend/schemas.py`) so it can be shown/hidden/reordered like any
built-in section.

This exact shape is also what `backend/schemas.py`'s `MasterResume` Pydantic
model validates, and what the frontend's structured edit form assumes —
keep all three in sync if the schema ever changes. `template.html` also
supports 5 visual themes (classic/modern/compact/sidebar/executive) and an
optional photo (Sidebar theme only) — chosen per-render, not part of the
master resume schema itself; see `EditableResume` for those fields.

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
