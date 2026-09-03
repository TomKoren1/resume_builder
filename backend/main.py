import boto3
import json
import os
import sys
import logging
import logging_loki
import requests
from pathlib import Path
from botocore.exceptions import BotoCoreError, ClientError

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# --- OBSERVABILITY SETUP ---
# 1. Logging (Sends directly to Loki container)
loki_handler = logging_loki.LokiHandler(
    url=os.environ.get("LOKI_URL", "http://loki:3100/loki/api/v1/push"),
    tags={"app": "resume_backend"},
    version="1",
)
logger = logging.getLogger("resume_builder")
logger.setLevel(logging.INFO)
logger.addHandler(loki_handler)
logger.addHandler(logging.StreamHandler(sys.stdout)) # Also log to Docker console

# 2. Metrics (Scraped by Prometheus via /metrics endpoint)
GENERATE_COUNT = Counter('resume_generation_total', 'Total resumes generated', ['status'])
LLM_LATENCY = Histogram('llm_inference_seconds', 'Time spent waiting for LLM', ['provider'])

# --- APP SETUP ---
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from resume_contact import apply_contact_overrides
except ImportError:
    # Mock fallback if resume_contact isn't present in the Docker build context
    def apply_contact_overrides(data): pass

try:
    from app.render_resume import render_resume, validate_resume_data
except ImportError:
    render_resume = None
    validate_resume_data = None

from . import db

PDF_SCRATCH_PATH = "/tmp/resume_render.pdf"  # scratch only - the DB blob is canonical
TEMPLATE_PATH = "app/template.html"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK")


def notify_slack(text):
    """Best-effort Slack push. Never raises - a notification failure
    shouldn't fail the /generate request. Incoming webhooks can only post
    text/links, not upload files, so this sends a download link rather
    than the PDF itself."""
    if not SLACK_WEBHOOK_URL:
        return
    try:
        requests.post(SLACK_WEBHOOK_URL, json={"text": text}, timeout=5)
    except Exception as e:
        logger.warning(f"Slack notification failed: {e}")

app = FastAPI()


@app.on_event("startup")
def _startup():
    db.init_db()


# Allow the frontend to communicate with this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class GenerateRequest(BaseModel):
    job_description: str

BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BEDROCK_REGION = "us-east-1"
ANTHROPIC_MODEL_ID = "claude-sonnet-4-5-20250929"

SYSTEM_PROMPT = (
    "You are an expert DevOps and Site Reliability Engineering technical recruiter. "
    "Your task is to take a master JSON resume and tailor it to a specific job description. "
    "Select the most relevant experience, emphasize the right tools (e.g., Kubernetes, AWS, Terraform), "
    "and output the final result STRICTLY as valid JSON matching the original schema. "
    "Copy every 'url' field verbatim, unmodified. Wrap every concrete tool or metric in **double asterisks**. "
    "Output ONLY raw JSON without markdown formatting."
)

def call_bedrock(user_text):
    bedrock_runtime = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION)
    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        system=[{"text": SYSTEM_PROMPT}],
        inferenceConfig={"temperature": 0.1, "maxTokens": 4096}
    )
    return response['output']['message']['content'][0]['text']

def call_anthropic_api(user_text):
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=ANTHROPIC_MODEL_ID,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}]
    )
    return response.content[0].text

@app.get("/metrics")
def metrics():
    """Endpoint for Prometheus to scrape metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

@app.get("/history")
def get_history():
    """List every past generation attempt (success and error), newest first."""
    return db.list_history()

@app.get("/history/{history_id}/download")
def download_history_pdf(history_id: int):
    pdf_bytes = db.get_history_pdf(history_id)
    if pdf_bytes is None:
        raise HTTPException(status_code=404, detail="No PDF stored for that generation.")
    return Response(pdf_bytes, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="resume-{history_id}.pdf"'
    })

@app.get("/master-resume")
def get_master_resume():
    resume = db.get_current_master_resume()
    if resume is None:
        raise HTTPException(status_code=404, detail="No master resume stored yet.")
    return resume

@app.put("/master-resume")
def put_master_resume(resume: dict):
    if validate_resume_data is None:
        raise HTTPException(status_code=500, detail="Validation logic unavailable.")
    try:
        validate_resume_data(resume)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    version_id = db.save_master_resume_version(resume)
    logger.info(f"Saved master resume version {version_id}")
    return {"message": "Saved.", "version_id": version_id}

@app.get("/master-resume/versions")
def get_master_resume_versions():
    return db.list_master_resume_versions()

@app.post("/master-resume/versions/{version_id}/restore")
def restore_master_resume(version_id: int):
    new_id = db.restore_master_resume_version(version_id)
    if new_id is None:
        raise HTTPException(status_code=404, detail="No such version.")
    logger.info(f"Restored master resume version {version_id} as new version {new_id}")
    return {"message": "Restored.", "version_id": new_id}

@app.post("/generate")
def generate_resume(body: GenerateRequest, http_request: Request):
    logger.info("Received resume generation request.")

    master_resume_dict = db.get_current_master_resume()
    if master_resume_dict is None:
        GENERATE_COUNT.labels(status='error').inc()
        db.insert_history(body.job_description, status='error', error_message="No master resume stored.")
        logger.error("No master resume stored in the database.")
        raise HTTPException(status_code=500, detail="No master resume stored.")

    master_resume = json.dumps(master_resume_dict)
    output_path = 'app/tailored_resume.json'

    user_text = f"Here is my master JSON resume:\n{master_resume}\n\nHere is the target job description:\n{body.job_description}"

    try:
        # Try Bedrock First
        with LLM_LATENCY.labels(provider='bedrock').time():
            logger.info(f"Calling AWS Bedrock ({BEDROCK_MODEL_ID})...")
            try:
                response_text = call_bedrock(user_text)
            except (ClientError, BotoCoreError) as e:
                logger.warning(f"Bedrock failed ({e}); falling back to Anthropic API...")
                # Fallback to Anthropic API
                with LLM_LATENCY.labels(provider='anthropic').time():
                    response_text = call_anthropic_api(user_text)

        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0].strip()

        tailored_resume_dict = json.loads(response_text)
        apply_contact_overrides(tailored_resume_dict)

        # Save to disk as originally intended
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(tailored_resume_dict, f, indent=4)

        GENERATE_COUNT.labels(status='success').inc()
        logger.info(f"Successfully tailored resume. Saved to {output_path}")

        pdf_bytes = None
        if render_resume is not None:
            try:
                render_resume(output_path, TEMPLATE_PATH, PDF_SCRATCH_PATH)
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