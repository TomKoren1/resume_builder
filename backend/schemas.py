from typing import Optional

from pydantic import BaseModel, Field

# Must match app/render_resume.py's DEFAULT_SECTION_ORDER - duplicated
# rather than imported so this schema module has no hard dependency on
# app.render_resume (which the rest of the backend treats as optional,
# see routers/generate.py's try/except around importing it).
DEFAULT_SECTION_ORDER = [
    "summary", "experience", "projects", "certifications", "education", "skills", "languages",
]


class GenerateRequest(BaseModel):
    job_description: str


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


# --- Editing a single already-generated resume (from History) ---

class EditableResume(MasterResume):
    """A tailored resume as stored in generation_history, plus per-render
    layout metadata - which sections to show and in what order. Not part
    of MasterResume: this is a property of one rendered PDF, not something
    the master source-of-truth needs."""
    section_order: list[str] = Field(default_factory=lambda: list(DEFAULT_SECTION_ORDER))
    hidden_sections: list[str] = Field(default_factory=list)


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
