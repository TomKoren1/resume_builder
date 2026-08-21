import boto3
import json
import sys

def tailor_resume(master_resume_path, job_description_path, output_path):
    # Initialize the Bedrock Runtime client
    # When deployed to GitHub Actions, boto3 will automatically pick up the assumed OIDC role
    bedrock_runtime = boto3.client('bedrock-runtime', region_name='us-east-1')
    
    # Using Claude 3.5 Sonnet for high reasoning capabilities
    model_id = "us.anthropic.claude-3-5-sonnet-20241022-v2:0" 
    
    # Load your inputs
    with open(master_resume_path, 'r', encoding='utf-8') as f:
        master_resume = f.read()
        
    with open(job_description_path, 'r', encoding='utf-8') as f:
        job_description = f.read()

    # The System Prompt acts as the strict bounds for the model's behavior
    system_prompt = [{
        "text": (
            "You are an expert DevOps and Site Reliability Engineering technical recruiter. "
            "Your task is to take a master JSON resume and tailor it to a specific job description. "
            "Select the most relevant experience, emphasize the right tools (e.g., Kubernetes, AWS, Terraform), "
            "and output the final result STRICTLY as valid JSON matching the original schema. "
            "Do not include any conversational text, markdown formatting, or ```json blocks. Output ONLY raw JSON."
        )
    }]

    # The User Message contains the actual payload
    messages = [{
        "role": "user",
        "content": [{
            "text": f"Here is my master JSON resume:\n{master_resume}\n\nHere is the target job description:\n{job_description}"
        }]
    }]

    print(f"Sending request to {model_id}...")
    
    try:
        # Call the Bedrock Converse API
        response = bedrock_runtime.converse(
            modelId=model_id,
            messages=messages,
            system=system_prompt,
            inferenceConfig={
                "temperature": 0.1, # Low temperature ensures it sticks strictly to your facts, no hallucinations
                "maxTokens": 4096
            }
        )
        
        # Extract the raw text from the response payload
        response_text = response['output']['message']['content'][0]['text']
        
        # Parse it back to a Python dictionary to verify it is valid, unbroken JSON
        tailored_resume_dict = json.loads(response_text)
        
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
    # Example execution
    tailor_resume('master_resume.json', 'job_description.txt', 'tailored_resume.json')