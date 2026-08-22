# Standard AWS provider block. When testing locally, run Terraform via
# `tflocal` (https://github.com/localstack/terraform-local) instead of
# `terraform` directly - tflocal transparently rewrites this provider's
# endpoints to point at LocalStack, so no localstack-specific config is
# needed here.
provider "aws" {
  region = var.aws_region
}
