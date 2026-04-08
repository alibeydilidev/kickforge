# KickForge — Claude Code Technical Brief

## Project Overview

KickForge is an open-source Python toolkit for building interactive Kick.com streaming experiences. It's a monorepo with 5 packages that share a common core engine. This document is the complete specification for building Tier 1 (the open-source foundation).

**GitHub repo:** `github.com/alibeydilidev/kickforge`
**License:** MIT
**Python:** 3.11+
**Package manager:** pip (PyPI publish target)

---

## Architecture

```
kickforge/                          # Monorepo root
├── pyproject.toml                  # Single installable: pip install kickforge
├── README.md
├── LICENSE (MIT)
├── .gitignore
│
├── kickforge_core/                 # PACKAGE 1: Core engine
│   ├── __init__.py                 # Exports: KickApp, KickAuth, Event, EventBus, KickAPI, WebhookServer
│   ├── auth.py                     # OAuth 2.1 (client creds + auth code + refresh + caching)
│   ├── events.py                   # Typed event models + pub/sub EventBus
│   ├── webhook.py                  # FastAPI webhook server + signature verification
│   ├── api.py                      # Kick REST API wrapper (chat, mod, subs, leaderboard)
│   ├── app.py                      # KickApp orchestrator — ties everything together
│   └── cli.py                      # CLI: kickforge init / run / check
│
├── kickforge_bot/                  # PACKAGE 2: Bot framework
│   ├── __init__.py
│   ├── bot.py                      # Main bot class, extends KickApp
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── handler.py              # @bot.command("!ping") decorator, arg parse, cooldown, permissions
│   │   └── builtin.py              # Built-in commands: !help, !uptime, !followage
│   ├── loyalty.py                  # XP/level system (SQLite backend)
│   ├── moderation.py               # Auto-mod: blacklist, caps, spam, links
│   ├── timers.py                   # Timed recurring messages
│   ├── polls.py                    # !poll and !giveaway
│   └── plugins/
│       ├── __init__.py
│       └── base.py                 # Plugin interface (on_message, on_follow, on_sub, on_gift hooks)
│
├── kickforge_gsi/                  # PACKAGE 3: Game integrations
│   ├── __init__.py
│   ├── bridge.py                   # KickGameBridge — routes Kick events to game actions
│   ├── tiers.py                    # YAML-driven tier engine (gift amount → action mapping)
│   ├── cooldown.py                 # Per-action and per-user cooldown manager
│   ├── adapters/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract GameAdapter interface
│   │   ├── minecraft.py            # Minecraft RCON adapter (mcrcon)
│   │   ├── cs2_gsi.py              # CS2 Game State Integration reader (read-only)
│   │   ├── cs2_rcon.py             # CS2 RCON adapter (Source RCON protocol)
│   │   └── generic_http.py         # Generic HTTP adapter (FiveM, custom games)
│   └── config/
│       └── example_tiers.yaml      # Example tier config file
│
├── kickforge_clip/                 # PACKAGE 4: Clip automation
│   ├── __init__.py
│   ├── detector.py                 # Heat moment detection (chat velocity spike)
│   ├── clipper.py                  # FFmpeg-based clip extraction
│   ├── formatter.py                # 16:9 → 9:16 crop + subtitle overlay
│   ├── exporter.py                 # Batch export + Discord webhook notification
│   └── cli.py                      # kickforge-clip CLI: watch / export / format
│
├── kickforge_overlay/              # PACKAGE 5: OBS widgets
│   ├── __init__.py
│   ├── server/
│   │   ├── __init__.py
│   │   └── ws_server.py            # WebSocket server pushing real-time data to widgets
│   └── widgets/
│       ├── velocity.html           # Chat velocity meter
│       ├── hype_bar.html           # Event-driven hype bar
│       ├── event_feed.html         # Scrolling event feed
│       ├── leaderboard.html        # Top gifters/XP leaderboard
│       ├── prediction.html         # Round prediction overlay
│       └── chaos_meter.html        # Gift-driven chaos progress bar
│
├── examples/
│   ├── minimal_bot.py              # 40-line working bot
│   ├── cs2_interactive.py          # CS2 Chaos Arena (full interactive)
│   ├── minecraft_chaos.py          # Minecraft gift → mob spawn
│   └── loyalty_bot.py              # Bot with XP system + leaderboard
│
├── tests/
│   ├── test_auth.py
│   ├── test_events.py
│   ├── test_webhook.py
│   ├── test_api.py
│   ├── test_bot_commands.py
│   ├── test_tiers.py
│   └── test_clip_detector.py
│
└── docs/
    ├── quickstart.md
    ├── core-concepts.md
    ├── bot-guide.md
    ├── game-integration.md
    ├── overlay-guide.md
    └── adapters.md
```

