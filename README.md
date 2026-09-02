# Resume Builder

An automated, docs-as-code pipeline that generates a tailored, print-ready
PDF resume for a specific job posting. Given a master resume (JSON) and a
job description (text), an LLM selects and emphasizes the most relevant
experience, and the result is rendered to a polished PDF — all wired up to
run automatically in CI on AWS.

## How it works

```
app/job_description.txt  ─┐
                           ├─▶ backend/main.py ──▶ app/tailored_resume.json ──▶ app/render_resume.py ──▶ app/output.pdf
app/master_resume.json   ─┘        (Bedrock)         (tailored JSON)              (Jinja2 + Playwright)
```

1. `backend/main.py` sends the master resume and job description to a
   Claude model on AWS Bedrock (via the Converse API) and gets back a
   tailored resume as strict JSON. If the Bedrock call fails for any reason
   (e.g. account-level quota throttling), it automatically falls back to
   calling the same model directly through the Anthropic API, using an
   `ANTHROPIC_API_KEY` secret — see below.
2. `app/render_resume.py` renders that JSON into `app/template.html` with
   Jinja2, then uses Playwright (headless Chromium) to print it to a PDF.
3. A GitHub Actions workflow runs both steps automatically whenever
   `app/job_description.txt` changes, authenticating to AWS via OIDC
   (no long-lived credentials), and uploads the resulting PDF as a
   workflow artifact.

## Repository layout

| Path | Purpose |
|---|---|
| `app/` | The resume itself: `master_resume.json` (source data — placeholders only, see below), `job_description.txt` (target posting), `template.html` (print layout), `render_resume.py` (JSON → PDF). |
| `backend/main.py` | Calls AWS Bedrock to tailor the master resume to the job description. |
| `resume_contact.py` | Merges real contact info (email/phone) in at runtime — see below. |
| `infra/` | Terraform for the AWS side: GitHub OIDC provider, an IAM role scoped to `bedrock:InvokeModel`, trusted only from this repo's CI. |
| `.github/workflows/` | The CI pipeline that runs the whole thing end to end. |
| `project_description.md` | Detailed build log / phase-by-phase project status. |

## Contact info

`app/master_resume.json` is committed and meant to be safe to make public,
so it only ever holds placeholder email/phone. The real values are merged
in at runtime by `resume_contact.py`, from either:

- **Local runs:** copy `app/contact_info.local.json.example` to
  `app/contact_info.local.json` and fill in your real email/phone. That
  file is gitignored and never committed.
- **CI:** set repo secrets `RESUME_EMAIL` and `RESUME_PHONE`
  (Settings → Secrets and variables → Actions); the workflow passes them
  through as environment variables.

Neither is required — with no override present, the pipeline still runs
end to end using the placeholder values. LinkedIn/GitHub handles are left
as real values directly in `master_resume.json`, since a resume is meant
to surface those (unlike a phone number, they're not something you'd want
to keep off a public copy).

## Bedrock fallback (Anthropic API)

`backend/main.py` calls Bedrock first. If that call raises a `boto3`/AWS
error (throttling, access denied, no credentials, etc.), it automatically
retries the same tailoring request against the direct Anthropic API instead,
using the `anthropic` Python SDK:

- **Local runs:** `export ANTHROPIC_API_KEY=sk-ant-...` (or set it in your
  shell profile). Never commit this key.
- **CI:** set a repo secret named `ANTHROPIC_API_KEY`
  (Settings → Secrets and variables → Actions). The workflow passes it
  through as an environment variable to the tailoring step only.

If Bedrock fails and `ANTHROPIC_API_KEY` isn't set, the script exits with
an error explaining that Plan B needs the key.

## Running it locally

```bash
pip install -r requirements.txt
playwright install chromium
cp app/contact_info.local.json.example app/contact_info.local.json  # then fill in real info

# 1. Tailor the resume via Bedrock (needs AWS credentials with bedrock:InvokeModel)
python backend/main.py

# 2. Render the tailored (or master, as a fallback) resume to PDF
python app/render_resume.py
```

`app/render_resume.py` defaults to `app/tailored_resume.json`, falling back
to `app/master_resume.json` if it doesn't exist yet, and writes
`app/output.pdf`.

## Infrastructure

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in your AWS account ID
terraform init
terraform apply
```

This provisions the IAM role GitHub Actions assumes via OIDC. Copy the
`github_actions_role_arn` output into a repo secret named `AWS_ROLE_ARN`
for the workflow to use.

## Status

Phases 0–3 (repo hygiene, templating/PDF, IaC, CI/CD) are implemented and
individually verified. See `project_description.md` for the full
phase-by-phase history, known issues, and open questions.
