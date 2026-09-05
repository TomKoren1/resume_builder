import io
import json

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import ValidationError
from pypdf import PdfReader

from .. import db
from ..auth import get_current_user, get_current_user_with_key
from ..llm import extract_master_resume
from ..observability import logger
from ..rate_limit import limiter
from ..schemas import MasterResume, MasterResumeVersion

router = APIRouter()


def _extract_pdf_text(upload: UploadFile, content: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Could not read '{upload.filename}' as a PDF.")


@router.get("/master-resume", response_model=MasterResume)
def get_master_resume(user_id: int = Depends(get_current_user)):
    resume = db.get_current_master_resume(user_id)
    if resume is None:
        raise HTTPException(status_code=404, detail="No master resume stored yet.")
    return resume


@router.put("/master-resume")
def put_master_resume(resume: MasterResume, user_id: int = Depends(get_current_user)):
    version_id = db.save_master_resume_version(user_id, resume.model_dump())
    logger.info(f"Saved master resume version {version_id} for user {user_id}")
    return {"message": "Saved.", "version_id": version_id}


@router.post("/master-resume/import")
@limiter.limit("10/hour")
async def import_master_resume(
    request: Request,
    texts: list[str] = Form(default=[]),
    files: list[UploadFile] = File(default=[]),
    user: tuple = Depends(get_current_user_with_key),
):
    """Consolidates one or more pasted/uploaded resumes into a master
    resume via the user's own Anthropic key (see llm.extract_master_resume).

    If the user has no master resume yet, the extracted result is saved
    immediately (nothing to lose/overwrite). If they already have one,
    it's returned for review instead - the frontend populates the edit
    form with it but leaves the actual Save step to the user, so an
    imperfect extraction can never silently clobber real existing data.
    """
    user_id, anthropic_api_key = user

    resume_texts = [t.strip() for t in texts if t and t.strip()]
    for upload in files:
        content = await upload.read()
        text = _extract_pdf_text(upload, content)
        if text.strip():
            resume_texts.append(text)

    if not resume_texts:
        raise HTTPException(status_code=400, detail="Provide at least one resume (pasted text or PDF).")

    try:
        extracted = extract_master_resume(resume_texts, anthropic_api_key)
    except json.JSONDecodeError:
        logger.error(f"Master resume import: model did not return valid JSON for user {user_id}.")
        raise HTTPException(status_code=500, detail="The model did not return valid JSON. Try again.")

    try:
        MasterResume.model_validate(extracted)
        is_valid = True
    except ValidationError:
        is_valid = False

    existing = db.get_current_master_resume(user_id)
    if existing is None and is_valid:
        version_id = db.save_master_resume_version(user_id, extracted)
        logger.info(f"Auto-saved imported master resume as version {version_id} for user {user_id}")
        return {
            "message": "Master resume created from your uploaded resumes.",
            "auto_saved": True,
            "data": extracted,
            "version_id": version_id,
        }

    logger.info(f"Extracted master resume for user {user_id}, awaiting review (valid={is_valid}).")
    return {
        "message": "Review the extracted resume below, then save." if is_valid
        else "Extraction is missing some required fields - fill those in below before saving.",
        "auto_saved": False,
        "data": extracted,
    }


@router.get("/master-resume/versions", response_model=list[MasterResumeVersion])
def get_master_resume_versions(user_id: int = Depends(get_current_user)):
    return db.list_master_resume_versions(user_id)


@router.post("/master-resume/versions/{version_id}/restore")
def restore_master_resume(version_id: int, user_id: int = Depends(get_current_user)):
    new_id = db.restore_master_resume_version(user_id, version_id)
    if new_id is None:
        raise HTTPException(status_code=404, detail="No such version.")
    logger.info(f"Restored master resume version {version_id} as new version {new_id} for user {user_id}")
    return {"message": "Restored.", "version_id": new_id}
