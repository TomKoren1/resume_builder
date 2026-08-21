import json
import sys
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from playwright.sync_api import sync_playwright


def render_resume(resume_json_path, template_path, output_pdf_path):
    template_path = Path(template_path)

    with open(resume_json_path, "r", encoding="utf-8") as f:
        resume_data = json.load(f)

    env = Environment(loader=FileSystemLoader(str(template_path.parent)))
    template = env.get_template(template_path.name)
    html_content = template.render(**resume_data)

    with sync_playwright() as p:
        browser = p.chromium.launch()
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
    resume_json = sys.argv[1] if len(sys.argv) > 1 else "tailored_resume.json"
    template_file = sys.argv[2] if len(sys.argv) > 2 else "template.html"
    output_pdf = sys.argv[3] if len(sys.argv) > 3 else "output.pdf"

    if not Path(resume_json).exists():
        print(f"Error: {resume_json} not found. Falling back to master_resume.json.")
        resume_json = "master_resume.json"

    render_resume(resume_json, template_file, output_pdf)
