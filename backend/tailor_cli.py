"""Standalone CLI entrypoint for the CI pipeline
(.github/workflows/generate-resume.yml): tailors app/master_resume.json
against app/job_description.txt and writes app/tailored_resume.json.

Reuses the exact same tailor_resume() the web app's POST /generate uses
(backend/llm.py) rather than duplicating the Bedrock/Anthropic-fallback
logic here. Run from the repo root: `python backend/tailor_cli.py`.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.llm import tailor_resume
from resume_contact import apply_contact_overrides

MASTER_RESUME_PATH = "app/master_resume.json"
JOB_DESCRIPTION_PATH = "app/job_description.txt"
OUTPUT_PATH = "app/tailored_resume.json"


def main():
    with open(MASTER_RESUME_PATH, "r", encoding="utf-8") as f:
        master_resume = json.load(f)
    with open(JOB_DESCRIPTION_PATH, "r", encoding="utf-8") as f:
        job_description = f.read()

    tailored = tailor_resume(master_resume, job_description)
    apply_contact_overrides(tailored)

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(tailored, f, indent=4)

    print(f"Tailored resume written to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
