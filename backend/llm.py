"""Bedrock-first, Anthropic-API-fallback resume tailoring."""
import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from . import config
from .observability import LLM_LATENCY, logger

SYSTEM_PROMPT = (
    "You are an expert DevOps and Site Reliability Engineering technical recruiter. "
    "Your task is to take a master JSON resume and tailor it to a specific job description. "
    "Select the most relevant experience, and emphasize the right tools (e.g., Kubernetes, AWS, Terraform). "
    "Don't just reorder or lightly trim the existing bullets and summary - actively REWRITE their phrasing "
    "in every section (profile summary, each experience bullet, project bullets) to mirror the job "
    "description's own terminology, priorities, and emphasis, so the resume reads as if it were written "
    "specifically for this role. Rephrase aggressively. "
    "This must never cross into fabrication: every tool, skill, achievement, and metric you write must "
    "already be present (even if worded differently) somewhere in the master resume. Never invent a "
    "technology, responsibility, or number that isn't there - rewriting the phrasing is expected and "
    "encouraged, inventing new facts is not. "
    "Output the final result STRICTLY as valid JSON matching the original schema. "
    "Copy every 'url' field verbatim, unmodified. Wrap every concrete tool or metric in **double asterisks**. "
    "Output ONLY raw JSON without markdown formatting."
)

EXTRACT_SYSTEM_PROMPT = (
    "You are an expert resume consolidator. You will be given the text of one or more resumes "
    "belonging to the same person - possibly overlapping, or from different points in time. "
    "Merge them into a single comprehensive master resume: combine every unique experience/project/"
    "education/certification entry, merge duplicate or overlapping jobs (same company and role) into "
    "one entry taking the union of their bullets, deduplicate skills/certifications/languages, and "
    "when resumes disagree on wording for the same fact, prefer whichever is more complete and specific. "
    "Do not invent information that isn't present in at least one of the provided resumes. "
    "Output the final result STRICTLY as valid JSON with exactly this shape: "
    '{"name": str, "title": str, "contact": {"email": str, "phone": str, "location": str, '
    '"linkedin": str, "github": str}, "summary": str, "skills": [str, ...], "languages": [str, ...], '
    '"experience": [{"company": str, "role": str, "start_date": str, "end_date": str, "location": str, '
    '"bullets": [str, ...]}], "projects": [{"name": str, "url": str, "bullets": [str, ...]}], '
    '"education": [{"school": str, "degree": str, "start_date": str, "end_date": str, "notes": [str, ...]}], '
    '"certifications": [str, ...]}. '
    "Every skills entry should follow a 'Category: item, item, item' format (e.g. 'Cloud: AWS, GCP, Terraform'). "
    "If a field genuinely isn't present anywhere in the source resumes, use an empty string or empty list "
    "for it rather than guessing. Output ONLY raw JSON without markdown formatting."
)


def _strip_json_fence(response_text):
    response_text = response_text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0].strip()
    return response_text


def call_bedrock(user_text):
    bedrock_runtime = boto3.client('bedrock-runtime', region_name=config.BEDROCK_REGION)
    response = bedrock_runtime.converse(
        modelId=config.BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        system=[{"text": SYSTEM_PROMPT}],
        inferenceConfig={"temperature": 0.1, "maxTokens": 4096}
    )
    return response['output']['message']['content'][0]['text']


def call_anthropic_api(user_text, api_key=None):
    import anthropic
    # api_key is the caller's own key for the multi-user web app (BYOK -
    # see backend/auth.py); falls back to the shared server-side key only
    # for the standalone CLI pipeline (backend/tailor_cli.py), which has
    # no per-user concept at all.
    key = api_key or config.ANTHROPIC_API_KEY
    if not key:
        raise RuntimeError("No Anthropic API key available.")
    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL_ID,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}]
    )
    return response.content[0].text


def tailor_resume(master_resume, job_description, anthropic_api_key=None):
    """Calls Bedrock first, falls back to the Anthropic API on any AWS
    error, strips a ```json markdown fence if present, and returns the
    parsed tailored resume dict. Raises json.JSONDecodeError if the model
    didn't return valid JSON, or the underlying LLM exception otherwise.

    anthropic_api_key: the calling user's own key (multi-user web app
    only - see routers/generate.py). Bedrock stays the shared,
    server-side-credentialed first attempt either way; only the
    Anthropic fallback becomes per-user.
    """
    user_text = (
        f"Here is my master JSON resume:\n{json.dumps(master_resume)}\n\n"
        f"Here is the target job description:\n{job_description}"
    )

    with LLM_LATENCY.labels(provider='bedrock').time():
        logger.info(f"Calling AWS Bedrock ({config.BEDROCK_MODEL_ID})...")
        try:
            response_text = call_bedrock(user_text)
        except (ClientError, BotoCoreError) as e:
            logger.warning(f"Bedrock failed ({e}); falling back to Anthropic API...")
            with LLM_LATENCY.labels(provider='anthropic').time():
                response_text = call_anthropic_api(user_text, api_key=anthropic_api_key)

    return json.loads(_strip_json_fence(response_text))


def extract_master_resume(resume_texts, api_key):
    """Consolidates one or more resume texts (pasted, or extracted from an
    uploaded PDF - see routers/master_resume.py's /import) into a single
    MasterResume-shaped dict, via the calling user's own Anthropic key.

    BYOK-only, deliberately no Bedrock path here (unlike tailor_resume) -
    this only ever runs for a logged-in multi-user web app request
    (Depends(get_current_user_with_key)), which always has a key by the
    time this is called.
    """
    import anthropic
    user_text = "\n\n---\n\n".join(
        f"Resume {i + 1}:\n{text}" for i, text in enumerate(resume_texts)
    )
    client = anthropic.Anthropic(api_key=api_key)
    with LLM_LATENCY.labels(provider='anthropic').time():
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL_ID,
            max_tokens=4096,
            system=EXTRACT_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_text}]
        )
    return json.loads(_strip_json_fence(response.content[0].text))
