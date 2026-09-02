import html
import io
import json
import re
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

# Make the repo-root resume_contact module importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resume_contact import load_resume_json

# Must match the @page rule in template.html (Letter, 0.45in top/bottom,
# 0.55in left/right margins) - used to figure out how much the content
# needs to be scaled down to fit on a single page, and passed into the
# template so it can flex-distribute any leftover space between sections
# instead of leaving it as dead whitespace at the bottom.
PAGE_WIDTH_IN = 8.5
PAGE_HEIGHT_IN = 11
MARGIN_TOP_BOTTOM_IN = 0.45 * 2
MARGIN_LEFT_RIGHT_IN = 0.55 * 2
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


MAX_SKILLS_SHOWN = 12


def flatten_skills(skills, max_items=MAX_SKILLS_SHOWN):
    """Turn ["Category: AWS (EC2, S3, ...), Terraform, ...", ...] into a
    short, flat list of top-level skill names for a single-line display
    (parenthetical sub-detail like "(EC2, S3, ...)" is dropped - too
    granular for a capped list). Samples round-robin across categories
    (one item from each category per pass) rather than taking categories
    in full one at a time, so a long list still gets trimmed to a
    representative spread instead of losing entire categories off the end.
    """
    category_items = []
    for entry in skills or []:
        text = entry.split(":", 1)[1] if ":" in entry else entry
        text_wo_paren = re.sub(r"\([^)]*\)", "", text)
        items = [tok.strip() for tok in text_wo_paren.split(",") if tok.strip()]
        if items:
            category_items.append(items)

    flat = []
    round_index = 0
    while len(flat) < max_items and round_index < max(len(items) for items in category_items or [[]]):
        for items in category_items:
            if round_index < len(items):
                flat.append(items[round_index])
                if len(flat) >= max_items:
                    break
        round_index += 1
    return flat


def ensure_https(url):
    """Add a https:// scheme to a bare domain (e.g. "github.com/x") so it
    works as a clickable href; leaves an already-schemed URL untouched."""
    if not url:
        return url
    return url if re.match(r"^https?://", url) else f"https://{url}"


_BOLD_MARKDOWN_RE = re.compile(r"\*\*(.+?)\*\*")


def highlight_text(text):
    """HTML-escape free text and convert **phrase** markdown to <strong>.

    Bolding is manual-only, authored directly into the resume JSON (by a
    human in master_resume.json, or by the model in a tailored resume -
    see the system prompt in backend/main.py, which asks it to bold the
    one or two most important words/phrases per bullet). No auto-keyword
    guessing: that produced an inconsistent, scattershot look.
    """
    if not text:
        return text
    escaped = html.escape(text)
    return _BOLD_MARKDOWN_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)


def render_resume(resume_json_path, template_path, output_pdf_path):
    template_path = Path(template_path)

    # Merges in real email/phone from the environment or a gitignored local
    # file (see resume_contact.py); the committed JSON only ever holds
    # placeholders.
    resume_data = load_resume_json(resume_json_path)

    validate_resume_data(resume_data)
    resume_data["skills_flat"] = flatten_skills(resume_data.get("skills"))

    # Contact links: LinkedIn/GitHub are stored as bare-or-schemed URLs;
    # the template shows a short label ("LinkedIn"/"GitHub") that links here.
    contact = resume_data.get("contact", {})
    if contact.get("linkedin"):
        contact["linkedin_url"] = ensure_https(contact["linkedin"])
    if contact.get("github"):
        contact["github_url"] = ensure_https(contact["github"])

    # Project headline -> repo link, and convert any **manual** bold
    # markdown authored into the resume JSON to <strong> (see highlight_text).
    resume_data["summary"] = highlight_text(resume_data.get("summary"))
    for job in resume_data.get("experience", []):
        job["bullets"] = [highlight_text(b) for b in job.get("bullets", [])]
    for project in resume_data.get("projects", []):
        project["bullets"] = [highlight_text(b) for b in project.get("bullets", [])]
        if project.get("url"):
            project["url"] = ensure_https(project["url"])

    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    template = env.get_template(template_path.name)
    html_content = template.render(page_fill_height_px=CONTENT_HEIGHT_PX, **resume_data)

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
