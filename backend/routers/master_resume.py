from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import get_current_user
from ..observability import logger
from ..schemas import MasterResume, MasterResumeVersion

router = APIRouter()


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
