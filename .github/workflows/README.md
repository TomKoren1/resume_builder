# `.github/workflows/`

Two independent workflows — one is the CI/CD pipeline for the deployed web
app, the other is a standalone one-shot PDF generator.

## `build-and-deploy.yml` — CI/CD for the web app

Triggers on push to `main` when `backend/**` or `frontend/**` changes.
Builds and pushes only the component(s) that actually changed, tagged with
the short git SHA, then bumps that tag in `helm/resume-builder/values.yaml`
and commits it back to `main` — which ArgoCD (running in-cluster) picks up
and syncs. This workflow never touches the cluster directly; see
[`../../argocd/README.md`](../../argocd/README.md).

```
push (backend/** or frontend/**)
  ├─ changes          — dorny/paths-filter: which of backend/frontend changed?
  ├─ build-backend    — docker build+push → ghcr.io/tomkoren1/resume-backend:sha-<short>  (if backend changed)
  ├─ build-frontend   — docker build+push → ghcr.io/tomkoren1/resume-frontend:sha-<short> (if frontend changed)
  ├─ update-chart     — yq-bump the changed tag(s) in values.yaml, commit "[skip ci]", push
  └─ notify-failure   — POST to Slack if any of the above failed
```

**Anti-loop by construction, two independent guards:** the bump commit only
touches `helm/resume-builder/values.yaml`, which never matches this
workflow's `paths:` filter, so it can't re-trigger itself — and the
`[skip ci]` in the commit message is a second, independent guard (GitHub
natively skips runs on head commits containing it).

**Required secrets:** none beyond the automatic `GITHUB_TOKEN` (with
`contents: write` + `packages: write` — the pushed images are public, so no
pull secret is needed on the cluster side) and `SLACK_WEBHOOK` (for the
failure notification).

**One-time setup gotcha, already done for this repo but worth knowing if
ever repeating it elsewhere:** GHCR packages default to private even from
a public repo, and if bootstrapped with a personal token rather than the
repo's own Actions token, the repo also needs to be explicitly granted
write access under each package's *Manage Actions access* setting — both
are one-time steps in each package's GitHub UI settings, not something a
workflow re-run fixes.

## `generate-resume.yml` — standalone CLI pipeline

Independent of the web app entirely — see the root README's
[Standalone CLI pipeline](../../README.md#standalone-cli-pipeline) section.
Triggers on a push that changes `app/job_description.txt`, tailors
`app/master_resume.json` against it (`python backend/tailor_cli.py`,
Bedrock via OIDC, falling back to the Anthropic API), renders a PDF, and
uploads it as a workflow artifact.

**Required secrets:** `AWS_ROLE_ARN` (from `terraform apply` in
[`../../infra/`](../../infra/README.md)), `ANTHROPIC_API_KEY`, and
optionally `RESUME_EMAIL`/`RESUME_PHONE`.