---

## Kick API Reference

**Base URL:** `https://api.kick.com`
**Auth:** OAuth 2.1 — token endpoint at `https://id.kick.com/oauth/token`
**Docs:** `https://docs.kick.com`

### OAuth Scopes
- `user:read`, `channel:read`, `channel:write`
- `chat:write`, `streamkey:read`, `events:subscribe`
- `moderation:ban`, `moderation:chat_message:manage`, `kicks:read`

### Webhook Events (subscribe via POST /api/v1/events/subscriptions)
| Event | Payload key fields |
|---|---|
| `chat.message.sent` | message_id, content, sender.username, sender.user_id, broadcaster_user_id, replied_to |
| `channel.followed` | username, user_id, broadcaster_user_id |
| `channel.subscription.new` | username, user_id, months, broadcaster_user_id |
| `channel.subscription.renewal` | same as above |
| `channel.subscription.gifts` | username, user_id, is_gift, broadcaster_user_id |
| `kicks.gifted` | gifter.username, gifter.user_id, amount, broadcaster_user_id |
| `livestream.status.updated` | is_live, title, broadcaster_user_id |
| `moderation.banned` | user_id, broadcaster_user_id |
| `channel.reward.redemption.updated` | reward details |

### Webhook Security
- Kick signs payloads with Ed25519
- Headers: `Kick-Event-Signature`, `Kick-Event-Message-Id`, `Kick-Event-Message-Timestamp`, `Kick-Event-Type`, `Kick-Event-Subscription-Id`
- Public key: `GET /public-key`
- Verify: message = message_id + timestamp + body → Ed25519 verify with public key
- Kick retries 3 times if non-200 response; auto-unsubscribes if server unreachable

### Key REST Endpoints
- `POST /api/v1/chat` — send message (fields: broadcaster_user_id, content, type: "bot"|"user")
- `GET /api/v1/channels?slug={slug}` — channel info
- `GET /api/v1/livestreams?broadcaster_user_id={id}` — livestream info
- `POST /api/v1/moderation/ban` — ban/timeout user
- `DELETE /api/v1/moderation/ban` — unban
- `DELETE /api/v1/chat/{message_id}` — delete message
- `POST /api/v1/events/subscriptions` — subscribe to webhook events
- `GET /api/v1/events/subscriptions` — list subscriptions
- `GET /api/v1/kicks/leaderboard` — kicks leaderboard

---

## Package 1: kickforge_core (Priority: HIGHEST)

The foundation. Every other package depends on this.

### Design Principles
- **Async-first:** All API/webhook operations are async (asyncio + httpx)
- **Decorator API:** `@app.on("event_type")` pattern for event handlers
- **Zero config start:** `KickApp(client_id, client_secret)` → `.run()` should work
- **Type safety:** Pydantic models or dataclasses for all events

### KickApp — Developer Experience Target
```python
from kickforge_core import KickApp

app = KickApp(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
)

@app.on("chat.message.sent")
async def on_chat(event):
    if event.message.startswith("!hello"):
        await app.say(f"Hey {event.sender.username}!")

@app.on("kicks.gifted")
async def on_gift(event):
    print(f"{event.gifter_username} gifted {event.kicks_amount} kicks!")

app.run(port=8420)
```

### CLI
- `kickforge init <name>` — scaffold project (config.yaml + bot.py + .gitignore)
- `kickforge check` — verify credentials against Kick API
- `kickforge run <file>` — run a KickForge app

### Implementation Notes
- Use `fastapi` for webhook server, `httpx` for async HTTP
- Ed25519 signature verification: use `cryptography` library (`ed25519.Ed25519PublicKey.verify()`)
- Token caching: in-memory dict with TTL, auto-refresh 60s before expiry
- EventBus: simple dict[str, list[handler]], asyncio.gather for parallel dispatch, try/except per handler

---

## Package 2: kickforge_bot (Priority: HIGH)

Bot framework on top of core. Think Nightbot but Pythonic and extensible.

### Command Handler
```python
from kickforge_bot import KickBot

bot = KickBot(client_id="...", client_secret="...")

@bot.command("!ping", cooldown=5)
async def ping(ctx):
    await ctx.reply("pong! 🏓")

@bot.command("!dice", cooldown=10)
async def dice(ctx):
    import random
    await ctx.reply(f"🎲 You rolled {random.randint(1,6)}!")

# Permission levels: everyone, subscriber, moderator, broadcaster
@bot.command("!ban", permission="moderator")
async def ban(ctx):
    target = ctx.args[0] if ctx.args else None
    if target:
        await bot.api.ban_user(ctx.broadcaster_id, target_user_id=..., duration=600)
```

