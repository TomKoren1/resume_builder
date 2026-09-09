import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import config, db
from ..auth import get_current_user_with_key
from ..config import PDF_SCRATCH_PATH, TAILORED_OUTPUT_PATH, TEMPLATE_PATH
from ..llm import tailor_resume
from ..notifications import notify_slack
from ..observability import GENERATE_COUNT, logger
from ..rate_limit import limiter
from ..schemas import GenerateRequest

try:
    from app.render_resume import render_resume
except ImportError:
    render_resume = None

router = APIRouter()


@router.post("/generate")
@limiter.limit("10/hour")
def generate_resume(body: GenerateRequest, request: Request, user: tuple = Depends(get_current_user_with_key)):
    user_id, anthropic_api_key = user
    logger.info(f"Received resume generation request from user {user_id}.")

    master_resume_dict = db.get_current_master_resume(user_id)
    if master_resume_dict is None:
        GENERATE_COUNT.labels(status='error').inc()
        db.insert_history(user_id, body.job_description, status='error', error_message="No master resume stored.")
        logger.error(f"No master resume stored for user {user_id}.")
        raise HTTPException(status_code=400, detail="No master resume stored. Fill one in under Edit Master Resume first.")

    try:
        # Bedrock is billed to the owner's AWS account - only that one
        # account may use it. Every other user is BYOK-only, straight to
        # the Anthropic API with their own key, no Bedrock attempt at all.
        use_bedrock = user_id == config.BEDROCK_ALLOWED_USER_ID
        tailored_resume_dict = tailor_resume(
            master_resume_dict, body.job_description,
            anthropic_api_key=anthropic_api_key, use_bedrock=use_bedrock,
        )
        # Deliberately no apply_contact_overrides() here - that merges in
        # the *project owner's* real email/phone (see resume_contact.py),
        # correct only for the standalone CLI pipeline (tailor_cli.py).
        # This is every signed-up user's own resume; their own contact
        # info (already in master_resume_dict, carried through by the LLM)
        # must never be silently replaced with the owner's.
        # Chosen at generate-time (frontend Generate tab); also changeable
        # afterward from the History editor, since it's stored on the
        # resume itself just like section_order/hidden_sections.
        tailored_resume_dict["theme"] = body.theme
        tailored_resume_dict["color"] = body.color
        tailored_resume_dict["photo"] = body.photo
        # Custom sections (Volunteer Work, Publications, etc.) aren't
        # job-tailoring targets - the LLM prompt never asks it to rewrite
        # them, and isn't told to preserve an unfamiliar field it wasn't
        # instructed about, so they silently vanish from its JSON output
        # more often than not. Carry them over from the master resume
        # verbatim instead of trusting the model to echo them back.
        tailored_resume_dict["custom_sections"] = master_resume_dict.get("custom_sections", [])

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
            user_id, body.job_description, status='success',
            tailored_resume=tailored_resume_dict, pdf_bytes=pdf_bytes,
        )
        # Absolute, for the Slack notification (read outside the browser,
        # so it needs a real scheme/host - unrelated to the bug below).
        absolute_download_url = str(request.base_url) + f"history/{history_id}/download" if pdf_bytes else None
        if absolute_download_url:
            notify_slack(f"✅ Resume generated: {absolute_download_url}")
        else:
            notify_slack("⚠️ Resume JSON was generated but the PDF render failed - check the logs.")

        # Relative, for the frontend: uvicorn runs without --proxy-headers
        # behind cloudflared -> Traefik, so request.base_url always reports
        # "http://" even though the site is only ever served over https.
        # Handing that to the browser as a link's href makes it drop the
        # Secure session cookie on click (SESSION_COOKIE_SECURE=true),
        # producing a 401 on download. A relative path resolves against
        # the page's own (https) origin instead.
        download_url = f"/history/{history_id}/download" if pdf_bytes else None

        return {
            "message": "Success! Resume generated and saved.",
            "data": tailored_resume_dict,
            "download_url": download_url,
        }

    except json.JSONDecodeError:
        GENERATE_COUNT.labels(status='error').inc()
        db.insert_history(user_id, body.job_description, status='error', error_message="The model did not return valid JSON.")
        logger.error("LLM did not return valid JSON.")
        raise HTTPException(status_code=500, detail="The model did not return valid JSON.")
    except Exception as e:
        GENERATE_COUNT.labels(status='error').inc()
        db.insert_history(user_id, body.job_description, status='error', error_message=str(e))
        logger.error(f"API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
