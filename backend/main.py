import boto3
import json
import os
import sys
from pathlib import Path
from botocore.exceptions import BotoCoreError, ClientError

# Make the repo-root resume_contact module importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from resume_contact import apply_contact_overrides

# Plan A: AWS Bedrock (Claude Sonnet 5 isn't enabled for this account; 4.5 is).
BEDROCK_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
BEDROCK_REGION = "us-east-1"

# Plan B: direct Anthropic API, used when Bedrock is unavailable (e.g. the
# account-level token quota this project is currently blocked on). Needs
# ANTHROPIC_API_KEY set (repo secret in CI, env var locally).
ANTHROPIC_MODEL_ID = "claude-sonnet-4-5-20250929"

SYSTEM_PROMPT = (
    "You are an expert DevOps and Site Reliability Engineering technical recruiter. "
    "Your task is to take a master JSON resume and tailor it to a specific job description. "
    "Select the most relevant experience, emphasize the right tools (e.g., Kubernetes, AWS, Terraform), "
    "and output the final result STRICTLY as valid JSON matching the original schema. "
    "Do not include any conversational text, markdown formatting, or ```json blocks. Output ONLY raw JSON."
)


def call_bedrock(user_text):
    # When deployed to GitHub Actions, boto3 will automatically pick up the assumed OIDC role.
    bedrock_runtime = boto3.client('bedrock-runtime', region_name=BEDROCK_REGION)
    response = bedrock_runtime.converse(
        modelId=BEDROCK_MODEL_ID,
        messages=[{"role": "user", "content": [{"text": user_text}]}],
        system=[{"text": SYSTEM_PROMPT}],
        inferenceConfig={
            "temperature": 0.1,  # Low temperature ensures it sticks strictly to your facts, no hallucinations
            "maxTokens": 4096
        }
    )
    return response['output']['message']['content'][0]['text']


def call_anthropic_api(user_text):
    import anthropic  # imported lazily so Plan A doesn't require it to be installed

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set; cannot fall back to the direct Anthropic API.")

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=ANTHROPIC_MODEL_ID,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_text}]
    )
    return response.content[0].text


def get_tailored_resume_text(user_text):
    try:
        print(f"Sending request to Bedrock ({BEDROCK_MODEL_ID})...")
        return call_bedrock(user_text)
    except (ClientError, BotoCoreError) as e:
        print(f"Bedrock request failed ({e}); falling back to the direct Anthropic API...")
        return call_anthropic_api(user_text)


def tailor_resume(master_resume_path, job_description_path, output_path):
    # Load your inputs. master_resume.json only holds placeholder contact
    # info (real email/phone are merged in below, after tailoring, from
    # resume_contact.py) - the model doesn't need real PII to tailor bullets.
    with open(master_resume_path, 'r', encoding='utf-8') as f:
        master_resume = f.read()

    with open(job_description_path, 'r', encoding='utf-8') as f:
        job_description = f.read()

    user_text = f"Here is my master JSON resume:\n{master_resume}\n\nHere is the target job description:\n{job_description}"

    try:
        response_text = get_tailored_resume_text(user_text)

        # The model sometimes wraps its output in a markdown code fence
        # despite the system prompt forbidding it - strip it if present.
        response_text = response_text.strip()
        if response_text.startswith("```"):
            response_text = response_text.split("\n", 1)[1]
            response_text = response_text.rsplit("```", 1)[0].strip()

        # Parse it back to a Python dictionary to verify it is valid, unbroken JSON
        tailored_resume_dict = json.loads(response_text)

        # Merge in real contact info (env var / gitignored local file) now
        # that we're past the model call, so the placeholder in
        # master_resume.json never has to be the real thing.
        apply_contact_overrides(tailored_resume_dict)

        # Save the tailored JSON to disk, ready for Jinja2 processing
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(tailored_resume_dict, f, indent=4)

        print(f"Success! Tailored resume saved to {output_path}")
        return tailored_resume_dict

    except json.JSONDecodeError:
        print("Error: The model did not return valid JSON. Check the system prompt.")
        sys.exit(1)
    except Exception as e:
        print(f"API Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    tailor_resume('app/master_resume.json', 'app/job_description.txt', 'app/tailored_resume.json')
