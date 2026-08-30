# Project Specification: Automated DevOps Resume Generator

> This is the detailed build log / phase history. For the current repo layout and how to run things, see [README.md](README.md). File paths below reflect the state at the time each phase was written and may not match the current layout in every place (e.g. `app/` was introduced later — see README for the up-to-date structure).

## 1. Project Overview
This project is an automated, docs-as-code pipeline designed to dynamically generate tailored resumes for DevOps and Site Reliability Engineering (SRE) job applications. 

Given a master resume (in JSON format) and a specific job description, the system uses an LLM to select and highlight the most relevant infrastructure, CI/CD, and cloud engineering experience. It then seamlessly renders a pixel-perfect, professionally designed PDF. The entire process is containerized and executed via a CI/CD pipeline.

**Goal:** Serve as a fully automated tool for high-volume, high-quality applications to tech companies, while also functioning as a strong portfolio project demonstrating cloud-native, IaC, and automation skills.

## 2. Technical Stack
*   **Core Logic:** Python 3.10+
*   **AI Backend:** AWS Bedrock (Claude 3.5 Sonnet) via `boto3`
*   **Templating:** Jinja2 + HTML/CSS
*   **PDF Generation:** Playwright (Headless Chromium)
*   **Infrastructure as Code (IaC):** Terraform (Tested locally via LocalStack/`tflocal`)
*   **CI/CD & Automation:** GitHub Actions + Docker
*   **Authentication:** AWS OIDC (OpenID Connect) for secure GitHub-to-AWS communication.

## 3. Architecture & Workflow Flow
1.  **Input:** The user pushes a `job_description.txt` to the repository.
2.  **AI Processing:** `backend/main.py` reads `master_resume.json` and the target job description. It invokes AWS Bedrock using the Converse API.
3.  **JSON Output:** Bedrock returns a strictly formatted `tailored_resume.json` emphasizing relevant tools (e.g., Kubernetes, AWS, Terraform).
4.  **Templating:** A Python script uses Jinja2 to parse `tailored_resume.json` and inject the data into a responsive HTML resume template (`template.html`).
5.  **PDF Rendering:** Playwright opens the generated HTML file and prints it to a formatted PDF (`resume_output.pdf`).
6.  **Pipeline Orchestration:** This entire workflow runs inside a Dockerized GitHub Actions runner, leveraging an IAM role via OIDC to authenticate with AWS Bedrock without long-lived credentials.

