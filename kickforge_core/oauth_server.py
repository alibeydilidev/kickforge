"""
OAuth authorization-code server.

Runs a short-lived local FastAPI server that walks the user through
Kick's OAuth 2.1 + PKCE flow to obtain a user access token with
``chat:write`` scope, and also tries to resolve the chatroom_id
(which Kick's public API doesn't expose) either server-side with
the freshly-minted user token or client-side via a small JavaScript
snippet running in the user's browser tab.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import webbrowser
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from kickforge_core.api import KickAPI
from kickforge_core.auth import KickAuth, generate_pkce_pair

logger = logging.getLogger("kickforge.oauth")

DEFAULT_PORT = 8421
# Use "localhost" (not "127.0.0.1") because Kick does exact string
# matching on redirect_uri between authorize and token exchange,
# and the README/docs tell users to register the localhost form.
DEFAULT_HOST = "localhost"
DEFAULT_SCOPES: list[str] = [
    "user:read",
    "channel:read",
    "channel:write",
    "chat:write",
    "events:subscribe",
]


def _success_page(chatroom_resolved: bool, channel_slug: Optional[str]) -> str:
    """
    Build the browser-facing success page.

    If chatroom_id was already resolved server-side, just show a
    static success page.  Otherwise, embed JavaScript that fetches
    kick.com/api/v2/channels/{slug} from the browser (where Cloudflare
    lets requests through because it has real browser TLS + session),
    extracts the chatroom_id, and POSTs it back to /auth/chatroom.
    """
    static_status_html = (
        '<div class="hint">Token saved to ~/.kickforge/tokens.json</div>'
    )
    if chatroom_resolved or not channel_slug:
        status_block = static_status_html
        js_block = ""
    else:
        status_block = (
            '<div class="hint" id="status">Resolving chatroom_id from your browser...</div>'
        )
        js_block = f"""
