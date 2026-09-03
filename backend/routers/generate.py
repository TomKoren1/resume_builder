import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from .. import db
from ..config import PDF_SCRATCH_PATH, TAILORED_OUTPUT_PATH, TEMPLATE_PATH
from ..llm import tailor_resume
from ..notifications import notify_slack
from ..observability import GENERATE_COUNT, logger
from ..schemas import GenerateRequest

try:
    from resume_contact import apply_contact_overrides
except ImportError:
    # Mock fallback if resume_contact isn't present in the Docker build context
    def apply_contact_overrides(data): pass

try:
    from app.render_resume import render_resume
except ImportError:
    render_resume = None

router = APIRouter()


@router.post("/generate")
def generate_resume(body: GenerateRequest, http_request: Request):
    logger.info("Received resume generation request.")

    master_resume_dict = db.get_current_master_resume()
    if master_resume_dict is None:
        GENERATE_COUNT.labels(status='error').inc()
        db.insert_history(body.job_description, status='error', error_message="No master resume stored.")
        logger.error("No master resume stored in the database.")
        raise HTTPException(status_code=500, detail="No master resume stored.")

    try:
        tailored_resume_dict = tailor_resume(master_resume_dict, body.job_description)
        apply_contact_overrides(tailored_resume_dict)

        # Save to disk as originally intended
        os.makedirs(os.path.dirname(TAILORED_OUTPUT_PATH), exist_ok=True)
        with open(TAILORED_OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(tailored_resume_dict, f, indent=4)

        GENERATE_COUNT.labels(status='success').inc()
        logger.info(f"Successfully tailored resume. Saved to {TAILORED_OUTPUT_PATH}")

        pdf_bytes = None
        if render_resume is not None:
            try:
                render_resume(TAILORED_OUTPUT_PATH, TEMPLATE_PATH, PDF_SCRATCH_PATH)
                pdf_bytes = Path(PDF_SCRATCH_PATH).read_bytes()
                logger.info("Rendered resume PDF.")
            except Exception as e:
                logger.error(f"PDF render failed: {e}")

        history_id = db.insert_history(
            body.job_description, status='success',
            tailored_resume=tailored_resume_dict, pdf_bytes=pdf_bytes,
        )
        download_url = str(http_request.base_url) + f"history/{history_id}/download" if pdf_bytes else None

        if download_url:
            notify_slack(f"✅ Resume generated: {download_url}")
        else:
            notify_slack("⚠️ Resume JSON was generated but the PDF render failed - check the logs.")

        return {
            "message": "Success! Resume generated and saved.",
            "data": tailored_resume_dict,
            "download_url": download_url,
        }

    except json.JSONDecodeError:
        GENERATE_COUNT.labels(status='error').inc()
        db.insert_history(body.job_description, status='error', error_message="The model did not return valid JSON.")
        logger.error("LLM did not return valid JSON.")
        raise HTTPException(status_code=500, detail="The model did not return valid JSON.")
    except Exception as e:
        GENERATE_COUNT.labels(status='error').inc()
        db.insert_history(body.job_description, status='error', error_message=str(e))
        logger.error(f"API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
