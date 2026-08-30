"""Runtime contact-info overlay for the resume pipeline.

`app/master_resume.json` is committed to the repo (and is meant to be safe
to make public) so it only ever holds placeholder contact info. The real
email/phone are sourced here at runtime, from one of:

  1. RESUME_EMAIL / RESUME_PHONE environment variables — how CI supplies
     them, via GitHub Actions secrets (see .github/workflows/generate-resume.yml).
  2. app/contact_info.local.json — a gitignored file for local runs. Copy
     app/contact_info.local.json.example to app/contact_info.local.json and
     fill in your real info; it is never committed.

Neither source is required: if both are absent, the placeholder values in
master_resume.json are used as-is, so the pipeline still runs end-to-end
(e.g. on a fresh fork) without needing real personal data.
"""

import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
LOCAL_OVERRIDE_PATH = REPO_ROOT / "app" / "contact_info.local.json"

# Only these fields are ever sourced this way. LinkedIn/GitHub handles are
# intentionally public (that's the point of putting them on a resume) so
# they live directly in master_resume.json and aren't treated as secrets.
OVERRIDE_FIELDS = ("email", "phone")


def load_contact_overrides():
    """Return a dict of real contact field overrides, or {} if none are set."""
    overrides = {}

    if LOCAL_OVERRIDE_PATH.exists():
        with open(LOCAL_OVERRIDE_PATH, "r", encoding="utf-8") as f:
            file_overrides = json.load(f)
        for field in OVERRIDE_FIELDS:
            if file_overrides.get(field):
                overrides[field] = file_overrides[field]

    # Environment variables (e.g. from a GitHub Actions secret) win over the
    # local file, so CI doesn't need a contact_info.local.json checked out.
    for field in OVERRIDE_FIELDS:
        env_value = os.environ.get(f"RESUME_{field.upper()}")
        if env_value:
            overrides[field] = env_value

    return overrides


def apply_contact_overrides(resume_data):
    """Merge real contact info into resume_data['contact'] in place.

    No-op for any field with no override available, so placeholder values
    pass through untouched.
    """
    overrides = load_contact_overrides()
    contact = resume_data.get("contact")
    if overrides and isinstance(contact, dict):
        contact.update(overrides)
    return resume_data


def load_resume_json(path):
    """Load a resume JSON file (master or tailored) with real contact info
    merged in from the environment/local override file."""
    with open(path, "r", encoding="utf-8") as f:
        resume_data = json.load(f)
    return apply_contact_overrides(resume_data)
