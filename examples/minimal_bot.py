"""
KickForge — Minimal Bot Example
================================

A complete working bot in ~40 lines. Shows:
- Chat command handling
- Gift reactions
- Follow welcomes
- Timed messages

Setup:
    1. pip install kickforge
    2. Copy .env.example to .env and fill in your Kick credentials
    3. python examples/minimal_bot.py
    4. In another terminal: ngrok http 8420
    5. Set your ngrok URL as webhook URL in Kick Dev settings
"""

from kickforge_core import KickApp

# Credentials are loaded automatically from .env
# You can also pass them directly: KickApp(client_id="...", client_secret="...")
app = KickApp()


@app.on("chat.message.sent")
async def handle_chat(event):
    msg = event.message.strip().lower()
    user = event.sender.username

    if msg == "!ping":
        await app.say("pong! 🏓")

    elif msg == "!dice":
        import random
        roll = random.randint(1, 6)
        await app.say(f"🎲 {user} rolled a {roll}!")

    elif msg == "!hug":
        await app.say(f"🤗 {user} sends a virtual hug to the chat!")


@app.on("kicks.gifted")
async def handle_gift(event):
    amount = event.kicks_amount
    user = event.gifter_username

    if amount >= 100:
        await app.say(f"🔥🔥🔥 MASSIVE GIFT from {user} — {amount} kicks! You're a legend!")
    elif amount >= 10:
        await app.say(f"🔥 {user} sent {amount} kicks! Thank you!")
    else:
        await app.say(f"💚 Thanks for the {amount} kicks, {user}!")


@app.on("channel.followed")
async def handle_follow(event):
    await app.say(f"Welcome aboard, {event.follower_username}! 🎉")


if __name__ == "__main__":
    app.run(port=8420)
