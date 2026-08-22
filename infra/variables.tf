variable "aws_region" {
  description = "AWS region to deploy the IAM/OIDC resources into (Bedrock is invoked cross-region regardless, see local.bedrock_model_arns)."
  type        = string
  default     = "us-east-1"
}

variable "aws_account_id" {
  description = "AWS account ID that owns the IAM role/policy. Required to build the Bedrock inference-profile ARN."
  type        = string
}

variable "github_org" {
  description = "GitHub organization or username that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without the org/user prefix)."
  type        = string
}

variable "github_branch" {
  description = "Git branch the OIDC trust policy restricts assumption to. Use \"*\" to allow any branch."
  type        = string
  default     = "main"
}

variable "bedrock_model_id" {
  description = "Bedrock cross-region inference profile ID invoked by backend/main.py."
  type        = string
  default     = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

variable "bedrock_underlying_regions" {
  description = "AWS regions the bedrock_model_id's cross-region inference profile can route requests to. Required because bedrock:InvokeModel needs permission on both the inference-profile ARN and every underlying foundation-model ARN it may dispatch to."
  type        = list(string)
  default     = ["us-east-1", "us-east-2", "us-west-2"]
}
