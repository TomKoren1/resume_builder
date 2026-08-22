# Project Specification: Automated DevOps Resume Generator

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
*   [x] **AI Parsing Logic:** The AWS Bedrock integration script (`backend/main.py`) has been written and prompts Claude 3.5 Sonnet to output valid, customized JSON based on the master resume and job description. (Not yet run against live Bedrock or covered by tests.)
*   [x] **Phase 0 (repo hygiene):** git repo connected to GitHub, `.gitignore`, `requirements.txt`, sample `master_resume.json` / `job_description.txt` in place. See Phase 0 below.
*   [x] **Phase 1 (templating & PDF):** `template.html` (print-optimized, CSS `@page`) and `render_resume.py` (Jinja2 → Playwright PDF) written. **Not yet locally verified end-to-end** — this dev sandbox's networking couldn't reliably complete the one-time Playwright Chromium browser download (~200MB, kept stalling). Verification deferred to Phase 3, where GitHub Actions runs `playwright install` itself without this constraint.
*   [ ] `.github/` and `infra/` are still empty placeholders — Phase 2/3 work.

## 5. Tasks for Claude Code (Next Steps)
Claude, please assist in executing the following phases sequentially:

### Phase 0: Repo Hygiene (prerequisite) — DONE
*   [x] Git initialized and connected to GitHub (`origin` set, `main` pushed).
*   [x] `.gitignore` fixed (was a dead `,gitignore` file) and populated: `__pycache__/`, `.venv/`, `*.pdf`, `tailored_resume.json`, `.env`, `.aws/`.
*   [x] `requirements.txt` added (`boto3`, `jinja2`, `playwright`).
*   [x] Sample `master_resume.json` (placeholder "Jane Doe" data, defines the schema — replace with your real resume content) and `job_description.txt` (sample SRE posting) added so `backend/main.py` is runnable end-to-end locally.

### Phase 1: Templating & PDF Generation — DONE (pending local verification)
*   [x] `template.html`: single-page, print-optimized (CSS `@page` rules), two-column layout for education/certifications/languages, sections for summary/experience/projects/skills matching the `master_resume.json` schema.
*   [x] `render_resume.py`: loads a resume JSON (defaults to `tailored_resume.json`, falls back to `master_resume.json` if absent) via Jinja2, renders `template.html`, and uses Playwright (sync API) to print it to `output.pdf`.
*   [ ] **Not yet run successfully in this environment** — Playwright's one-time Chromium download stalled repeatedly over this dev sandbox's slow/restricted network. Real verification is deferred to Phase 3 CI. If you want to sanity-check locally first, run (after `pip install -r requirements.txt && playwright install chromium`):
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

### Phase 3: CI/CD Pipeline (GitHub Actions) — DONE (pending live run)
*   [x] `.github/workflows/generate-resume.yml`: triggers on push to `main` when `job_description.txt` changes (plus manual `workflow_dispatch`), checks out code, sets up Python 3.11, installs `requirements.txt`, installs Playwright's Chromium via `playwright install --with-deps chromium`, assumes the Phase 2 OIDC role via `aws-actions/configure-aws-credentials`, runs `backend/main.py` then `render_resume.py`, and uploads `output.pdf` as a workflow artifact.
*   [ ] **Not yet run** — needs two things first:
    1.  `terraform apply` (Phase 2) so the IAM role actually exists.
    2.  A repo secret `AWS_ROLE_ARN` set to the `github_actions_role_arn` Terraform output.
    Once both are in place, push a change to `job_description.txt` (or trigger manually) to verify the pipeline end-to-end — this is also the first real verification of Phases 1 and 2.

## 6. Coding Guidelines
*   Keep Python scripts modular and well-documented.
*   Ensure all JSON parsing includes proper error handling.
*   Write clean, easily maintainable HTML/CSS that aligns with standard resume formatting practices.

## 7. Open Questions / Risks
*   **Model availability & ARN — RESOLVED:** `us.anthropic.claude-3-5-sonnet-20241022-v2:0` is a cross-region inference profile ID. The Phase 2 policy (`infra/iam.tf`) now grants `bedrock:InvokeModel` on both the inference-profile ARN and the underlying foundation-model ARN in each of `us-east-1`/`us-east-2`/`us-west-2` (the profile's routing regions) — Bedrock requires permission on both halves or invocation fails with `AccessDeniedException` even though the policy "looks" like it covers the model.
*   **Bedrock region/access:** Confirm the AWS account has Bedrock model access enabled for this model in `us-east-1` before wiring CI — this is a manual console step, not something Terraform provisions.
*   **Master resume format:** No schema is defined yet for `master_resume.json`; Phase 0 should pin one down so the Jinja2 template (Phase 1) and the Bedrock system prompt agree on field names.
*   **Cost control:** High-volume applications means repeated Bedrock invocations — consider a rough per-run cost estimate and/or a guard against accidental workflow loops (e.g. the trigger path only watching `job_description.txt`, not `main_resume.json`, is a reasonable start but worth double-checking in Phase 3).