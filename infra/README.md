# `infra/`

Terraform for the AWS side of the **standalone CI pipeline**
(`.github/workflows/generate-resume.yml`) — not used by the deployed web
app at all, which has no AWS credentials and always falls back to the
direct Anthropic API (see the root README's
[Bedrock fallback](../README.md#bedrock-fallback-anthropic-api)).

Provisions exactly one thing: a GitHub Actions OIDC trust so that workflow
can call AWS Bedrock without any long-lived AWS credentials stored in
GitHub.

| File | Purpose |
|---|---|
| `oidc.tf` | The GitHub Actions OIDC identity provider, and an IAM role assumable only via `sts:AssumeRoleWithWebIdentity` from this repo's `main` branch. The trust condition wildcards GitHub's optional `@<id>` suffix on the `sub` claim (anti-repojacking protection for renamed/transferred repos) — an exact match would otherwise reject valid tokens. |
| `iam.tf` | The IAM policy: `bedrock:InvokeModel` only, scoped to the exact ARNs needed. A Bedrock cross-region inference profile ID (e.g. `us.anthropic.claude-...`) needs permission on **both** the inference-profile ARN itself *and* the underlying foundation-model ARN in every region the profile can route to — granting only one half causes `AccessDeniedException` at invoke time even though the policy "looks" like it covers the model. |
| `variables.tf` / `terraform.tfvars.example` | AWS account ID, GitHub org/repo/branch, Bedrock model ID and its underlying routing regions. |
| `provider.tf` | Standard AWS provider config. For local testing against LocalStack, run via `tflocal` (transparent endpoint rewriting) instead of `terraform` directly — no LocalStack-specific code needed here. |
| `outputs.tf` | `github_actions_role_arn` — paste into the `AWS_ROLE_ARN` repo secret. |

## Applying

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in your AWS account ID
terraform init
terraform apply
```

Then set the `github_actions_role_arn` output as a repo secret named
`AWS_ROLE_ARN` for `generate-resume.yml` to use.

## Note on this account's Bedrock access

Bedrock model access needs to be enabled per-model, per-region in the AWS
console — a manual step Terraform doesn't provision. On the account this
was originally built against, the cross-region inference profile hit a
`ThrottlingException: Too many tokens per day` quota; the Anthropic API
fallback exists specifically to keep the pipeline usable regardless.
