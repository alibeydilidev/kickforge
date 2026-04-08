"""
KickForge — Event Subscription Helper
======================================

One-shot script that subscribes to Kick webhook events and
lists the active subscriptions.  Run this once after setting
up your Kick Developer App credentials.

Setup:
    1. Copy .env.example to .env and fill in your credentials
    2. python examples/subscribe_events.py
"""

from __future__ import annotations

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()


EVENTS = [
    "chat.message.sent",
    "channel.followed",
    "kicks.gifted",
    "channel.subscription.new",
    "livestream.status.updated",
]


async def main() -> None:
    client_id = os.getenv("KICK_CLIENT_ID", "")
    client_secret = os.getenv("KICK_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("Error: KICK_CLIENT_ID and KICK_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    from kickforge_core.auth import KickAuth
    from kickforge_core.api import KickAPI

    auth = KickAuth(client_id=client_id, client_secret=client_secret)
    api = KickAPI(auth=auth)

    try:
        # Subscribe
        print(f"Subscribing to {len(EVENTS)} events...")
        result = await api.subscribe_events(EVENTS)
        print("Subscription response:", result)
        print()

        # List active subscriptions
        print("Active subscriptions:")
        subs = await api.get_subscriptions()
        entries = subs.get("data", subs)
        if isinstance(entries, list):
            for entry in entries:
                name = entry.get("name", entry.get("event", "?"))
                status = entry.get("status", "")
                print(f"  - {name}  {status}")
        else:
            print(f"  {subs}")

        print()
        print("Done. Your webhook server will now receive these events.")

    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
