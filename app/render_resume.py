import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright

# Make the repo-root resume_contact module importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resume_contact import load_resume_json


def validate_resume_data(resume_data):
    """Minimal required-field check on tailored/master resume JSON.

    Jinja2 silently renders missing variables as blank instead of erroring,
    so a malformed or incomplete Bedrock response (missing keys, empty
    experience, etc.) would otherwise produce a PDF that looks "successful"
    but is broken. Fail loudly here instead.
    """
    required_top_level = ["name", "title", "contact", "summary", "experience"]
    missing = [
        field for field in required_top_level
        if not resume_data.get(field)
    ]
    if missing:
        raise ValueError(
            f"Resume JSON is missing required field(s): {', '.join(missing)}"
        )

    contact = resume_data.get("contact")
    if not isinstance(contact, dict) or not contact.get("email"):
        raise ValueError("Resume JSON 'contact' must include at least an 'email'")

    experience = resume_data.get("experience")
    if not isinstance(experience, list) or len(experience) == 0:
        raise ValueError("Resume JSON 'experience' must be a non-empty list")

    for i, job in enumerate(experience):
        if not isinstance(job, dict) or not job.get("role") or not job.get("company"):
            raise ValueError(
                f"Resume JSON experience[{i}] is missing 'role' or 'company'"
            )


def render_resume(resume_json_path, template_path, output_pdf_path):
    template_path = Path(template_path)

    # Merges in real email/phone from the environment or a gitignored local
    # file (see resume_contact.py); the committed JSON only ever holds
    # placeholders.
    resume_data = load_resume_json(resume_json_path)

    validate_resume_data(resume_data)

    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    template = env.get_template(template_path.name)
    html_content = template.render(**resume_data)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium")
        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")
        page.pdf(
            path=str(output_pdf_path),
            format="Letter",
            print_background=True,
            prefer_css_page_size=True,
        )
        browser.close()

    print(f"Success! Resume PDF saved to {output_pdf_path}")


if __name__ == "__main__":
    resume_json = sys.argv[1] if len(sys.argv) > 1 else "app/tailored_resume.json"
    template_file = sys.argv[2] if len(sys.argv) > 2 else "app/template.html"
    output_pdf = sys.argv[3] if len(sys.argv) > 3 else "app/output.pdf"

    if not Path(resume_json).exists():
        print(f"Error: {resume_json} not found. Falling back to master_resume.json.")
        resume_json = "app/master_resume.json"

    try:
        render_resume(resume_json, template_file, output_pdf)
    except ValueError as e:
        print(f"Error: invalid resume data in {resume_json}: {e}")
        sys.exit(1)
