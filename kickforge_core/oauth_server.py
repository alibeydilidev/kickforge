"""
OAuth authorization-code server.

Runs a short-lived local FastAPI server that walks the user through
Kick's OAuth 2.1 + PKCE flow so KickForge can obtain a user access
token with ``chat:write`` scope.

Usage:
    from kickforge_core.auth import KickAuth
    from kickforge_core.oauth_server import OAuthServer

    auth = KickAuth(client_id="...", client_secret="...")
    server = OAuthServer(auth=auth)
    success = await server.run()  # opens browser, waits for callback
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import webbrowser
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from kickforge_core.auth import KickAuth, generate_pkce_pair

logger = logging.getLogger("kickforge.oauth")

DEFAULT_PORT = 8421
DEFAULT_HOST = "127.0.0.1"
DEFAULT_SCOPES: list[str] = [
    "user:read",
    "channel:read",
    "channel:write",
    "chat:write",
    "events:subscribe",
]

_SUCCESS_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>KickForge — Authorized</title>
<style>
body{font-family:-apple-system,Segoe UI,sans-serif;background:#0e0e10;color:#fff;
  display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{text-align:center;padding:48px 64px;background:#18181b;border-radius:12px;
  box-shadow:0 8px 32px rgba(0,0,0,.4);max-width:440px}
h1{color:#53fc18;margin:0 0 12px;font-size:28px}
p{color:#adadb8;line-height:1.5;margin:8px 0}
.hint{margin-top:24px;padding:12px;background:#26262c;border-radius:6px;
  font-family:monospace;font-size:13px;color:#53fc18}
</style>
</head>
<body>
<div class="card">
<h1>Authorized!</h1>
<p>Your KickForge user token has been saved.</p>
<p>You can close this window and return to your terminal.</p>
<div class="hint">Token saved to ~/.kickforge/tokens.json</div>
</div>
</body>
</html>
"""

_ERROR_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>KickForge — Auth Failed</title>
<style>
body{{font-family:-apple-system,Segoe UI,sans-serif;background:#0e0e10;color:#fff;
  display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;padding:48px 64px;background:#18181b;border-radius:12px;
  box-shadow:0 8px 32px rgba(0,0,0,.4);max-width:500px}}
h1{{color:#ff4444;margin:0 0 12px;font-size:28px}}
p{{color:#adadb8;line-height:1.5;margin:8px 0}}
.err{{margin-top:20px;padding:12px;background:#26262c;border-radius:6px;
  font-family:monospace;font-size:13px;color:#ff8888;text-align:left;
  word-break:break-word}}
</style>
</head>
<body>
<div class="card">
<h1>Authorization Failed</h1>
<p>KickForge could not complete the OAuth flow.</p>
<div class="err">{error}</div>
<p>Check your terminal for details, then try again.</p>
</div>
</body>
</html>
"""


class OAuthServer:
    """
    Local OAuth callback server.

    Call ``run()`` to start the server, open the user's browser to
    ``/auth/login``, and wait for them to come back via the callback.
    Returns True on success (token saved) or False on any failure.
    """

    def __init__(
        self,
        auth: KickAuth,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
        scopes: Optional[list[str]] = None,
        timeout_seconds: float = 300.0,
    ) -> None:
        self.auth = auth
        self.port = port
        self.host = host
        self.scopes = scopes or DEFAULT_SCOPES
        self.timeout_seconds = timeout_seconds
        self.redirect_uri = f"http://{host}:{port}/auth/callback"

        self._state: Optional[str] = None
        self._code_verifier: Optional[str] = None
        self._done_event: Optional[asyncio.Event] = None
        self.error: Optional[str] = None
        self.success: bool = False

        self.app = FastAPI(title="KickForge OAuth", docs_url=None, redoc_url=None)
        self._setup_routes()

    def _setup_routes(self) -> None:
        @self.app.get("/auth/login")
        async def login() -> RedirectResponse:
            self._state = secrets.token_urlsafe(32)
            self._code_verifier, challenge = generate_pkce_pair()
            url = self.auth.get_authorize_url(
                redirect_uri=self.redirect_uri,
                scopes=self.scopes,
                state=self._state,
                code_challenge=challenge,
            )
            logger.info("Redirecting user to Kick authorize URL")
            return RedirectResponse(url)

        @self.app.get("/auth/callback")
        async def callback(request: Request) -> HTMLResponse:
            params = dict(request.query_params)

            if "error" in params:
                msg = f"{params.get('error')}: {params.get('error_description', '')}"
                return self._finish(success=False, error=msg)

            code = params.get("code")
            state = params.get("state")

            if not code:
                return self._finish(success=False, error="No code in callback")

            if state != self._state:
                return self._finish(success=False, error="State mismatch (CSRF protection)")

            try:
                await self.auth.exchange_code(
                    code=code,
                    redirect_uri=self.redirect_uri,
                    code_verifier=self._code_verifier,
                )
            except Exception as exc:
                logger.exception("Code exchange failed")
                return self._finish(success=False, error=f"Code exchange failed: {exc}")

            return self._finish(success=True)

        @self.app.get("/")
        async def root() -> RedirectResponse:
            return RedirectResponse("/auth/login")

    def _finish(self, success: bool, error: Optional[str] = None) -> HTMLResponse:
        """Mark the flow as complete and return the user-facing page."""
        self.success = success
        self.error = error
        if self._done_event:
            self._done_event.set()
        if success:
            return HTMLResponse(_SUCCESS_HTML)
        return HTMLResponse(_ERROR_HTML_TEMPLATE.format(error=error or "unknown"), status_code=400)

    async def run(self, open_browser: bool = True) -> bool:
        """
        Start the server, open the browser to /auth/login, and
        wait for the callback.

        Returns True on success, False on failure or timeout.
        """
        self._done_event = asyncio.Event()

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        # Wait until uvicorn signals it's ready
        for _ in range(50):
            if getattr(server, "started", False):
                break
            await asyncio.sleep(0.1)

        login_url = f"http://{self.host}:{self.port}/auth/login"
        print(f"\nOpening browser to: {login_url}")
        print("If the browser doesn't open, paste that URL manually.\n")
        if open_browser:
            try:
                webbrowser.open(login_url)
            except Exception:
                pass

        try:
            await asyncio.wait_for(self._done_event.wait(), timeout=self.timeout_seconds)
        except asyncio.TimeoutError:
            self.success = False
            self.error = f"OAuth flow timed out after {self.timeout_seconds:.0f}s"

        # Give the browser a moment to receive the success/error HTML
        await asyncio.sleep(0.5)
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except asyncio.TimeoutError:
            server_task.cancel()

        return self.success
