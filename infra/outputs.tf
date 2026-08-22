output "github_actions_role_arn" {
  description = "Paste into the aws-actions/configure-aws-credentials 'role-to-assume' input in the Phase 3 GitHub Actions workflow."
  value       = aws_iam_role.github_actions_bedrock.arn
}

output "bedrock_model_arns" {
  description = "The full set of ARNs the IAM policy grants bedrock:InvokeModel on (inference profile + underlying per-region foundation models)."
  value       = local.bedrock_model_arns
}
