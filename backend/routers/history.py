import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from .. import db
from ..auth import get_current_user
from ..config import PDF_SCRATCH_PATH, TAILORED_OUTPUT_PATH, TEMPLATE_PATH
from ..schemas import EditableResume, HistoryDetail, HistoryItem

try:
    from app.render_resume import build_resume_html, render_resume
except ImportError:
    build_resume_html = None
    render_resume = None

router = APIRouter()


def _render_edited_resume(resume: EditableResume):
    """Writes the edited resume to the scratch JSON path, renders it to
    PDF via the same render_resume() /generate uses, and returns the raw
    PDF bytes. Raises if PDF rendering isn't available in this build."""
    if render_resume is None:
        raise HTTPException(status_code=500, detail="PDF rendering unavailable.")
    with open(TAILORED_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(resume.model_dump(), f, indent=4)
    render_resume(TAILORED_OUTPUT_PATH, TEMPLATE_PATH, PDF_SCRATCH_PATH)
    return Path(PDF_SCRATCH_PATH).read_bytes()


@router.get("/history", response_model=list[HistoryItem])
def get_history(user_id: int = Depends(get_current_user)):
    """List every past generation attempt (success and error), newest first."""
    return db.list_history(user_id)


@router.get("/history/{history_id}", response_model=HistoryDetail)
def get_history_detail(history_id: int, user_id: int = Depends(get_current_user)):
    entry = db.get_history_entry(user_id, history_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such history entry.")
    return entry


@router.get("/history/{history_id}/preview", response_class=HTMLResponse)
def preview_history_entry(history_id: int, user_id: int = Depends(get_current_user)):
    """Renders this entry's stored resume through the exact same
    template.html Playwright prints to PDF - loaded into an iframe by the
    frontend's click-to-edit History editor, so what you edit is what you
    get, not a separate approximation of it."""
    if build_resume_html is None:
        raise HTTPException(status_code=500, detail="Preview rendering unavailable.")
    entry = db.get_history_entry(user_id, history_id)
    if entry is None or entry["data"] is None:
        raise HTTPException(status_code=404, detail="No such history entry.")
    return build_resume_html(entry["data"], TEMPLATE_PATH)


@router.get("/history/{history_id}/download")
def download_history_pdf(history_id: int, user_id: int = Depends(get_current_user)):
    pdf_bytes = db.get_history_pdf(user_id, history_id)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="No PDF stored for that generation.")
    return Response(pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="resume-{history_id}.pdf"'
    })


@router.put("/history/{history_id}")
def update_history_entry(history_id: int, resume: EditableResume, http_request: Request, user_id: int = Depends(get_current_user)):
    """Overwrites this history entry's content and PDF in place - editing
    a past generation, not the master resume (which /master-resume owns)."""
    existing = db.get_history_entry(user_id, history_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="No such history entry.")

    pdf_bytes = _render_edited_resume(resume)
    db.update_history(user_id, history_id, resume.model_dump(), pdf_bytes)

    return {
        "message": "Saved.",
        "download_url": str(http_request.base_url) + f"history/{history_id}/download",
    }


@router.post("/history/{history_id}/save-as")
def save_history_entry_as_new(history_id: int, resume: EditableResume, http_request: Request, user_id: int = Depends(get_current_user)):
    """Same edit, but as a new history entry - the original generation
    (and its PDF) is left untouched."""
    existing = db.get_history_entry(user_id, history_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="No such history entry.")

    pdf_bytes = _render_edited_resume(resume)
    new_id = db.insert_history(
        user_id, existing["job_description"], status='success',
        tailored_resume=resume.model_dump(), pdf_bytes=pdf_bytes,
    )

    return {
        "message": "Saved as a new history entry.",
        "history_id": new_id,
        "download_url": str(http_request.base_url) + f"history/{new_id}/download",
    }
