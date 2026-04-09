"""
KickForge — Debug Webhook Receiver
===================================

A completely minimal FastAPI server that accepts ANY POST to /webhook
and prints the full request (headers + body).  No signature verification,
no parsing, no rejection — every request gets a 200 response and is
logged in full.

Use this to verify that Kick (or ngrok) is actually reaching your
machine before debugging the main KickForge webhook pipeline.

Usage:
    python examples/debug_webhook.py
    # then: ngrok http 8420
    # then: set ngrok URL in Kick Dev App → Webhook URL

Endpoints:
    POST /webhook  — logs everything, returns 200
    GET  /health   — returns {"status": "ok"}
    GET  /         — returns a landing message (helpful for verifying ngrok)
"""

from __future__ import annotations

import json
import sys
from datetime import datetime

from fastapi import FastAPI, Request, Response
import uvicorn


app = FastAPI(title="KickForge Debug Receiver")


def _log(msg: str) -> None:
    """Print with timestamp and flush immediately."""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


@app.post("/webhook")
async def webhook(request: Request) -> Response:
    body = await request.body()

    _log("=" * 70)
    _log(f"POST /webhook from {request.client.host if request.client else 'unknown'}")
    _log("-" * 70)
    _log("Headers:")
    for name, value in request.headers.items():
        _log(f"  {name}: {value}")
    _log("-" * 70)
    _log(f"Body ({len(body)} bytes):")
    # Try to pretty-print JSON; fall back to raw
    if body:
        try:
            parsed = json.loads(body)
            _log(json.dumps(parsed, indent=2, ensure_ascii=False))
        except json.JSONDecodeError:
            _log(body.decode("utf-8", errors="replace"))
    else:
        _log("  (empty body)")
    _log("=" * 70)

    return Response(status_code=200)


@app.get("/health")
async def health() -> dict[str, str]:
    _log("GET /health")
    return {"status": "ok", "service": "kickforge-debug"}


@app.get("/")
async def root() -> dict[str, str]:
    _log("GET /")
    return {
        "service": "kickforge-debug",
        "message": "Send webhooks to POST /webhook",
    }


@app.middleware("http")
async def log_every_request(request: Request, call_next):
    """Log every incoming request, even ones that don't hit a route."""
    _log(f">> {request.method} {request.url.path} from {request.client.host if request.client else '?'}")
    response = await call_next(request)
    _log(f"<< {response.status_code} {request.method} {request.url.path}")
    return response


if __name__ == "__main__":
    print("=" * 70)
    print("KickForge Debug Webhook Receiver")
    print("=" * 70)
    print("Listening on http://0.0.0.0:8420")
    print()
    print("Endpoints:")
    print("  POST /webhook  — accepts everything, logs headers + body")
    print("  GET  /health   — health check")
    print("  GET  /         — landing page")
    print()
    print("Next steps:")
    print("  1. In another terminal: ngrok http 8420")
    print("  2. Copy the HTTPS forwarding URL")
    print("  3. In Kick Dev App settings, set Webhook URL to:")
    print("     https://YOUR-NGROK.ngrok-free.app/webhook")
    print("  4. Trigger an event (send a chat message in your channel)")
    print("  5. Watch this terminal for incoming requests")
    print("=" * 70)
    print(flush=True)

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8420,
        log_level="info",
        access_log=True,
    )
