# `infra/`

Terraform for this project's AWS side, two independent pieces:

1. The **standalone CI pipeline** (`.github/workflows/generate-resume.yml`)
   — a separate, short-lived OIDC identity only assumable from GitHub
   Actions runners on this repo's `main` branch. Not used by the live pod.
2. **The live backend pod's AWS credentials** (`resume-builder-backend`
   IAM user) — narrowly scoped to exactly two things: `kms:Encrypt`/
   `kms:Decrypt`/`kms:DescribeKey` on the one API-key-encryption key
   (`iam_kms_user.tf`'s `kms_encrypt_decrypt` policy), and
   `bedrock:InvokeModel` on the configured model
   (`iam_kms_user.tf`'s `bedrock_invoke_model` policy, reusing the same
   ARNs `iam.tf` computes for the CI role). If Bedrock calls from the
   live app are falling back to the Anthropic API with
   `AccessDeniedException`, check that this second policy is actually
   applied — it's easy to add Bedrock access to the CI role and forget
   the live pod uses a completely different identity.

| File | Purpose |
|---|---|
| `oidc.tf` | (CI pipeline) The GitHub Actions OIDC identity provider, and an IAM role assumable only via `sts:AssumeRoleWithWebIdentity` from this repo's `main` branch. The trust condition wildcards GitHub's optional `@<id>` suffix on the `sub` claim (anti-repojacking protection for renamed/transferred repos) — an exact match would otherwise reject valid tokens. |
| `iam.tf` | (CI pipeline) The IAM policy: `bedrock:InvokeModel` only, scoped to the exact ARNs needed. A Bedrock cross-region inference profile ID (e.g. `us.anthropic.claude-...`) needs permission on **both** the inference-profile ARN itself *and* the underlying foundation-model ARN in every region the profile can route to — granting only one half causes `AccessDeniedException` at invoke time even though the policy "looks" like it covers the model. |
| `kms.tf` | (live backend) The KMS key that encrypts per-user Anthropic API keys (`backend/auth.py`), plus its `alias/resume-builder-api-keys` alias. Automatic yearly key rotation; a 30-day deletion window so destroying this resource is a "confirm within 30 days" mistake, not instant and irreversible for every stored user's key. |
| `iam_kms_user.tf` | (live backend) A **separate, dedicated** IAM user + long-lived access key for the running pod — deliberately not the OIDC role above, since that's short-lived and only assumable from GitHub Actions, and a persistent pod on a bare k3s cluster has no EKS/IRSA equivalent to use instead. Two policies attached: `kms_encrypt_decrypt` (the API-key encryption key) and `bedrock_invoke_model` (same ARNs as `iam.tf`'s CI policy, via `local.bedrock_model_arns`). |
| `variables.tf` / `terraform.tfvars.example` | AWS account ID, GitHub org/repo/branch, Bedrock model ID and its underlying routing regions. |
| `provider.tf` | Standard AWS provider config. For local testing against LocalStack, run via `tflocal` (transparent endpoint rewriting) instead of `terraform` directly — no LocalStack-specific code needed here. |
| `outputs.tf` | `github_actions_role_arn` — paste into the `AWS_ROLE_ARN` repo secret. `kms_key_id`, `backend_aws_access_key_id`, `backend_aws_secret_access_key` — paste into the backend SealedSecret regeneration command, see `helm/resume-builder/README.md`. |

## Applying

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in your AWS account ID
terraform init
terraform apply
```

Then set the `github_actions_role_arn` output as a repo secret named
`AWS_ROLE_ARN` for `generate-resume.yml` to use.

**No remote state backend is configured** (`versions.tf` has no `backend`
block — state is a local `.tfstate` file, gitignored, never committed).
If you're applying from a machine that's never run `terraform apply` here
before, but the OIDC role/policy already exist in the real AWS account
(applied from elsewhere, or by hand), a plain `terraform apply` will try
to *recreate* `oidc.tf`/`iam.tf`'s resources and fail with "already
exists" errors — not dangerous, just messy. Scope it to just the KMS/IAM
pieces instead:

```bash
terraform apply \
  -target=aws_kms_key.api_key_encryption \
  -target=aws_kms_alias.api_key_encryption \
  -target=aws_iam_user.resume_builder_backend \
  -target=aws_iam_user_policy.kms_encrypt_decrypt \
  -target=aws_iam_access_key.resume_builder_backend
```

Check the plan lists only additions (5 resources, 0 to change/destroy)
before confirming. The clean long-term fix is `terraform import`-ing the
existing OIDC/IAM resources into state so a plain `apply` covers
everything again — not done here, since `-target` was sufficient for a
one-time KMS rollout.

Once the KMS/IAM resources above are already in your local state (as
they will be after the first apply), a plain `terraform apply` is enough
for later additions like `iam_kms_user.tf`'s `bedrock_invoke_model`
policy — Terraform only plans the new resource, no `-target` needed.

## Note on this account's Bedrock access

Bedrock model access needs to be enabled per-model, per-region in the AWS
console — a manual step Terraform doesn't provision. On the account this
was originally built against, the cross-region inference profile hit a
`ThrottlingException: Too many tokens per day` quota; the Anthropic API
fallback exists specifically to keep the pipeline usable regardless.