### CommandContext
```python
@dataclass
class CommandContext:
    event: ChatMessageEvent      # The raw event
    command: str                  # "ping" (without prefix)
    args: list[str]              # ["arg1", "arg2"]
    sender: Sender               # username, badges, is_sub
    broadcaster_id: int
    
    async def reply(self, message: str) -> None: ...
    async def send(self, message: str) -> None: ...  # Non-reply
```

### Loyalty/XP System
- SQLite backend (`loyalty.db`)
- Track: user_id, username, xp, level, total_watch_minutes, total_messages, first_seen, last_seen
- XP sources: watch time (1/min), messages (5/msg), sub (500), gift (proportional)
- Level thresholds configurable via YAML
- Commands: `!rank`, `!top10`, `!level`
- Integration: EventBus hooks (on every chat message → +5 XP, on gift → +amount XP)

### Auto-Moderation
- Blacklist words/phrases (regex support)
- Caps lock limit (% threshold)
- Spam detection (repeated messages within N seconds)
- Link filtering (allow/block with whitelist)
- Actions: warn (chat message), timeout (via API), ban (via API)
- All configurable via YAML

### Timed Messages
- List of (message, interval_seconds) pairs
- Asyncio background tasks
- Only fire when stream is live (check via GSI or API)

### Plugin System
```python
class Plugin:
    async def on_load(self, bot: KickBot) -> None: ...
    async def on_message(self, event: ChatMessageEvent) -> None: ...
    async def on_follow(self, event: FollowEvent) -> None: ...
    async def on_gift(self, event: GiftEvent) -> None: ...
    async def on_sub(self, event: SubscriptionEvent) -> None: ...

# Registration
bot.load_plugin(MyCustomPlugin())
```

---

## Package 3: kickforge_gsi (Priority: HIGH)

Game-to-Kick bridge. Routes Kick events to in-game actions.

### Adapter Interface
```python
class GameAdapter(ABC):
    @abstractmethod
    async def connect(self) -> None: ...
    
    @abstractmethod
    async def execute(self, action: str, params: dict) -> str: ...
    
    @abstractmethod
    async def get_state(self) -> dict: ...
    
    @abstractmethod
    async def disconnect(self) -> None: ...
```

### Minecraft RCON Adapter
- Uses `mcrcon` library
- Commands: summon, give, kill, tp, effect, fill, weather, time, say
- Connection pooling for performance

### CS2 GSI Adapter (Read-only)
- Listens on HTTP port for CS2 GSI POST data
- Config file generator for CS2 cfg directory
- Events: kill, death, bomb_planted, bomb_defused, round_start, round_end, mvp
- Exposes: player HP, armor, money, kills, deaths, current weapon, match score

### CS2 RCON Adapter (Write)
- Source RCON protocol implementation (TCP, different from Minecraft RCON)
- Commands: sv_gravity, sv_maxspeed, god, noclip, give, ent_create, say, mp_restartgame
- NOTE: RCON only works on community/dedicated servers, not matchmaking

### Tier Engine
```yaml
# example_tiers.yaml
game: minecraft
actions:
  chicken_army:
    command: "summon chicken ~ ~2 ~ {CustomName:'\"{{user}}\"'}"
    repeat: 5
    chat_response: "🐔 {{user}} spawned a chicken army!"
    
  creeper_wave:
    command: "summon creeper ~ ~5 ~"
    repeat: 3
    chat_response: "💥 {{user}} unleashed creepers!"

tiers:
  - range: [1, 10]
    actions: [chicken_army]
    cooldown: 10
    
  - range: [11, 50]
    actions: [creeper_wave, lightning_strike]
    cooldown: 30
    
  - range: [51, 200]
    actions: [wither_spawn, tnt_rain]
    cooldown: 60
    
  - range: [200, 99999]
    actions: [ender_dragon]
    cooldown: 120

chat_commands:
  "!spawn":
    action: random_mob
    cooldown: 30
    permission: everyone
```

### Cooldown Manager
- Per-action global cooldown
- Per-user cooldown (optional)
- Thread-safe (asyncio Lock)
- Returns remaining seconds if on cooldown

---

## Package 4: kickforge_clip (Priority: MEDIUM)

Auto-detect hype moments and cut clips.

### Heat Detector
- Sliding window (configurable, default 60s)
- Metrics: messages_per_second, unique_chatters_per_window, emote_frequency
- Heat score = weighted combination
- Threshold configurable, fires "heat_moment" event with timestamp + score

### Clipper
- Input: OBS recording file path (mp4/mkv) OR RTMP URL
- Uses FFmpeg subprocess: `ffmpeg -ss {start} -t {duration} -i {input} -c copy {output}`
- Clip window: configurable (default ±30s around heat peak)
- Output: numbered clips in output directory

