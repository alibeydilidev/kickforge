# 🔥 KickForge

**The open-source toolkit for interactive Kick.com streams.**

Build bots, connect games, automate clips, and create real-time overlays — all with Python.

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## What is KickForge?

KickForge is a modular Python toolkit that lets you build interactive experiences on Kick.com. It handles the boring parts (OAuth, webhooks, API calls) so you can focus on the fun parts (making your stream chaotic, engaging, and profitable).

### Packages

| Package | What it does |
|---|---|
| **kickforge-core** | OAuth 2.1, webhook server, event bus, REST API client |
| **kickforge-bot** | Chat commands, loyalty/XP, moderation, polls, plugins |
| **kickforge-gsi** | Game integrations — CS2, Minecraft, GTA via RCON/API |
| **kickforge-clip** | Auto-detect hype moments, cut clips, export to Shorts |
| **kickforge-overlay** | Real-time OBS widgets via WebSocket |

## Quick Start

```bash
# Install
pip install kickforge

# Scaffold a new bot project
kickforge init my-bot
cd my-bot

# Edit config.yaml with your Kick Dev credentials
# Then run it
python bot.py
```

## 30-Second Bot

```python
from kickforge_core import KickApp

app = KickApp(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
)

@app.on("chat.message.sent")
async def on_chat(event):
    if event.message == "!ping":
        await app.say("pong! 🏓")

@app.on("kicks.gifted")
async def on_gift(event):
    await app.say(f"🔥 {event.gifter_username} sent {event.kicks_amount} kicks!")

app.run(port=8420)
```

## Interactive Gaming (CS2 Example)

```python
from kickforge_core import KickApp

app = KickApp(client_id="...", client_secret="...")

@app.on("kicks.gifted")
async def on_gift(event):
    if event.kicks_amount >= 50:
        # Send RCON command to your CS2 server
        execute_rcon("sv_gravity 200")  # Low gravity!
        await app.say(f"🪐 {event.gifter_username} activated LOW GRAVITY!")

app.run()
```

See [`examples/cs2_interactive.py`](https://github.com/alibeydilidev/kickforge/blob/main/examples/cs2_interactive.py) for a full interactive CS2 setup with tier-based actions.

## Architecture

```
Kick.com ──webhook──▶ KickForge Core ──events──▶ Your Code
                           │                        │
                      Event Bus              Game Adapters
                      REST API               OBS Overlays
                      Auth Manager           Clip Pipeline
```

Everything flows through the **Event Bus**. You register handlers with `@app.on("event_type")` and KickForge routes events to your code. No polling, no WebSocket management, no token refresh headaches.

## Supported Kick Events

| Event | Trigger |
|---|---|
| `chat.message.sent` | Someone sends a chat message |
| `channel.followed` | New follower |
| `channel.subscription.new` | New subscriber |
| `channel.subscription.renewal` | Sub renewal |
| `channel.subscription.gifts` | Gift subs |
| `kicks.gifted` | Kicks (coins) gifted |
| `livestream.status.updated` | Stream goes live/offline |
| `moderation.banned` | User banned |

## First Real Test

End-to-end in 5 minutes: wire up KickForge to the real Kick API and see a live event arrive.

**1. Install and configure**

```bash
pip install kickforge
cp .env.example .env
```

Edit `.env` with your Kick Developer credentials (get them at [kick.com/settings/developer](https://kick.com/settings/developer)):

```
KICK_CLIENT_ID=your_client_id_here
KICK_CLIENT_SECRET=your_client_secret_here
KICK_BROADCASTER_ID=your_broadcaster_user_id_here
```

> Your `KICK_BROADCASTER_ID` is the numeric user ID of the channel you want to receive events for. You can find it in your Kick Developer dashboard or by calling `GET /public/v1/channels?slug=your_channel_name`.

**2. Start ngrok first**

```bash
ngrok http 8420
```

Copy the HTTPS forwarding URL (e.g. `https://a1b2c3.ngrok-free.app`).

**3. Set the webhook URL in Kick**

Go to your [Kick Developer App settings](https://kick.com/settings/developer). Paste your ngrok URL **with `/webhook` appended** as the Webhook URL:

```
https://a1b2c3.ngrok-free.app/webhook
```

> This is configured in the Kick dashboard, not in your `.env` file. Kick needs to know where to send events, and this is how you tell it.

**4. Subscribe to events**

```bash
python examples/subscribe_events.py
```

This tells the Kick API which events you want to receive. You should see output like:

```
Subscribing to 5 events for broadcaster 123456...
Done. Your webhook server will now receive these events.
```

**5. Start the bot**

```bash
python examples/minimal_bot.py
```

You should see the KickForge banner and "Waiting for Kick events...".

**6. Send a test message**

Open your Kick channel in a browser and type `!ping` in chat. Back in your bot terminal you should see:

```
Received webhook: type=chat.message.sent subscription=...
Executed command: !ping by your_username
```

The bot replies "pong!" in chat. You're live.

---

## Setup Webhook (Development)

KickForge needs a public URL for Kick to send webhooks to. During development:

```bash
# Terminal 1: Run your bot
python bot.py

# Terminal 2: Expose to internet
ngrok http 8420

# Copy the ngrok URL (e.g. https://abc123.ngrok.io)
# Set it in Kick Dev settings: https://kick.com/settings/developer
# Webhook URL: https://abc123.ngrok.io/webhook
```

## Project Structure

```
kickforge/
├── kickforge_core/     # OAuth, webhooks, events, API
├── kickforge_bot/      # Chat bot framework
├── kickforge_gsi/      # Game integrations (CS2, MC, GTA)
├── kickforge_clip/     # Auto clip pipeline
├── kickforge_overlay/  # OBS widgets
├── examples/           # Working examples
├── tests/              # Test suite
└── docs/               # Documentation
```

## Contributing

KickForge is open source (MIT). Contributions welcome!

- 🐛 Found a bug? [Open an issue](https://github.com/alibeydilidev/kickforge/issues)
- 💡 Got an idea? [Start a discussion](https://github.com/alibeydilidev/kickforge/discussions)
- 🔧 Want to add a game adapter? See the [adapter guide](https://github.com/alibeydilidev/kickforge/blob/main/docs/adapters.md)

## Roadmap

- [x] Core engine (OAuth, webhooks, events, API)
- [x] CLI scaffolding (`kickforge init`)
- [x] Bot framework (commands, loyalty, moderation, polls, plugins)
- [x] CS2 GSI adapter (read-only + RCON write)
- [x] Minecraft RCON adapter
- [x] Generic HTTP adapter (FiveM, custom games)
- [x] Auto-clip pipeline (heat detection, FFmpeg, Shorts formatter)
- [x] OBS overlay widgets (6 widgets via WebSocket)
- [ ] Documentation site

## License

MIT — do whatever you want with it. Build something cool.

---

**Built by [Yargitay](https://kick.com/yargitay)** | [GitHub](https://github.com/alibeydilidev/kickforge) — streaming on Kick, building tools for streamers.
