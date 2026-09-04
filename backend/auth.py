"""OAuth (Google/GitHub) client setup, session-based auth dependencies,
and Fernet encryption for per-user Anthropic API keys.

Sessions are a signed httpOnly cookie (Starlette's SessionMiddleware,
wired up in main.py) storing only {"user_id": int} - no server-side
session store, which is fine for a single backend pod. Nothing else
(OAuth tokens, the Anthropic key) ever touches the session or the client.
"""
import httpx
from authlib.integrations.starlette_client import OAuth
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
    return user_id, decrypt_api_key(encrypted)


_fernet = Fernet(config.API_KEY_ENCRYPTION_KEY) if config.API_KEY_ENCRYPTION_KEY else None


def encrypt_api_key(plaintext: str) -> bytes:
    if _fernet is None:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY is not set.")
    return _fernet.encrypt(plaintext.encode("utf-8"))


def decrypt_api_key(ciphertext: bytes) -> str:
    if _fernet is None:
        raise RuntimeError("API_KEY_ENCRYPTION_KEY is not set.")
    return _fernet.decrypt(ciphertext).decode("utf-8")


def mask_api_key(plaintext: str) -> str:
    return f"{plaintext[:7]}...{plaintext[-4:]}" if len(plaintext) > 11 else "***"
