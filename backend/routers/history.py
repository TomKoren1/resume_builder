from fastapi import APIRouter, HTTPException, Response

from .. import db
from ..schemas import HistoryItem

router = APIRouter()


@router.get("/history", response_model=list[HistoryItem])
def get_history():
    """List every past generation attempt (success and error), newest first."""
    return db.list_history()


@router.get("/history/{history_id}/download")
def download_history_pdf(history_id: int):
    pdf_bytes = db.get_history_pdf(history_id)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="No PDF stored for that generation.")
    return Response(pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="resume-{history_id}.pdf"'
    })
