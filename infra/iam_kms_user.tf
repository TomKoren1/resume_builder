# Long-lived credentials for the *live backend pod* (as opposed to
# iam.tf/oidc.tf, which are short-lived, OIDC-federated credentials only
# usable from GitHub Actions runners). A bare k3s cluster has no
# EKS-style IRSA equivalent, so a persistently-running pod needs a real,
# standing AWS identity - kept as its own dedicated user/policy rather
# than folded into the GitHub Actions role, since the two have
# completely different trust boundaries and shouldn't share permissions.
#
# Deliberately a plain IAM user with an access key, not something like
# IAM Roles Anywhere (certificate-based, no static credentials) - the
# simpler option was chosen to match minimal-added-complexity over a
# marginally stronger credential-lifecycle story; worth revisiting if
# that tradeoff ever matters more than it does for a single homelab pod.
resource "aws_iam_user" "resume_builder_backend" {
  name = "resume-builder-backend"
}

# Least-privilege, same style as iam.tf's bedrock_invoke_model policy:
# exactly the three KMS actions the app calls (backend/auth.py), scoped
# to the one key it's allowed to touch - never kms:* or a wildcard
# resource.
resource "aws_iam_user_policy" "kms_encrypt_decrypt" {
  name = "kms-api-key-encryption-least-privilege"
  user = aws_iam_user.resume_builder_backend.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["kms:Encrypt", "kms:Decrypt", "kms:DescribeKey"]
        Resource = aws_kms_key.api_key_encryption.arn
      }
    ]
  })
}

resource "aws_iam_access_key" "resume_builder_backend" {
  user = aws_iam_user.resume_builder_backend.name
}
