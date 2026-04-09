"""
KickForge — Local Webhook Test
===============================

Sends a fake Kick webhook POST to http://localhost:8420/webhook
and prints the response.  Use this to verify that your local
webhook server is actually running and reachable on port 8420
BEFORE debugging ngrok or Kick's end.

Usage:
    # Terminal 1: start a webhook server
    python examples/debug_webhook.py

    # Terminal 2: send a fake event
    python examples/test_webhook_local.py
    python examples/test_webhook_local.py --url http://localhost:8420/webhook
    python examples/test_webhook_local.py --event chat.message.sent
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx


SAMPLE_PAYLOADS = {
    "chat.message.sent": {
        "message_id": "test-msg-001",
        "content": "!ping from test_webhook_local.py",
        "broadcaster_user_id": 123456,
        "sender": {
            "user_id": 99999,
            "username": "local_test_user",
            "is_subscriber": False,
            "badges": [],
        },
    },
    "channel.followed": {
        "username": "local_test_follower",
        "user_id": 88888,
        "broadcaster_user_id": 123456,
    },
    "kicks.gifted": {
        "gifter": {"username": "local_test_gifter", "user_id": 77777},
        "amount": 50,
        "broadcaster_user_id": 123456,
    },
}


async def main() -> None:
    parser = argparse.ArgumentParser(description="Send a fake Kick webhook to a local server")
    parser.add_argument("--url", default="http://localhost:8420/webhook", help="Webhook URL")
    parser.add_argument(
        "--event",
        default="chat.message.sent",
        choices=list(SAMPLE_PAYLOADS.keys()),
        help="Event type to send",
    )
    parser.add_argument(
        "--health",
        action="store_true",
        help="Also hit GET /health first",
    )
    args = parser.parse_args()

    payload = SAMPLE_PAYLOADS[args.event]
    body = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Kick-Event-Type": args.event,
        "Kick-Event-Message-Id": "test-msg-local-001",
        "Kick-Event-Message-Timestamp": "1234567890",
        "Kick-Event-Signature": "dGVzdA==",  # base64("test") — will fail verification
        "Kick-Event-Subscription-Id": "test-sub-local",
        "User-Agent": "KickForge-LocalTest/1.0",
    }

    print(f"Target: {args.url}")
    print(f"Event: {args.event}")
    print()

    async with httpx.AsyncClient(timeout=10.0) as client:
        if args.health:
            try:
                health_url = args.url.rsplit("/", 1)[0] + "/health"
                print(f"GET  {health_url}")
                resp = await client.get(health_url)
                print(f"  -> {resp.status_code} {resp.text}")
                print()
            except Exception as exc:
                print(f"  -> ERROR: {exc}")
                print()

        print(f"POST {args.url}")
        print(f"  Headers: {json.dumps({k: v for k, v in headers.items()}, indent=4)}")
        print(f"  Body:    {json.dumps(payload, indent=4)}")
        print()

        try:
            resp = await client.post(args.url, content=body, headers=headers)
        except httpx.ConnectError as exc:
            print(f"CONNECTION FAILED: {exc}")
            print()
            print("Is your webhook server running on port 8420?")
            print("Try:  python examples/debug_webhook.py")
            sys.exit(1)
        except Exception as exc:
            print(f"REQUEST FAILED: {exc}")
            sys.exit(1)

        print(f"Response: {resp.status_code}")
        print(f"Headers:  {dict(resp.headers)}")
        if resp.text:
            print(f"Body:     {resp.text}")
        print()

        if resp.status_code == 200:
            print("SUCCESS — server accepted the webhook.")
        elif resp.status_code == 403:
            print("403 FORBIDDEN — signature verification rejected the request.")
            print("  If you're using the KickForge WebhookServer, set verify_signatures=False")
            print("  for this local test, or use debug_webhook.py instead.")
        elif resp.status_code == 400:
            print("400 BAD REQUEST — server couldn't parse the body.")
        else:
            print(f"Unexpected status {resp.status_code}")


if __name__ == "__main__":
    asyncio.run(main())
