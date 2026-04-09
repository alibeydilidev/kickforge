# KickForge

**The open-source toolkit for interactive Kick.com streams.**

Build bots, connect games, automate clips, and create real-time overlays — all with Python.

[![PyPI](https://img.shields.io/pypi/v/kickforge)](https://pypi.org/project/kickforge/)
[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://github.com/alibeydilidev/kickforge/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)

---

## What is KickForge?

KickForge is a modular Python toolkit that lets you build interactive experiences on Kick.com. It handles the boring parts (OAuth, WebSockets, webhooks, API calls) so you can focus on the fun parts (making your stream chaotic, engaging, and profitable).

**Zero infrastructure required.** By default, KickForge connects directly to Kick's real-time Pusher WebSocket for chat — no ngrok, no public URL, no webhook server. Just run your bot.

### Packages

| Package | What it does |
|---|---|
| **kickforge-core** | OAuth 2.1 + PKCE, WebSocket chat client, webhook server, event bus, REST API |
| **kickforge-bot** | Chat commands, loyalty/XP, moderation, polls, plugins |
| **kickforge-gsi** | Game integrations — CS2, Minecraft, GTA via RCON/API |
| **kickforge-clip** | Auto-detect hype moments, cut clips, export to Shorts |
| **kickforge-overlay** | Real-time OBS widgets via WebSocket |

---

## Quick Start

Three steps, nothing else.

### 1. Install

```bash
pip install kickforge
```

### 2. Get a user token

Copy `.env.example` to `.env` and add your Kick credentials (get them at [kick.com/settings/developer](https://kick.com/settings/developer)):

```
KICK_CLIENT_ID=your_client_id
KICK_CLIENT_SECRET=your_client_secret
KICK_CHANNEL=yourslug
```

Make sure `http://localhost:8421/auth/callback` is registered under **Redirect URIs** in your Kick Dev App settings.

Then run:

```bash
kickforge auth --channel yourslug
```

Browser opens → click Approve → `~/.kickforge/tokens.json` is saved with your user token AND your channel's `chatroom_id` (auto-resolved). Done.

### 3. Run your bot

```bash
python examples/minimal_bot.py
```

Your bot now **listens** (via Pusher WebSocket) and **writes** (via Kick's chat API). No webhook, no ngrok, no extra config.

---

## 30-Second Bot

```python
from kickforge_core import KickApp

# Credentials loaded from .env automatically
app = KickApp()

@app.on("chat.message.sent")
async def on_chat(event):
    if event.message == "!ping":
        await app.say("pong!")

@app.on("kicks.gifted")
async def on_gift(event):
    await app.say(f"{event.gifter_username} sent {event.kicks_amount} kicks!")

app.run(channel="yourslug")
```

---

## How It Works

KickForge has two independent event paths that flow into the same `EventBus`:

### Reading chat — Pusher WebSocket (default)

Kick's chat runs on top of [Pusher](https://pusher.com/docs/channels/library_auth_reference/pusher-websockets-protocol/). KickForge connects directly to Kick's public Pusher endpoint and subscribes to your chatroom channel (`chatrooms.{id}.v2`). Chat messages, follows, subs, and kicks arrive in real time over a single WebSocket.

- No public URL needed
- No webhook registration
- No ngrok tunnel
- Works behind NAT / firewalls
- Survives reconnects automatically

Events arrive as `ChatMessageEvent`, `FollowEvent`, `GiftEvent`, `SubscriptionEvent` — the same types the webhook path emits, so your handlers don't care which transport was used.

### Writing to chat — OAuth 2.1 + PKCE

Sending chat messages requires a user access token with `chat:write` scope. The built-in `kickforge auth` command walks you through Kick's OAuth 2.1 flow (with PKCE S256 code challenge):

1. Spins up a local server on port 8421
2. Opens your browser to Kick's authorize page
3. Captures the callback, exchanges the code for a token
4. **Auto-resolves your `chatroom_id`** via browser-side JavaScript that bypasses Cloudflare
5. Persists everything to `~/.kickforge/tokens.json` (chmod 600)

Refresh tokens keep the session alive indefinitely — you only run `kickforge auth` once.

### Architecture

```
Kick Pusher WebSocket ─────┐
                            ├──▶ EventBus ──▶ Your @app.on() handlers
Kick Webhook HTTP POST ────┘
                                   │
                                   └──▶ REST API (authenticated) ──▶ Kick.com
```

---

## Supported Events

| Event | When it fires |
|---|---|
| `chat.message.sent` | Someone sends a chat message |
| `channel.followed` | New follower |
| `channel.subscription.new` | New subscriber |
| `channel.subscription.renewal` | Sub renewal |
| `channel.subscription.gifts` | Gift subs |
| `kicks.gifted` | Kicks (coins) gifted |
| `livestream.status.updated` | Stream goes live/offline |
| `moderation.banned` | User banned |

All of these fire identically whether you're in `websocket` mode (default), `webhook` mode, or `hybrid` mode.

---

## Interactive Gaming (CS2 Example)

```python
from kickforge_core import KickApp
from kickforge_gsi import CS2RCONAdapter, TierEngine, KickGameBridge

app = KickApp()
adapter = CS2RCONAdapter(host="192.168.1.10", port=27015, password="...")
engine = TierEngine.from_yaml("tiers.yaml")

bridge = KickGameBridge(
    bus=app.bus,
    adapter=adapter,
    tier_engine=engine,
)
bridge.register()

app.run(channel="yourslug")
```

See [`examples/cs2_interactive.py`](https://github.com/alibeydilidev/kickforge/blob/main/examples/cs2_interactive.py) for a full interactive CS2 setup with tier-based actions, and [`docs/adapters.md`](https://github.com/alibeydilidev/kickforge/blob/main/docs/adapters.md) for writing your own game adapter.

---

## Advanced: Webhook Mode

If you prefer the traditional webhook model (Kick pushes events to a public HTTPS endpoint), KickForge supports it too. Use `mode="webhook"` when you need delivery reliability guarantees or signed events.

```python
app = KickApp(mode="webhook", verify_signatures=True)
app.run(channel="yourslug", port=8420)
```

This requires:

- A public HTTPS URL pointing to your bot (ngrok, Cloudflare Tunnel, or a deployed server)
- The URL registered under Webhook URL in your Kick Dev App
- Event subscriptions via `python examples/subscribe_events.py`

```bash
# Terminal 1: run your bot
python bot.py

# Terminal 2: expose to internet
ngrok http 8420
# copy the HTTPS URL into Kick Dev App → Webhook URL

# Terminal 3: subscribe to events
python examples/subscribe_events.py
```

You can also run both transports at once with `mode="hybrid"`.

---

## Troubleshooting

- **Chat sending returns 401:** Run `kickforge auth --channel yourslug` again. Your Kick Dev App must have `chat:write` scope enabled.
- **chatroom_id not auto-resolved:** The browser-side fetch may have been blocked by CORS on a particular Kick version. Set `KICK_CHATROOM_ID=12345` in `.env` manually — find the value by opening `https://kick.com/api/v2/channels/yourslug` in any browser tab.
- **redirect_uri mismatch during auth:** Make sure the callback URL in your Kick Dev App is exactly `http://localhost:8421/auth/callback` (not `127.0.0.1`, no trailing slash, `http://` not `https://`).

---

## Project Structure

```
kickforge/
├── kickforge_core/     # OAuth, WebSocket, webhooks, events, API
├── kickforge_bot/      # Chat bot framework
├── kickforge_gsi/      # Game integrations (CS2, MC, GTA)
├── kickforge_clip/     # Auto clip pipeline
├── kickforge_overlay/  # OBS widgets
├── examples/           # Working examples
├── tests/              # 293 tests
└── docs/               # Documentation
```

---

## Contributing

KickForge is open source (MIT). Contributions welcome!

- Found a bug? [Open an issue](https://github.com/alibeydilidev/kickforge/issues)
- Got an idea? [Start a discussion](https://github.com/alibeydilidev/kickforge/discussions)
- Want to add a game adapter? See the [adapter guide](https://github.com/alibeydilidev/kickforge/blob/main/docs/adapters.md)

---

## Roadmap

- [x] Core engine (OAuth 2.1 + PKCE, webhooks, events, API)
- [x] Pusher WebSocket chat client (no ngrok needed)
- [x] OAuth user-token flow with auto chatroom_id resolve
- [x] CLI scaffolding (`kickforge init`, `kickforge auth`)
- [x] Bot framework (commands, loyalty, moderation, polls, plugins)
- [x] CS2 GSI adapter (read-only + RCON write)
- [x] Minecraft RCON adapter
- [x] Generic HTTP adapter (FiveM, custom games)
- [x] Auto-clip pipeline (heat detection, FFmpeg, Shorts formatter)
- [x] OBS overlay widgets (6 widgets via WebSocket)
- [x] PyPI release
- [ ] Documentation site

---

## License

MIT — do whatever you want with it. Build something cool.

---

**Built by [Yargitay](https://kick.com/yargitayy)** | [GitHub](https://github.com/alibeydilidev/kickforge) | [PyPI](https://pypi.org/project/kickforge/) — streaming on Kick, building tools for streamers.
