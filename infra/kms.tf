# Encrypts each user's stored Anthropic API key (backend/auth.py). Moved
# off a static local Fernet key after a security review found this
# cluster doesn't encrypt Kubernetes Secrets at rest (no k3s
# --secrets-encryption) and PVCs use the unencrypted local-path storage
# class - node/datastore disk access alone was enough to read both the
# key and the ciphertext. A KMS-backed key means decrypting requires a
# live, logged, revocable API call instead of a value that, once read
# once, is a permanent silent compromise.
resource "aws_kms_key" "api_key_encryption" {
  description = "Encrypts per-user Anthropic API keys for the resume-builder web app (backend/auth.py)."
  # Automatic yearly rotation of the underlying key material, same Key
  # ID/ARN throughout - transparent to the app, no code changes needed
  # when it rotates.
  enable_key_rotation = true
  # Max allowed - if this resource is ever destroyed, every stored user's
  # key becomes permanently undecryptable the moment deletion completes.
  # The window makes that a "confirm within 30 days" mistake instead of
  # an instant, irreversible one.
  deletion_window_in_days = 30
}

# The app references this alias (KMS_KEY_ID), never the raw key ARN -
# lets the underlying key be swapped/recreated without an app config
# change.
resource "aws_kms_alias" "api_key_encryption" {
  name          = "alias/resume-builder-api-keys"
  target_key_id = aws_kms_key.api_key_encryption.key_id
}
