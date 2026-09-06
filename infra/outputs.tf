output "github_actions_role_arn" {
  description = "Paste into the aws-actions/configure-aws-credentials 'role-to-assume' input in the Phase 3 GitHub Actions workflow."
  value       = aws_iam_role.github_actions_bedrock.arn
}

output "bedrock_model_arns" {
  description = "The full set of ARNs the IAM policy grants bedrock:InvokeModel on (inference profile + underlying per-region foundation models)."
  value       = local.bedrock_model_arns
}

output "kms_key_id" {
  description = "Paste into the SealedSecret regeneration command as KMS_KEY_ID (see helm/resume-builder/README.md)."
  value       = aws_kms_alias.api_key_encryption.name
}

output "backend_aws_access_key_id" {
  description = "Paste into the SealedSecret regeneration command as AWS_ACCESS_KEY_ID."
  value       = aws_iam_access_key.resume_builder_backend.id
}

output "backend_aws_secret_access_key" {
  description = "Paste into the SealedSecret regeneration command as AWS_SECRET_ACCESS_KEY. Only ever printed once here (terraform apply / terraform output on demand) - Terraform state itself is the durable copy, so treat that state file with the same care as any other secret store."
  value       = aws_iam_access_key.resume_builder_backend.secret
  sensitive   = true
}
