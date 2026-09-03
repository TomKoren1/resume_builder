"""Bedrock-first, Anthropic-API-fallback resume tailoring."""
import json

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from . import config
from .observability import LLM_LATENCY, logger

SYSTEM_PROMPT = (
    "You are an expert DevOps and Site Reliability Engineering technical recruiter. "
    "Your task is to take a master JSON resume and tailor it to a specific job description. "
    "Select the most relevant experience, emphasize the right tools (e.g., Kubernetes, AWS, Terraform), "
    "and output the final result STRICTLY as valid JSON matching the original schema. "
    "Copy every 'url' field verbatim, unmodified. Wrap every concrete tool or metric in **double asterisks**. "
    "Output ONLY raw JSON without markdown formatting."
)


def call_bedrock(user_text):
    bedrock_runtime = boto3.client('bedrock-runtime', region_name=config.BEDROCK_REGION)
    response = bedrock_runtime.converse(
        modelId=config.BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        system=[{"text": SYSTEM_PROMPT}],
        inferenceConfig={"temperature": 0.1, "maxTokens": 4096}
    )
    return response['output']['message']['content'][0]['text']


def call_anthropic_api(user_text):
    import anthropic
    if not config.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL_ID,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}]
    )
    return response.content[0].text


def tailor_resume(master_resume, job_description):
    """Calls Bedrock first, falls back to the Anthropic API on any AWS
    error, strips a ```json markdown fence if present, and returns the
    parsed tailored resume dict. Raises json.JSONDecodeError if the model
    didn't return valid JSON, or the underlying LLM exception otherwise."""
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
                response_text = call_anthropic_api(user_text)

    response_text = response_text.strip()
    if response_text.startswith("```"):
        response_text = response_text.split("\n", 1)[1]
        response_text = response_text.rsplit("```", 1)[0].strip()

    return json.loads(response_text)
