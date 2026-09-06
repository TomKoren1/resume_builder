"""OAuth (Google/GitHub) client setup, session-based auth dependencies,
and per-user Anthropic API key encryption (AWS KMS, with a Fernet
fallback for rows saved before the KMS migration - see decrypt_api_key).

Sessions are a signed httpOnly cookie (Starlette's SessionMiddleware,
wired up in main.py) storing only {"user_id": int} - no server-side
session store, which is fine for a single backend pod. Nothing else
(OAuth tokens, the Anthropic key) ever touches the session or the client.
"""
import boto3
import httpx
from authlib.integrations.starlette_client import OAuth
from botocore.exceptions import ClientError
from cryptography.fernet import Fernet
from fastapi import HTTPException, Request

from . import config, db

oauth = OAuth()

oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_id=config.GOOGLE_CLIENT_ID,
    client_secret=config.GOOGLE_CLIENT_SECRET,
    client_kwargs={"scope": "openid email profile"},
)

oauth.register(
    name="github",
    access_token_url="https://github.com/login/oauth/access_token",
    authorize_url="https://github.com/login/oauth/authorize",
    api_base_url="https://api.github.com/",
    client_id=config.GITHUB_CLIENT_ID,
    client_secret=config.GITHUB_CLIENT_SECRET,
    client_kwargs={"scope": "read:user user:email"},
)


async def fetch_github_userinfo(token):
    """GitHub's OAuth has no standard OIDC userinfo endpoint (unlike
    Google) - fetch the profile and email list separately. Email can
    still come back empty if the user has none verified/public, even
    with the user:email scope - callers must handle that."""
    headers = {"Authorization": f"Bearer {token['access_token']}"}
    async with httpx.AsyncClient() as client:
        profile = (await client.get("https://api.github.com/user", headers=headers)).json()
        emails = (await client.get("https://api.github.com/user/emails", headers=headers)).json()
    primary_email = next((e["email"] for e in emails if e.get("primary")), None) if isinstance(emails, list) else None
    return {
        "subject": str(profile["id"]),
        "email": primary_email,
        "display_name": profile.get("name") or profile.get("login"),
        "avatar_url": profile.get("avatar_url"),
    }


def parse_google_userinfo(userinfo):
    return {
        "subject": userinfo["sub"],
        "email": userinfo.get("email"),
        "display_name": userinfo.get("name"),
        "avatar_url": userinfo.get("picture"),
    }


async def get_current_user(request: Request) -> int:
    """FastAPI dependency: the logged-in user's id, or a 401 if there
    isn't one. Used on every data-touching endpoint except /generate,
    which needs get_current_user_with_key instead."""
    user_id = request.session.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Not logged in.")
    if db.get_user(user_id) is None:
        # Session cookie outlived the account (e.g. manually deleted).
        request.session.clear()
        raise HTTPException(status_code=401, detail="Not logged in.")
    return user_id


async def get_current_user_with_key(request: Request) -> tuple[int, str]:
    """Like get_current_user, but also decrypts the user's stored
    Anthropic key - only /generate needs this, so it's kept separate to
    avoid a wasted decrypt on every other request."""
    user_id = await get_current_user(request)
    encrypted = db.get_user_api_key_encrypted(user_id)
    if encrypted is None:
        raise HTTPException(
            status_code=400,
            detail="No Anthropic API key configured. Add one in Account settings.",
        )
    try:
        return user_id, decrypt_api_key(encrypted, user_id=user_id)
    except ClientError:
        # A real KMS problem (IAM, throttling, an outage) - distinct from
        # "no key configured" above, and from InvalidCiphertextException,
        # which decrypt_api_key already treats as "this is a pre-KMS row"
        # rather than an error.
        raise HTTPException(
            status_code=502,
            detail="Could not access your stored API key right now. Try again shortly.",
        )


_kms_client = boto3.client("kms", region_name=config.BEDROCK_REGION) if config.AWS_KMS_KEY_ID else None
# Fallback-only from here on: decrypts API keys saved before the KMS
# migration, and re-encrypts them via KMS the moment they're next used
# (see decrypt_api_key) so this path naturally stops being exercised as
# users generate resumes. Not used for anything new.
_fernet = Fernet(config.API_KEY_ENCRYPTION_KEY) if config.API_KEY_ENCRYPTION_KEY else None


def encrypt_api_key(plaintext: str) -> bytes:
    if _kms_client is None:
        raise RuntimeError("KMS_KEY_ID is not set.")
    return _kms_client.encrypt(KeyId=config.AWS_KMS_KEY_ID, Plaintext=plaintext.encode("utf-8"))["CiphertextBlob"]


#  A ciphertext that predates the KMS migration isn't valid KMS data at
# all, but which error KMS reports for that depends on whether it can
# even parse the blob as ciphertext: garbage/foreign bytes (e.g. our old
# Fernet tokens) that also fail to match the explicit KeyId passed below
# come back as IncorrectKeyException, not InvalidCiphertextException, per
# real-KMS-compatible testing against LocalStack - both mean "this isn't
# our ciphertext", never an operational problem, so both trigger the
# Fernet fallback. Passing KeyId explicitly (rather than omitting it) is
# still worth keeping - defense-in-depth against ever decrypting
# ciphertext that claims to be for a different key/purpose.
_LEGACY_CIPHERTEXT_ERROR_CODES = {"InvalidCiphertextException", "IncorrectKeyException"}


def decrypt_api_key(ciphertext: bytes, user_id: int | None = None) -> str:
    """KMS first, with a Fernet fallback for rows saved before the KMS
    migration (see _LEGACY_CIPHERTEXT_ERROR_CODES above). Any other
    ClientError (access denied, throttling, KMS down, ...) is a real
    problem and must propagate, never be silently mistaken for an
    old-format row.

    On a successful Fernet fallback, opportunistically re-encrypts this
    one row via KMS and writes it back (needs user_id) - a lazy,
    per-user migration with no separate batch job: each stored key
    upgrades itself the next time it's actually used, which suits this
    app's low, sporadic traffic (rate-limited to 10 generations/hour/user)
    far better than a scripted cutover would.
    """
    if _kms_client is not None:
        try:
            return _kms_client.decrypt(CiphertextBlob=ciphertext, KeyId=config.AWS_KMS_KEY_ID)["Plaintext"].decode("utf-8")
        except ClientError as e:
            if e.response["Error"]["Code"] not in _LEGACY_CIPHERTEXT_ERROR_CODES:
                raise

    if _fernet is None:
        raise RuntimeError("Ciphertext is not valid KMS data and no Fernet fallback key is configured.")
    plaintext = _fernet.decrypt(ciphertext).decode("utf-8")

    if _kms_client is not None and user_id is not None:
        db.set_user_api_key(user_id, encrypt_api_key(plaintext))

    return plaintext


def mask_api_key(plaintext: str) -> str:
    return f"{plaintext[:7]}...{plaintext[-4:]}" if len(plaintext) > 11 else "***"