<script>
(async () => {{
  const statusEl = document.getElementById('status');
  const setStatus = (text, ok) => {{
    statusEl.textContent = text;
    statusEl.style.color = ok ? '#53fc18' : '#ffdd55';
  }};
  try {{
    const resp = await fetch(
      'https://kick.com/api/v2/channels/{channel_slug}',
      {{credentials: 'omit'}}
    );
    if (!resp.ok) {{
      setStatus('Could not fetch chatroom_id (' + resp.status + '). Set KICK_CHATROOM_ID in .env.', false);
      return;
    }}
    const data = await resp.json();
    const chatroomId = data?.chatroom?.id;
    const broadcasterId = data?.user_id || data?.user?.id;
    if (!chatroomId) {{
      setStatus('No chatroom.id in response. Set KICK_CHATROOM_ID in .env.', false);
      return;
    }}
    await fetch('/auth/chatroom', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        chatroom_id: chatroomId,
        broadcaster_user_id: broadcasterId,
        slug: '{channel_slug}',
      }}),
    }});
    setStatus('chatroom_id ' + chatroomId + ' saved to ~/.kickforge/tokens.json', true);
  }} catch (err) {{
    setStatus('Browser fetch failed: ' + err.message + '. Set KICK_CHATROOM_ID in .env.', false);
  }}
}})();
</script>
"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>KickForge — Authorized</title>
<style>
body{{font-family:-apple-system,Segoe UI,sans-serif;background:#0e0e10;color:#fff;
  display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
.card{{text-align:center;padding:48px 64px;background:#18181b;border-radius:12px;
  box-shadow:0 8px 32px rgba(0,0,0,.4);max-width:520px}}
h1{{color:#53fc18;margin:0 0 12px;font-size:28px}}
p{{color:#adadb8;line-height:1.5;margin:8px 0}}
.hint{{margin-top:24px;padding:12px;background:#26262c;border-radius:6px;
  font-family:monospace;font-size:13px;color:#53fc18;word-break:break-word}}
</style>
</head>
<body>
<div class="card">
<h1>Authorized!</h1>
<p>Your KickForge user token has been saved.</p>
<p>You can close this window and return to your terminal.</p>
{status_block}
</div>
{js_block}
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

    If ``channel_slug`` is provided, the server also tries to resolve
    the chatroom_id for that channel immediately after the token
    exchange, using (a) the newly-minted user token server-side and
    (b) a JavaScript fetch in the browser success page.
    """

    def __init__(
        self,
        auth: KickAuth,
        channel_slug: Optional[str] = None,
        api: Optional[KickAPI] = None,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
        scopes: Optional[list[str]] = None,
        timeout_seconds: float = 300.0,
        chatroom_wait_seconds: float = 10.0,
    ) -> None:
        self.auth = auth
        self.channel_slug = channel_slug
        self.api = api or KickAPI(auth=auth)
        self.port = port
        self.host = host
        self.scopes = scopes or DEFAULT_SCOPES
        self.timeout_seconds = timeout_seconds
        self.chatroom_wait_seconds = chatroom_wait_seconds
        self.redirect_uri = f"http://{host}:{port}/auth/callback"

        self._state: Optional[str] = None
        self._code_verifier: Optional[str] = None
        self._token_done: Optional[asyncio.Event] = None
        self._chatroom_done: Optional[asyncio.Event] = None

        self.error: Optional[str] = None
        self.success: bool = False
        self.chatroom_id: Optional[int] = None
        self.broadcaster_user_id: Optional[int] = None

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
            logger.info(
                "Authorize URL built (redirect_uri=%r)", self.redirect_uri
            )
            return RedirectResponse(url)

        @self.app.get("/auth/callback")
        async def callback(request: Request) -> HTMLResponse:
            params = dict(request.query_params)

            if "error" in params:
                msg = f"{params.get('error')}: {params.get('error_description', '')}"
                return self._finish_token(success=False, error=msg)

            code = params.get("code")
            state = params.get("state")

            if not code:
                return self._finish_token(success=False, error="No code in callback")

            if state != self._state:
                return self._finish_token(
                    success=False, error="State mismatch (CSRF protection)"
                )

            logger.info(
                "Callback received (redirect_uri=%r), exchanging code...",
                self.redirect_uri,
            )
            try:
                await self.auth.exchange_code(
                    code=code,
                    redirect_uri=self.redirect_uri,
                    code_verifier=self._code_verifier,
                )
            except Exception as exc:
                logger.exception("Code exchange failed")
                return self._finish_token(
                    success=False, error=f"Code exchange failed: {exc}"
                )

            # Token is saved — now try to resolve chatroom_id server-side
            # with the fresh user token.
            if self.channel_slug:
                try:
                    cid = await self.api.get_chatroom_id(
                        self.channel_slug, try_user_token=True
                    )
                    if cid:
                        self.chatroom_id = cid
                        self.auth.save_channel_info(
                            chatroom_id=cid, slug=self.channel_slug
                        )
                        logger.info(
                            "Resolved chatroom_id=%d server-side", cid
                        )
                        if self._chatroom_done:
                            self._chatroom_done.set()
                except Exception:
                    logger.exception("Server-side chatroom lookup failed")

            return self._finish_token(success=True)

        @self.app.post("/auth/chatroom")
        async def save_chatroom(request: Request) -> JSONResponse:
            try:
                data = await request.json()
            except Exception:
                return JSONResponse({"error": "invalid json"}, status_code=400)

            cid = data.get("chatroom_id")
            bid = data.get("broadcaster_user_id")
            slug = data.get("slug")

            if not cid:
                return JSONResponse(
                    {"error": "missing chatroom_id"}, status_code=400
                )

            try:
                self.chatroom_id = int(cid)
                self.broadcaster_user_id = int(bid) if bid else None
                self.auth.save_channel_info(
                    chatroom_id=self.chatroom_id,
                    broadcaster_user_id=self.broadcaster_user_id,
                    slug=slug,
                )
            except Exception as exc:
                logger.exception("Failed to save chatroom info")
                return JSONResponse({"error": str(exc)}, status_code=500)

            logger.info(
                "Saved chatroom_id=%d from browser-side lookup", self.chatroom_id
            )
            if self._chatroom_done:
                self._chatroom_done.set()
            return JSONResponse({"ok": True, "chatroom_id": self.chatroom_id})

        @self.app.get("/")
        async def root() -> RedirectResponse:
            return RedirectResponse("/auth/login")

    def _finish_token(
        self, success: bool, error: Optional[str] = None
    ) -> HTMLResponse:
        """Mark the token flow as complete and return the user-facing page."""
        self.success = success
        self.error = error
        if self._token_done:
            self._token_done.set()
        if success:
            return HTMLResponse(
                _success_page(
                    chatroom_resolved=self.chatroom_id is not None,
                    channel_slug=self.channel_slug,
                )
            )
        return HTMLResponse(
            _ERROR_HTML_TEMPLATE.format(error=error or "unknown"),
            status_code=400,
        )

    async def run(self, open_browser: bool = True) -> bool:
        """
        Start the server, open the browser to /auth/login, and wait
        for the callback (and optionally the chatroom POST).

        Returns True on successful token exchange, False on any failure
        or timeout.  chatroom_id may or may not be resolved — check
        ``self.chatroom_id`` after ``run()`` returns.
        """
        self._token_done = asyncio.Event()
        self._chatroom_done = asyncio.Event()

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

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
            await asyncio.wait_for(
                self._token_done.wait(), timeout=self.timeout_seconds
            )
        except asyncio.TimeoutError:
            self.success = False
            self.error = f"OAuth flow timed out after {self.timeout_seconds:.0f}s"

        # If token succeeded and we haven't yet resolved chatroom_id,
        # give the browser a few seconds to POST it back via /auth/chatroom
        if self.success and self.chatroom_id is None and self.channel_slug:
            try:
                await asyncio.wait_for(
                    self._chatroom_done.wait(),
                    timeout=self.chatroom_wait_seconds,
                )
            except asyncio.TimeoutError:
                logger.info(
                    "Browser did not POST chatroom_id within %ss",
                    self.chatroom_wait_seconds,
                )

        # Give the browser a moment to finish rendering the success/error page
        await asyncio.sleep(0.5)
        server.should_exit = True
        try:
            await asyncio.wait_for(server_task, timeout=5.0)
        except asyncio.TimeoutError:
            server_task.cancel()

        return self.success
