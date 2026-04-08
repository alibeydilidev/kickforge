"""
KickForge — Event Subscription Helper
======================================

One-shot script that subscribes to Kick webhook events and
lists the active subscriptions.  Run this once after setting
up your Kick Developer App credentials.

Usage:
    python examples/subscribe_events.py            # subscribe to events
    python examples/subscribe_events.py --reset    # clear all, then re-subscribe

Setup:
    1. Copy .env.example to .env and fill in your credentials
    2. python examples/subscribe_events.py
"""

from __future__ import annotations

import argparse
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
    parser = argparse.ArgumentParser(description="Subscribe to Kick webhook events")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete all existing subscriptions before re-subscribing",
    )
    args = parser.parse_args()

    client_id = os.getenv("KICK_CLIENT_ID", "")
    client_secret = os.getenv("KICK_CLIENT_SECRET", "")
    broadcaster_id_str = os.getenv("KICK_BROADCASTER_ID", "")

    if not client_id or not client_secret:
        print("Error: KICK_CLIENT_ID and KICK_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    if not broadcaster_id_str:
        print("Error: KICK_BROADCASTER_ID must be set in .env")
        print("  Find it via: GET https://api.kick.com/public/v1/channels?slug=YOUR_CHANNEL")
        sys.exit(1)

    try:
        broadcaster_id = int(broadcaster_id_str)
    except ValueError:
        print(f"Error: KICK_BROADCASTER_ID must be an integer, got '{broadcaster_id_str}'")
        sys.exit(1)

    from kickforge_core.auth import KickAuth
    from kickforge_core.api import KickAPI

    auth = KickAuth(client_id=client_id, client_secret=client_secret)
    api = KickAPI(auth=auth)

    try:
        # Reset: delete all existing subscriptions first
        if args.reset:
            print("Fetching existing subscriptions...")
            subs = await api.get_subscriptions()
            entries = subs.get("data", [])
            if isinstance(entries, list) and entries:
                ids = [e["id"] for e in entries if "id" in e]
                if ids:
                    print(f"Deleting {len(ids)} existing subscription(s)...")
                    await api.delete_subscriptions(ids)
                    print("Deleted.")
                else:
                    print("No subscription IDs found to delete.")
            else:
                print("No existing subscriptions.")
            print()

        # Subscribe
        print(f"Subscribing to {len(EVENTS)} events for broadcaster {broadcaster_id}...")
        result = await api.subscribe_events(EVENTS, broadcaster_user_id=broadcaster_id)
        print("Subscription response:", result)
        print()

        # List active subscriptions
        print("Active subscriptions:")
        subs = await api.get_subscriptions()
        entries = subs.get("data", subs)
        if isinstance(entries, list):
            for entry in entries:
                name = entry.get("name", entry.get("event", "?"))
                sub_id = entry.get("id", "")
                print(f"  - {name}  (id={sub_id})")
        else:
            print(f"  {subs}")

        print()
        print("Done. Your webhook server will now receive these events.")

    finally:
        await api.close()


if __name__ == "__main__":
    asyncio.run(main())
