# Fetch the current TLS certificate chain for GitHub's OIDC issuer so the
# thumbprint below is always correct, instead of hardcoding a fingerprint
# that goes stale whenever GitHub rotates certificates.
data "tls_certificate" "github_actions" {
  url = "https://token.actions.githubusercontent.com"
}

# GitHub Actions OIDC identity provider. AWS validates the issuer's TLS
# certificate against its own trusted root CAs and only falls back to
# thumbprint_list if that fails, but the field is still required by this
# resource - see https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles_providers_create_oidc_verify-thumbprint.html
resource "aws_iam_openid_connect_provider" "github_actions" {
  url = "https://token.actions.githubusercontent.com"

  client_id_list = ["sts.amazonaws.com"]

  thumbprint_list = [data.tls_certificate.github_actions.certificates[0].sha1_fingerprint]
}

# Role assumable only by workflow runs on the configured repo/branch, via
# GitHub's OIDC token - no long-lived AWS credentials stored in GitHub.
resource "aws_iam_role" "github_actions_bedrock" {
  name = "github-actions-resume-builder-bedrock"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Federated = aws_iam_openid_connect_provider.github_actions.arn
        }
        Action = "sts:AssumeRoleWithWebIdentity"
        Condition = {
          StringEquals = {
            "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
          }
          StringLike = {
            "token.actions.githubusercontent.com:sub" = "repo:${var.github_org}/${var.github_repo}:ref:refs/heads/${var.github_branch}"
          }
        }
      }
    ]
  })
}
