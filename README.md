# Resume Builder

An AI-powered resume tailoring app: given a master resume and a target job
posting, an LLM selects and emphasizes the most relevant experience and
renders the result to a polished, single-page PDF. It runs as a small web
app (FastAPI + a static frontend) self-hosted on a personal Kubernetes
cluster, with a full GitOps pipeline (push to `main` → CI builds the images →
ArgoCD deploys them) and an observability stack (Prometheus/Grafana/Loki,
alerting to Slack).

An earlier, simpler form of this project — tailor via a GitHub Actions
workflow on every push to a job description file, no web app or cluster
involved — still exists and works; see [Standalone CLI pipeline](#standalone-cli-pipeline)
below.

## How the web app works

```
                    ┌─────────────┐      ┌──────────────────────────┐
 job description ──▶│  frontend   │─────▶│  backend (FastAPI)       │
 (typed in the UI)  │ (static SPA)│      │  • tailor via Bedrock,   │
                     └─────────────┘      │    falls back to the    │
                                          │    Anthropic API        │
                                          │  • render PDF (Jinja2 + │
                                          │    Playwright)          │
                                          │  • store in SQLite      │
                                          └──────────────────────────┘
```

1. The frontend posts the job description to `POST /generate`.
2. The backend tailors the stored master resume against it (AWS Bedrock
   first, falling back to the direct Anthropic API on any AWS error — see
   [Bedrock fallback](#bedrock-fallback-anthropic-api)), renders the result
   to a PDF, and stores both in a SQLite database.
3. The frontend's **History** tab lists every past attempt (success or
   error) with a download link; the **Edit Master Resume** tab is a
   structured form for editing the master resume itself, with save +
   rollback across versions.

The master resume is **not** a static file at runtime: `app/master_resume.json`
is only the seed used the first time the database is empty. After that, the
database is the live source of truth — see [`app/README.md`](app/README.md).

## Repository layout

| Path | Purpose |
|---|---|
| [`app/`](app/README.md) | Resume data and the shared PDF-rendering logic: the master resume schema/seed, the Jinja2 print template, and `render_resume.py`. |
| [`backend/`](backend/README.md) | The FastAPI app — tailoring, PDF rendering, history, master-resume editing/versioning, metrics/logging. |
| [`frontend/`](frontend/README.md) | The static single-page UI (no build step) — Generate / History / Edit Resume. |
| [`helm/resume-builder/`](helm/resume-builder/README.md) | The Helm chart that deploys the whole thing to Kubernetes, plus the vendored Prometheus/Grafana/Loki monitoring stack. |
| [`argocd/`](argocd/README.md) | ArgoCD's own config (the `Application` that auto-deploys the chart above, notification wiring) — separate from the app chart since ArgoCD is a cluster-level tool. |
| [`.github/workflows/`](.github/workflows/README.md) | CI: builds and pushes images on every backend/frontend change, and the original standalone PDF-generation workflow. |
| [`infra/`](infra/README.md) | Terraform for the AWS side — OIDC + IAM role scoped to `bedrock:InvokeModel`, used by CI. |
| `resume_contact.py` | Merges real contact info (email/phone) in at runtime — see [Contact info](#contact-info) below. |
| `project_description.md` | Detailed build log / phase-by-phase project history. |

## Deployment architecture

```
push to main
     │
     ▼
GitHub Actions (.github/workflows/build-and-deploy.yml)
  builds the changed image(s) → pushes to ghcr.io → bumps the tag in
  helm/resume-builder/values.yaml → commits back to main
     │
     ▼
ArgoCD (in-cluster, polls the repo)
  detects the change → syncs the Helm chart → k3s applies it
     │
     ▼
k3s cluster
  frontend + backend (SQLite on a PVC) + Prometheus/Grafana/Loki/Alertmanager
  (alerts → Slack)
```

No manual `docker build`/`helm upgrade`/`kubectl` is part of normal
day-to-day work — see [`helm/resume-builder/README.md`](helm/resume-builder/README.md)
and [`argocd/README.md`](argocd/README.md) for how the pieces fit together,
and [`.github/workflows/README.md`](.github/workflows/README.md) for the CI
side.

## Running the backend locally (without Kubernetes)

```bash
pip install -r backend/requirements.txt
playwright install chromium
cp app/contact_info.local.json.example app/contact_info.local.json  # then fill in real info

uvicorn backend.main:app --reload --port 8000
```

Then open `frontend/index.html` directly, or serve `frontend/` with any
static file server — `fetch` calls use relative paths (`/generate`, etc.),
so the frontend needs to be reachable at the same origin as the backend
(that's what the Ingress does in the deployed cluster; locally, point
whatever's serving the frontend at `http://localhost:8000` or run both
behind a reverse proxy).

The SQLite DB defaults to `app/resume_builder.db` (gitignored) when
`DB_PATH` isn't set, so this works without a PVC.

## Contact info

`app/master_resume.json` is committed and meant to be safe to make public,
so it only ever holds placeholder email/phone. The real values are merged
in at runtime by `resume_contact.py`, from either:

- **Local runs / the standalone CLI pipeline:** copy
  `app/contact_info.local.json.example` to `app/contact_info.local.json`
  and fill in your real email/phone. That file is gitignored and never
  committed.
- **CI / the deployed app:** set `RESUME_EMAIL` and `RESUME_PHONE` (repo
  secrets for CI, delivered to the deployed app via the SealedSecret in
  `helm/resume-builder/templates/backend-sealedsecret.yaml`).

Neither is required — with no override present, the placeholder values are
used as-is. LinkedIn/GitHub handles are left as real values directly in
`master_resume.json`, since a resume is meant to surface those (unlike a
phone number, they're not something you'd want to keep off a public copy).

## Bedrock fallback (Anthropic API)

Tailoring calls Bedrock first. If that call raises a `boto3`/AWS error
(throttling, access denied, **no credentials** — this is always the case in
the deployed cluster, which has no AWS credentials at all), it automatically
retries the same request against the direct Anthropic API instead, using the
`anthropic` Python SDK and an `ANTHROPIC_API_KEY`:

- **Local runs / CI:** `ANTHROPIC_API_KEY` environment variable / repo secret.
- **The deployed app:** delivered via the same SealedSecret as the contact
  info above.

If Bedrock fails and `ANTHROPIC_API_KEY` isn't set, the request fails with
an error explaining that the fallback needs the key.

## Standalone CLI pipeline

Independent of the web app: `.github/workflows/generate-resume.yml` tailors
`app/master_resume.json` against `app/job_description.txt` and renders a PDF
on every push that changes the job description, uploading the PDF as a
workflow artifact — no server, cluster, or frontend involved. See
[`.github/workflows/README.md`](.github/workflows/README.md). Locally:

```bash
python backend/tailor_cli.py                                          # -> app/tailored_resume.json
python app/render_resume.py app/tailored_resume.json app/template.html app/output.pdf
```

## Infrastructure (AWS/Bedrock access for CI)

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in your AWS account ID
terraform init
terraform apply
```

See [`infra/README.md`](infra/README.md) for what this provisions and why
it's scoped the way it is.

## Status

The web app, its Kubernetes deployment, the GitOps pipeline, and the
monitoring stack are all live and verified end to end. See
`project_description.md` for the detailed phase-by-phase build history,
known issues, and open questions from earlier in the project.
