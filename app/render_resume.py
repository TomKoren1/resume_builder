import io
import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

# Make the repo-root resume_contact module importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resume_contact import load_resume_json

# Must match the @page rule in template.html (Letter, 0.5in top/bottom,
# 0.6in left/right margins) - used to figure out how much the content
# needs to be scaled down to fit on a single page.
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11
MARGIN_TOP_BOTTOM_IN = 0.5 * 2
MARGIN_LEFT_RIGHT_IN = 0.6 * 2
PX_PER_IN = 96
CONTENT_WIDTH_PX = round((PAGE_WIDTH_IN - MARGIN_LEFT_RIGHT_IN) * PX_PER_IN)
CONTENT_HEIGHT_PX = round((PAGE_HEIGHT_IN - MARGIN_TOP_BOTTOM_IN) * PX_PER_IN)

# Playwright's page.pdf(scale=...) floor; below this the text becomes too
# small to be a usable resume, so we'd rather fail loudly than ship it.
MIN_PRINT_SCALE = 0.75


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


def flatten_skills(skills):
    """Turn ["Category: a, b, c (with, nested, commas)", ...] into a flat
    ["a, b, c (with, nested, commas)", ...] list (category labels dropped,
    one item per original category) for the single-line skills display.
    Splitting further on "," would break apart parenthetical detail like
    "AWS (EC2, S3, ...)", so each category is kept whole."""
    flat = []
    for entry in skills or []:
        items = entry.split(":", 1)[1].strip() if ":" in entry else entry.strip()
        if items:
            flat.append(items)
    return flat


def render_resume(resume_json_path, template_path, output_pdf_path):
    template_path = Path(template_path)

    # Merges in real email/phone from the environment or a gitignored local
    # file (see resume_contact.py); the committed JSON only ever holds
    # placeholders.
    resume_data = load_resume_json(resume_json_path)

    validate_resume_data(resume_data)
    resume_data["skills_flat"] = flatten_skills(resume_data.get("skills"))

    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    template = env.get_template(template_path.name)
    html_content = template.render(**resume_data)

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chromium")
        page = browser.new_page(viewport={"width": CONTENT_WIDTH_PX, "height": 100})
        page.set_content(html_content, wait_until="networkidle")

        # Measure the natural (unscaled) content height at the resume's
        # actual printable width, so we know up front whether it'll fit on
        # one Letter page or needs to be shrunk down to fit.
        content_height_px = page.evaluate("document.body.scrollHeight")
        scale = 1.0
        if content_height_px > CONTENT_HEIGHT_PX:
            scale = max(MIN_PRINT_SCALE, CONTENT_HEIGHT_PX / content_height_px)

        pdf_bytes = page.pdf(
            format="Letter",
            print_background=True,
            prefer_css_page_size=True,
            scale=scale,
        )
        browser.close()

    page_count = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    if page_count > 1:
        raise ValueError(
            f"Rendered resume is {page_count} pages even at print scale "
            f"{scale:.2f} (floor is {MIN_PRINT_SCALE}). Trim content in the "
            f"resume JSON so it fits on a single page."
        )

    Path(output_pdf_path).write_bytes(pdf_bytes)

    if scale < 1.0:
        print(f"Note: shrunk to {scale:.0%} print scale to fit on one page.")
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
