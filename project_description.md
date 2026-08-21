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
*   [ ] Repo is not yet a git repository; `.github/` and `infra/` are empty placeholders.
*   [ ] No `requirements.txt`, `master_resume.json`, or `job_description.txt` exist yet — these are prerequisites for Phase 1.
*   [ ] Stray `,gitignore` file (comma, not a leading dot) has no effect — needs to be renamed to `.gitignore` and populated (`__pycache__/`, `.venv/`, `*.pdf`, `tailored_resume.json`, AWS creds, etc.).

## 5. Tasks for Claude Code (Next Steps)
Claude, please assist in executing the following phases sequentially:

### Phase 0: Repo Hygiene (prerequisite)
*   Initialize git (`git init`) and commit the current state.
*   Fix `.gitignore` (currently a dead `,gitignore` file) and populate it: `__pycache__/`, `*.pyc`, `.venv/`, `*.pdf`, `tailored_resume.json`, `.env`, local AWS credentials.
*   Add a `requirements.txt` (`boto3`, `jinja2`, `playwright`).
*   Add a sample `master_resume.json` and `job_description.txt` so `backend/main.py` is actually runnable end-to-end for local testing.

### Phase 1: Templating & PDF Generation
*   Create a simple, professional, single-page `template.html` optimized for print/PDF (using CSS `@page` rules).
*   Write a Python script (`render_resume.py`) that uses Jinja2 to map fields from `tailored_resume.json` into `template.html`.
*   Integrate Playwright into `render_resume.py` to convert the rendered HTML into `output.pdf`.

### Phase 2: Infrastructure as Code (Terraform)
*   Write the Terraform configuration to provision the necessary AWS resources. 
*   **Requirements:**
    *   An IAM OIDC Identity Provider for GitHub Actions.
    *   An IAM Role assumable by the GitHub Actions repository.
    *   A least-privilege IAM Policy attached to the role, granting ONLY `bedrock:InvokeModel` for the specific Claude 3.5 Sonnet model ARN.
*   Ensure the Terraform code is compatible with testing against LocalStack (`tflocal`) before deploying to live AWS.

### Phase 3: CI/CD Pipeline (GitHub Actions)
*   Create a `.github/workflows/generate-resume.yml` file.
*   **Workflow Steps:**
    *   Trigger on push to the `main` branch when `job_description.txt` changes.
    *   Checkout code.
    *   Set up Python and install requirements (`boto3`, `jinja2`, `playwright`).
    *   Install Playwright browsers.
    *   Configure AWS Credentials using the `aws-actions/configure-aws-credentials` action and the OIDC role from Phase 2.
    *   Execute `bedrock_generator.py` followed by `render_resume.py`.
    *   Upload the resulting `output.pdf` as a workflow artifact.

## 6. Coding Guidelines
*   Keep Python scripts modular and well-documented.
*   Ensure all JSON parsing includes proper error handling.
*   Write clean, easily maintainable HTML/CSS that aligns with standard resume formatting practices.

## 7. Open Questions / Risks
*   **Model availability & ARN:** `us.anthropic.claude-3-5-sonnet-20241022-v2:0` is a cross-region inference profile ID, not a raw model ARN — the Phase 2 IAM policy needs to scope to whichever ARN form Bedrock actually requires for `bedrock:InvokeModel` on this ID (inference profile ARN vs. foundation-model ARN vs. wildcard-on-region). Verify before locking down the policy.
*   **Bedrock region/access:** Confirm the AWS account has Bedrock model access enabled for this model in `us-east-1` before wiring CI — this is a manual console step, not something Terraform provisions.
*   **Master resume format:** No schema is defined yet for `master_resume.json`; Phase 0 should pin one down so the Jinja2 template (Phase 1) and the Bedrock system prompt agree on field names.
*   **Cost control:** High-volume applications means repeated Bedrock invocations — consider a rough per-run cost estimate and/or a guard against accidental workflow loops (e.g. the trigger path only watching `job_description.txt`, not `main_resume.json`, is a reasonable start but worth double-checking in Phase 3).