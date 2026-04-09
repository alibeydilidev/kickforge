"""
KickForge — Minimal Bot Example
================================

A complete working bot in ~40 lines using Kick's Pusher WebSocket
for chat.  No ngrok, no webhook, no public URL needed — it connects
directly to Kick's real-time chat stream.

Setup:
    1. pip install kickforge
    2. Copy .env.example to .env and fill in your Kick credentials
    3. Set your channel slug below (or pass via CLI)
    4. python examples/minimal_bot.py

Requirements:
    KICK_CLIENT_ID, KICK_CLIENT_SECRET in .env
    A channel slug (your Kick username)
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

from kickforge_core import KickApp

CHANNEL = os.getenv("KICK_CHANNEL", "yargitay")  # Override with KICK_CHANNEL=yourname

# Default mode is "websocket" — no ngrok needed
app = KickApp()


@app.on("chat.message.sent")
async def handle_chat(event):
    msg = event.message.strip().lower()
    user = event.sender.username
    print(f"[chat] {user}: {event.message}")

    if msg == "!ping":
        await app.say("pong!")

    elif msg == "!dice":
        import random
        roll = random.randint(1, 6)
        await app.say(f"{user} rolled a {roll}!")

    elif msg == "!hug":
        await app.say(f"{user} sends a virtual hug to the chat!")


@app.on("kicks.gifted")
async def handle_gift(event):
    amount = event.kicks_amount
    user = event.gifter_username
    print(f"[gift] {user} sent {amount} kicks")

    if amount >= 100:
        await app.say(f"MASSIVE GIFT from {user} — {amount} kicks! Legend!")
    elif amount >= 10:
        await app.say(f"{user} sent {amount} kicks! Thank you!")
    else:
        await app.say(f"Thanks for the {amount} kicks, {user}!")


@app.on("channel.followed")
async def handle_follow(event):
    print(f"[follow] {event.follower_username}")
    await app.say(f"Welcome aboard, {event.follower_username}!")


if __name__ == "__main__":
    channel = sys.argv[1] if len(sys.argv) > 1 else CHANNEL
    app.run(channel=channel)
