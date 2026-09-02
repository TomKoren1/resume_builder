import boto3
import json
import os
import sys
import logging
import logging_loki
from pathlib import Path
from botocore.exceptions import BotoCoreError, ClientError

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# --- OBSERVABILITY SETUP ---
# 1. Logging (Sends directly to Loki container)
loki_handler = logging_loki.LokiHandler(
    url="http://loki:3100/loki/api/v1/push",
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

app = FastAPI()

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

@app.post("/generate")
def generate_resume(request: GenerateRequest):
    logger.info("Received resume generation request.")
    
    master_resume_path = 'app/master_resume.json'
    output_path = 'app/tailored_resume.json'
    
    if not os.path.exists(master_resume_path):
        GENERATE_COUNT.labels(status='error').inc()
        logger.error(f"Missing master resume file at {master_resume_path}")
        raise HTTPException(status_code=500, detail="Master resume file not found.")

    with open(master_resume_path, 'r', encoding='utf-8') as f:
        master_resume = f.read()

    user_text = f"Here is my master JSON resume:\n{master_resume}\n\nHere is the target job description:\n{request.job_description}"

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
        
        return {"message": "Success! Resume generated and saved.", "data": tailored_resume_dict}

    except json.JSONDecodeError:
        GENERATE_COUNT.labels(status='error').inc()
        logger.error("LLM did not return valid JSON.")
        raise HTTPException(status_code=500, detail="The model did not return valid JSON.")
    except Exception as e:
        GENERATE_COUNT.labels(status='error').inc()
        logger.error(f"API Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))