## 4. Current Progress
*   [x] **AI Parsing Logic:** `backend/main.py` prompts Claude to output valid, customized JSON based on the master resume and job description. Verified end-to-end against the live Anthropic API (Bedrock itself is currently quota-throttled on this account, see Phase 3 below) — found and fixed a real bug: the model wraps its JSON output in a ` ```json ` markdown fence despite the system prompt forbidding it, which broke `json.loads()`. Now stripped before parsing.
*   [x] **Phase 0 (repo hygiene):** git repo connected to GitHub, `.gitignore`, `requirements.txt`, sample `master_resume.json` / `job_description.txt` in place. See Phase 0 below.
*   [x] **Phase 1 (templating & PDF):** `template.html` (print-optimized, CSS `@page`) and `render_resume.py` (Jinja2 → Playwright PDF) written and **now verified end-to-end locally**. The Playwright "headless shell" download reliably stalled on this sandbox's network; fixed by forcing `channel="chromium"` in `render_resume.py` to use the full Chromium build (which does download successfully) instead.
*   [x] Phase 2 (Terraform) applied to real AWS. Phase 3 (GitHub Actions) written and wired up — OIDC auth confirmed working end-to-end; blocked only on a Bedrock account-level daily token quota (see below).

## 5. Tasks for Claude Code (Next Steps)
Claude, please assist in executing the following phases sequentially:

### Phase 0: Repo Hygiene (prerequisite) — DONE
*   [x] Git initialized and connected to GitHub (`origin` set, `main` pushed).
*   [x] `.gitignore` fixed (was a dead `,gitignore` file) and populated: `__pycache__/`, `.venv/`, `*.pdf`, `tailored_resume.json`, `.env`, `.aws/`.
*   [x] `requirements.txt` added (`boto3`, `jinja2`, `playwright`).
*   [x] `master_resume.json` (real resume content, defines the schema — later split so real contact info is no longer committed, see Phase 4) and `job_description.txt` (sample SRE posting) added so `backend/main.py` is runnable end-to-end locally.

### Phase 1: Templating & PDF Generation — DONE (verified locally)
*   [x] `template.html`: single-page, print-optimized (CSS `@page` rules), two-column layout for education/certifications/languages, sections for summary/experience/projects/skills matching the `master_resume.json` schema.
*   [x] `render_resume.py`: loads a resume JSON (defaults to `tailored_resume.json`, falls back to `master_resume.json` if absent) via Jinja2, renders `template.html`, and uses Playwright (sync API, `channel="chromium"`) to print it to `output.pdf`. Confirmed working end-to-end with a real tailored resume.
    ```
    python render_resume.py master_resume.json template.html output.pdf
    ```

### Phase 2: Infrastructure as Code (Terraform) — DONE
*   [x] `infra/oidc.tf`: GitHub Actions OIDC identity provider (`token.actions.githubusercontent.com`). Thumbprint is derived at plan time via the `tls_certificate` data source rather than hardcoded, so it can't go stale if GitHub rotates certs.
*   [x] `infra/oidc.tf`: IAM role (`github-actions-resume-builder-bedrock`) assumable only via `sts:AssumeRoleWithWebIdentity` from the configured `github_org/github_repo` on `github_branch` (defaults to `main`).
*   [x] `infra/iam.tf`: least-privilege inline policy granting only `bedrock:InvokeModel`, scoped to the exact ARNs required — both the cross-region inference-profile ARN *and* the underlying foundation-model ARN in each region the profile can route to (see Open Questions below, now resolved).
*   [x] `infra/variables.tf`, `outputs.tf`, `terraform.tfvars.example` for account/repo/model config.
*   [x] `terraform init`/`validate` pass locally (root module, no LocalStack-specific code needed — run via `tflocal` instead of `terraform` to redirect to LocalStack, per `tflocal`'s own transparent endpoint-rewriting).
*   [ ] Not yet run against LocalStack or real AWS (`plan`/`apply`) — needs your AWS account ID and confirmed Bedrock model access first.

### Phase 3: CI/CD Pipeline (GitHub Actions) — DONE (blocked on Bedrock quota)
*   [x] `.github/workflows/generate-resume.yml`: triggers on push to `main` when `job_description.txt` changes (plus manual `workflow_dispatch`), checks out code, sets up Python 3.11, installs `requirements.txt`, installs Playwright's Chromium via `playwright install --with-deps chromium`, assumes the Phase 2 OIDC role via `aws-actions/configure-aws-credentials`, runs `backend/main.py` then `render_resume.py`, and uploads `output.pdf` as a workflow artifact.
*   [x] `terraform apply`'d (Phase 2) — IAM role, OIDC trust, Bedrock policy all live in AWS.
*   [x] `AWS_ROLE_ARN` repo secret set. OIDC handshake **confirmed working** — initially failed because this repo's GitHub OIDC `sub` claim includes immutable owner/repo IDs (`repo:org@id/repo@id:ref:...`, GitHub's anti-repojacking behavior for renamed/transferred repos), which the exact-match trust policy rejected. Fixed in `infra/oidc.tf` by wildcarding the `sub` condition around the optional `@<id>` suffix.
*   [x] Model switched from `claude-3-5-sonnet-20241022-v2:0` → `claude-sonnet-5` → **`claude-sonnet-4-5-20250929-v1:0`** (current). Sonnet 5 returned a genuine `AccessDeniedException` (not enabled for this account); Sonnet 4.5 is accessible.
*   [ ] **Blocked**: the account is hitting `ThrottlingException: Too many tokens per day` on Bedrock — likely a low provisional daily quota on this account (shared with other projects) compounded by manual CLI testing during debugging. Not a code/infra bug — confirmed by testing the same tailoring logic directly against the Anthropic API (bypassing Bedrock entirely), which worked and surfaced a real bug (see below) now fixed in `backend/main.py`. Next step once the quota resets or is increased: re-run the workflow to get the actual first green CI run.

### Phase 4: PII Cleanup — DONE
*   [x] `master_resume.json` held the owner's real email/phone in cleartext since Phase 0. Git history was rewritten (`git filter-repo --replace-text`) to strip those two literal strings from every blob in every commit reachable from any local ref; verified by scanning every object in the rewritten repo (`git rev-list --objects --all` + per-blob grep) with zero matches, and confirming the original PII blob's SHA no longer resolves at all.
*   [ ] **Force-push of the rewritten history to `origin/main`** — approved by the owner, but not yet executed: this environment has no GitHub credentials configured (no `gh` auth, no stored HTTPS token, no SSH key), so it can't authenticate to push (or even to check the remote's current state first, as required before a force-push). Needs to be run from an environment with push access.
*   [x] `master_resume.json` now commits only placeholder email/phone (`you@example.com` / `000-0000000`). Real values are merged in at runtime by `resume_contact.py`, from `RESUME_EMAIL`/`RESUME_PHONE` repo secrets in CI or a gitignored `app/contact_info.local.json` locally — see README's "Contact info" section. LinkedIn/GitHub handles are left as real values (intentionally public, not treated as secrets).

## 6. Coding Guidelines
*   Keep Python scripts modular and well-documented.
*   Ensure all JSON parsing includes proper error handling.
*   Write clean, easily maintainable HTML/CSS that aligns with standard resume formatting practices.

## 7. Open Questions / Risks
*   **Model availability & ARN — RESOLVED:** `us.anthropic.claude-3-5-sonnet-20241022-v2:0` is a cross-region inference profile ID. The Phase 2 policy (`infra/iam.tf`) now grants `bedrock:InvokeModel` on both the inference-profile ARN and the underlying foundation-model ARN in each of `us-east-1`/`us-east-2`/`us-west-2` (the profile's routing regions) — Bedrock requires permission on both halves or invocation fails with `AccessDeniedException` even though the policy "looks" like it covers the model.
*   **Bedrock region/access:** Confirm the AWS account has Bedrock model access enabled for this model in `us-east-1` before wiring CI — this is a manual console step, not something Terraform provisions.
*   **Master resume format:** No schema is defined yet for `master_resume.json`; Phase 0 should pin one down so the Jinja2 template (Phase 1) and the Bedrock system prompt agree on field names.
*   **Cost control:** High-volume applications means repeated Bedrock invocations — consider a rough per-run cost estimate and/or a guard against accidental workflow loops (e.g. the trigger path only watching `job_description.txt`, not `main_resume.json`, is a reasonable start but worth double-checking in Phase 3).