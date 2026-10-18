"""Startup checks and HTTP hardening.

- Refuse to start in production with a placeholder or short secret key, or a weak admin password.
- Security headers on every API response; personal data is never cached.
- Request bodies above JOBPILOT_MAX_REQUEST_BYTES are refused before parsing.
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from jobpilot.config import Settings

log = logging.getLogger("jobpilot.security")

PLACEHOLDER_SECRETS = {"change-me-in-production", "replace-with-a-long-random-string", "dev-secret-key-0123456789",
                       "test-secret-key-0123456789"}
MIN_PASSWORD = 12


class InsecureConfig(RuntimeError):
    pass


def check_settings(s: Settings) -> list[str]:
    """Returns warnings; raises InsecureConfig for problems that must stop a production start."""
    problems, warnings = [], []
    if s.secret_key in PLACEHOLDER_SECRETS or len(s.secret_key) < 32:
        problems.append("JOBPILOT_SECRET_KEY is a placeholder or shorter than 32 characters "
                        "(generate one: python -c \"import secrets;print(secrets.token_hex(32))\")")
    if s.admin_password and len(s.admin_password) < MIN_PASSWORD:
        problems.append(f"JOBPILOT_ADMIN_PASSWORD must be at least {MIN_PASSWORD} characters")
    if not s.cookie_secure:
        warnings.append("JOBPILOT_COOKIE_SECURE is false: fine on localhost, but set it to true behind HTTPS")
    if s.env == "production" and problems:
        raise InsecureConfig("Refusing to start: " + "; ".join(problems))
    for w in problems + warnings:
        log.warning("security: %s", w)
    return problems + warnings


API_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class HardeningMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next):
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > self.max_bytes:
            return JSONResponse({"error": {"code": "payload_too_large", "message": "Request body is too large",
                                           "details": {"max_bytes": self.max_bytes}}}, status_code=413)
        response = await call_next(request)
        for k, v in API_HEADERS.items():
            response.headers.setdefault(k, v)
        if not request.url.path.startswith(DOCS_PATHS):
            # JSON and files here are personal data: never cache, never render as a page
            response.headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            response.headers.setdefault("Cache-Control", "no-store")
        return response
