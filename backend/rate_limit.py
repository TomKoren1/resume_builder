"""Shared slowapi Limiter instance - lives in its own module (not
main.py) so routers can import it for the @limiter.limit(...) decorator
without a circular import (main.py imports the routers; a router
importing limiter back from main.py would be circular)."""
from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def _rate_limit_key(request: Request) -> str:
    # Per logged-in user once auth exists (the normal case for every
    # endpoint this is applied to) - falls back to IP only for the
    # theoretical unauthenticated case, which Depends(get_current_user...)
    # already rejects with a 401 before a rate-limited handler ever runs.
    user_id = request.session.get("user_id")
    return f"user:{user_id}" if user_id else get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key)