### Formatter (Shorts pipeline)
- 16:9 → 9:16 center crop (or face-tracking crop if available)
- Subtitle overlay using Whisper STT (optional dependency)
- FFmpeg filter chain: crop → scale → drawtext
- Output: mobile-ready vertical video

### Exporter
- Batch mode: process all clips after stream ends
- Rank by heat score, export top N
- Discord webhook notification with clip preview
- File naming: `{date}_{rank}_{score}.mp4`

---

## Package 5: kickforge_overlay (Priority: MEDIUM)

Real-time OBS widgets via WebSocket.

### WebSocket Server
- Part of KickApp — starts alongside webhook server
- Port 8765 (configurable)
- Broadcasts JSON events to all connected widget clients
- Event types: chat_velocity, gift_received, follow, sub, heat_score, leaderboard_update

### Widget Design
- Each widget = standalone HTML file
- Connect to `ws://localhost:8765` on load
- Parse incoming JSON, update DOM
- Transparent background (for OBS Browser Source)
- URL params for customization: `?theme=dark&color=red&position=topright`
- No external dependencies (vanilla JS + CSS)

### Widget Specs

**velocity.html** — Animated gauge/line chart showing messages per minute. Updates every 2 seconds.

**hype_bar.html** — Vertical progress bar that fills on events (gifts, follows, subs). Decays slowly over time. At 100%: flash animation + confetti.

**event_feed.html** — Scrolling list of last 10 events. New events slide in from right. Format: "🔥 username → action". Auto-fade old events.

**leaderboard.html** — Top 5 gifters or XP holders. Updates on each gift. Animate position changes.

**prediction.html** — Shows a question + two option bars with vote counts. Timer countdown. Results animation.

**chaos_meter.html** — Circular or horizontal meter. Increases with gifts, decreases over time. Thresholds trigger visual changes (calm → chaos → MEGA CHAOS).

---

## Development Order

### Sprint 1 (Week 1): Core Engine
1. `kickforge_core/auth.py` — full OAuth 2.1
2. `kickforge_core/events.py` — all event models + EventBus
3. `kickforge_core/webhook.py` — FastAPI + Ed25519 verification
4. `kickforge_core/api.py` — all REST endpoints
5. `kickforge_core/app.py` — KickApp orchestrator
6. `kickforge_core/cli.py` — init/check/run commands
7. Tests for all of the above

### Sprint 2 (Week 2-3): Bot Framework
1. `kickforge_bot/commands/handler.py` — decorator command system
2. `kickforge_bot/loyalty.py` — SQLite XP system
3. `kickforge_bot/moderation.py` — auto-mod rules
4. `kickforge_bot/timers.py` — timed messages
5. `kickforge_bot/polls.py` — polls + giveaways
6. `kickforge_bot/plugins/base.py` — plugin interface

### Sprint 3 (Week 3-4): Game Bridge
1. `kickforge_gsi/adapters/base.py` — abstract interface
2. `kickforge_gsi/adapters/minecraft.py` — RCON adapter
3. `kickforge_gsi/adapters/cs2_gsi.py` — GSI reader
4. `kickforge_gsi/adapters/cs2_rcon.py` — Source RCON
5. `kickforge_gsi/tiers.py` — YAML tier engine
6. `kickforge_gsi/bridge.py` — event → action router

### Sprint 4 (Week 5): Clips + Overlays
1. `kickforge_clip/detector.py` — heat detection
2. `kickforge_clip/clipper.py` — FFmpeg integration
3. `kickforge_overlay/server/ws_server.py` — WebSocket broadcaster
4. All 6 overlay widgets (HTML/CSS/JS)

---

## Starter Code

There are already skeleton files in the repo that can be used as starting points. The core module files (`auth.py`, `events.py`, `webhook.py`, `api.py`, `app.py`, `cli.py`) have working implementations that need to be refined:

- `auth.py`: OAuth 2.1 flows work but Ed25519 signature verification needs proper `cryptography` library integration instead of HMAC placeholder
- `events.py`: All 6 event models + EventBus are complete
- `webhook.py`: FastAPI server works, signature verification needs real Ed25519
- `api.py`: All endpoints covered, error handling needs improvement
- `app.py`: KickApp works but needs graceful shutdown improvements
- `cli.py`: `init` scaffolding is complete and generates working project

## Testing Strategy
- Use `pytest` + `pytest-asyncio`
- Mock Kick API responses with `httpx.MockTransport`
- Test EventBus independently (emit → handler called)
- Test webhook signature verification with known test vectors
- Test CLI `init` output (check generated files exist and are valid)

## Code Quality
- `ruff` for linting
- `mypy --strict` for type checking
- All public functions/classes need docstrings
- 100% type annotations on public API
