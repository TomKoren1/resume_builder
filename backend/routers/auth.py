from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .. import db
from ..auth import (
    decrypt_api_key,
    encrypt_api_key,
    fetch_github_userinfo,
    get_current_user,
    mask_api_key,
    oauth,
    parse_google_userinfo,
)
from ..observability import logger

router = APIRouter(prefix="/auth")


def _redirect_uri(request: Request, provider: str) -> str:
    # Derived from whatever host the request actually arrived on (rather
    # than a fixed config value), so both the private Tailscale hostname
    # and the public domain work simultaneously with no per-environment
    # config. Each OAuth provider's app config still needs every
    # hostname's callback URL allowlisted on its side - see
    # helm/resume-builder/README.md for the exact URIs to register.
    #
    # Deliberately NOT request.base_url here: that reflects the scheme
    # the ASGI server itself sees, which is plain HTTP even for the
    # public domain - Cloudflare terminates TLS at its edge, and the
    # tunnel -> Traefik -> backend hops are plain HTTP by design.
    # Correctly recovering "https" would mean trusting X-Forwarded-Proto
    # through two proxy hops (cloudflared, then Traefik) - fragile to
    # get right and silently wrong if either hop's trusted-proxy config
    # ever changes. The Host header has no such ambiguity (both hostnames
    # already depend on it being correct - that's how the Ingress routes
    # at all), so scheme is inferred from which host this is instead.
    scheme = "http" if request.url.hostname.endswith(".local") else "https"
    return f"{scheme}://{request.url.hostname}/auth/callback/{provider}"


@router.get("/login/{provider}")
async def login(request: Request, provider: str):
    if provider not in ("google", "github"):
        raise HTTPException(status_code=404, detail="Unknown provider.")
    client = oauth.create_client(provider)
    return await client.authorize_redirect(request, _redirect_uri(request, provider))


@router.get("/callback/{provider}")
async def callback(request: Request, provider: str):
    if provider not in ("google", "github"):
        raise HTTPException(status_code=404, detail="Unknown provider.")
    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)

    if provider == "google":
        userinfo = parse_google_userinfo(token["userinfo"])
    else:
        userinfo = await fetch_github_userinfo(token)

    user_id = db.upsert_user(
        provider, userinfo["subject"], userinfo["email"], userinfo["display_name"], userinfo["avatar_url"]
    )
    request.session["user_id"] = user_id
    logger.info(f"User {user_id} logged in via {provider}.")
    return RedirectResponse(url="/")


@router.post("/logout")
async def logout(request: Request):
    request.session.clear()
    return {"message": "Logged out."}


@router.get("/me")
async def me(user_id: int = Depends(get_current_user)):
    user = db.get_user(user_id)
    return {
        "id": user["id"],
        "email": user["email"],
        "display_name": user["display_name"],
        "avatar_url": user["avatar_url"],
        "has_api_key": user["anthropic_api_key_encrypted"] is not None,
    }


class ApiKeyRequest(BaseModel):
    anthropic_api_key: str


@router.put("/api-key")
async def save_api_key(body: ApiKeyRequest, user_id: int = Depends(get_current_user)):
    key = body.anthropic_api_key.strip()
    if not key:
        raise HTTPException(status_code=400, detail="API key cannot be empty.")
    db.set_user_api_key(user_id, encrypt_api_key(key))
    return {"message": "Saved.", "masked": mask_api_key(key)}


@router.delete("/api-key")
async def delete_api_key(user_id: int = Depends(get_current_user)):
    db.clear_user_api_key(user_id)
    return {"message": "Removed."}
