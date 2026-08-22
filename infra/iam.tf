locals {
  # bedrock_model_id (e.g. "us.anthropic.claude-3-5-sonnet-20241022-v2:0") is a
  # cross-region inference profile, not a plain foundation-model ID. Bedrock
  # requires the caller to have bedrock:InvokeModel on BOTH:
  #   1. the inference-profile ARN itself (account-scoped, in aws_region), and
  #   2. the underlying foundation-model ARN in every region the profile may
  #      route to (account-less, one per region in bedrock_underlying_regions).
  # Omitting either half causes AccessDeniedException at invoke time even
  # though the policy "looks" like it grants the model.
  inference_profile_arn = "arn:aws:bedrock:${var.aws_region}:${var.aws_account_id}:inference-profile/${var.bedrock_model_id}"

  # Strip the "us." cross-region prefix to get the bare foundation-model ID.
  foundation_model_id = replace(var.bedrock_model_id, "/^[a-z]+\\./", "")

  foundation_model_arns = [
    for region in var.bedrock_underlying_regions :
    "arn:aws:bedrock:${region}::foundation-model/${local.foundation_model_id}"
  ]

  bedrock_model_arns = concat([local.inference_profile_arn], local.foundation_model_arns)
}

resource "aws_iam_role_policy" "bedrock_invoke_model" {
  name = "bedrock-invoke-model-least-privilege"
  role = aws_iam_role.github_actions_bedrock.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.bedrock_model_arns
      }
    ]
  })
}
