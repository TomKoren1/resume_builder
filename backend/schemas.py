from typing import Optional

from pydantic import BaseModel, Field

# Must match app/render_resume.py's DEFAULT_SECTION_ORDER - duplicated
# rather than imported so this schema module has no hard dependency on
# app.render_resume (which the rest of the backend treats as optional,
# see routers/generate.py's try/except around importing it).
DEFAULT_SECTION_ORDER = [
    "summary", "experience", "projects", "certifications", "education", "skills", "languages",
]
DEFAULT_SECTION_TITLES = {
    "summary": "Profile",
    "experience": "Professional Experience",
    "projects": "Technical Projects",
    "certifications": "Certifications",
    "education": "Education",
    "skills": "Skills",
    "languages": "Languages",
}
# Must match the body.theme-* blocks in app/template.html. An unknown
# value here just falls back to the :root defaults (classic) - no
# validation needed, an invalid theme is harmless, not a broken render.
THEMES = ["classic", "modern", "compact", "sidebar", "executive"]
DEFAULT_THEME = "classic"
# A plain hex string, set directly as the --accent CSS custom property -
# no curated palette/enum, any color the user picks works (template.html
# derives readable heading/subtitle/bar-tint shades from it via
# color-mix(), so there's no fixed set to validate against).
DEFAULT_COLOR = "#2b4f77"


class GenerateRequest(BaseModel):
    job_description: str
    theme: str = DEFAULT_THEME
    color: str = DEFAULT_COLOR
    photo: str = ""  # base64 data: URI, or "" for none - see EditableResume.photo


# --- Master resume, matching the schema app/template.html renders ---

class Contact(BaseModel):
    email: str = Field(..., min_length=1)
    phone: str = ""
    location: str = ""
    linkedin: str = ""
    github: str = ""


class ExperienceEntry(BaseModel):
    company: str = Field(..., min_length=1)
    role: str = Field(..., min_length=1)
    start_date: str = ""
    end_date: str = ""
    location: str = ""
    bullets: list[str] = Field(default_factory=list)


class ProjectEntry(BaseModel):
    name: str = Field(..., min_length=1)
    url: str = ""
    bullets: list[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    school: str = Field(..., min_length=1)
    degree: str = Field(..., min_length=1)
    start_date: str = ""
    end_date: str = ""
    notes: list[str] = Field(default_factory=list)


class CustomSection(BaseModel):
    """User-defined section beyond the fixed set (e.g. "Volunteer Work",
    "Publications") - id is a stable slug (see app/render_resume.py's
    build_resume_html, which appends it to section_order so it can be
    shown/hidden/reordered in the History editor like any built-in
    section). Exactly one of items/text is meaningful depending on type;
    the other stays empty."""
    id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    type: str = "bullets"  # "bullets" | "text"
    items: list[str] = Field(default_factory=list)
    text: str = ""


class MasterResume(BaseModel):
    name: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    contact: Contact
    summary: str = Field(..., min_length=1)
    skills: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    experience: list[ExperienceEntry] = Field(..., min_length=1)
    projects: list[ProjectEntry] = Field(default_factory=list)
    education: list[EducationEntry] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    custom_sections: list[CustomSection] = Field(default_factory=list)


# --- Editing a single already-generated resume (from History) ---

class EditableResume(MasterResume):
    """A tailored resume as stored in generation_history, plus per-render
    layout metadata - which sections to show and in what order. Not part
    of MasterResume: this is a property of one rendered PDF, not something
    the master source-of-truth needs."""
    section_order: list[str] = Field(default_factory=lambda: list(DEFAULT_SECTION_ORDER))
    hidden_sections: list[str] = Field(default_factory=list)
    section_titles: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_SECTION_TITLES))
    theme: str = DEFAULT_THEME
    color: str = DEFAULT_COLOR
    photo: str = ""  # base64 data: URI (client-side resized before upload), or "" for none


# --- History / version list responses ---

class HistoryItem(BaseModel):
    id: int
    created_at: str
    job_description: str
    status: str
    has_pdf: bool
    error_message: Optional[str] = None


class HistoryDetail(HistoryItem):
    data: Optional[dict] = None


class MasterResumeVersion(BaseModel):
    id: int
    created_at: str
    is_current: bool
