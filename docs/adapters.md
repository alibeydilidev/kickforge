# Writing Custom Game Adapters

KickForge's game integration system is built around the **GameAdapter** interface. Any game that can receive commands over a network protocol (RCON, HTTP, TCP, WebSocket) can be integrated by writing a small adapter class.

This guide covers everything you need to build, configure, and deploy your own adapter.

---

## Architecture Overview

```
Kick Event (gift / chat command)
        |
    EventBus
        |
  KickGameBridge
        |
    TierEngine  -->  resolve amount to actions
        |
  CooldownManager  -->  check / set cooldowns
        |
    GameAdapter.execute(command, params)
        |
    Your Game Server
```

The **bridge** listens for Kick events, the **tier engine** decides which actions to fire, and the **adapter** sends the actual commands.

---

## The GameAdapter Interface

Every adapter must implement four async methods:

```python
from kickforge_gsi.adapters.base import GameAdapter
from typing import Any

class MyAdapter(GameAdapter):
    name = "my_game"

    async def connect(self) -> None:
        """Open a connection to your game server."""
        ...

    async def execute(self, action: str, params: dict[str, Any]) -> str:
        """
        Run a game command.

        Args:
            action: The command string with template vars already expanded
                    (e.g. "spawn zombie at alice").
            params: The raw template variables (user, amount) in case
                    your adapter needs them separately.

        Returns:
            Response text from the server (or empty string).
        """
        ...

    async def get_state(self) -> dict[str, Any]:
        """Return the current game state as a dict."""
        ...

    async def disconnect(self) -> None:
        """Close the connection."""
        ...
```

The `name` attribute is used in logs and config files.

---

## Step-by-Step: Building a Custom Adapter

### Example: FiveM Server Adapter

FiveM exposes an HTTP API. Here's a complete adapter:

```python
from __future__ import annotations
import logging
from typing import Any, Optional
import httpx
from kickforge_gsi.adapters.base import GameAdapter

logger = logging.getLogger("kickforge.gsi.fivem")


class FiveMAdapter(GameAdapter):
    name = "fivem"

    def __init__(self, base_url: str, auth_token: str = "") -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self._http: Optional[httpx.AsyncClient] = None
        self._connected = False

    async def connect(self) -> None:
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        self._http = httpx.AsyncClient(
            base_url=self.base_url, headers=headers, timeout=10.0,
        )
        self._connected = True
        logger.info("FiveM adapter connected to %s", self.base_url)

    async def execute(self, action: str, params: dict[str, Any]) -> str:
        if not self._http:
            raise ConnectionError("Not connected")
        resp = await self._http.post("/api/command", json={"command": action})
        resp.raise_for_status()
        return resp.text

    async def get_state(self) -> dict[str, Any]:
        if not self._http:
            return {"connected": False}
        resp = await self._http.get("/api/status")
        return resp.json()

    async def disconnect(self) -> None:
        if self._http:
            await self._http.aclose()
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected
```

### Registering Your Adapter

Pass it to the bridge:

```python
from kickforge_core import KickApp
from kickforge_gsi import KickGameBridge, TierEngine

app = KickApp(client_id="...", client_secret="...")
adapter = FiveMAdapter(base_url="http://localhost:30120")
engine = TierEngine.from_yaml("tiers.yaml")

bridge = KickGameBridge(
    bus=app.bus,
    adapter=adapter,
    tier_engine=engine,
    send_func=lambda bid, msg: app.api.send_message(bid, msg),
)
bridge.register()
```

---

## YAML Tier Configuration

The tier config maps gift amounts to game actions:

```yaml
game: fivem

actions:
  spawn_car:
    command: "spawn_vehicle {{user}} adder"
    repeat: 1
    chat_response: "{{user}} spawned a supercar!"

  money_drop:
    command: "give_money {{user}} 5000"
    repeat: 1
    chat_response: "{{user}} got $5000!"

tiers:
  - range: [1, 20]
    actions: [spawn_car]
    cooldown: 30

  - range: [21, 100]
    actions: [spawn_car, money_drop]
    cooldown: 60

chat_commands:
  "!car":
    action: spawn_car
    cooldown: 60
    permission: everyone
```

### Template Variables

| Variable | Description |
|---|---|
| `{{user}}` | Username of the gifter / command sender |
| `{{amount}}` | Gift amount (kicks) |

### Tier Fields

| Field | Type | Description |
|---|---|---|
| `range` | `[min, max]` | Gift amount range (inclusive) |
| `actions` | `list[str]` | Action names to execute |
| `cooldown` | `float` | Global cooldown in seconds |

### Action Fields

| Field | Type | Description |
|---|---|---|
| `command` | `str` | The command string sent to the adapter |
| `repeat` | `int` | How many times to execute (default: 1) |
| `chat_response` | `str` | Message sent to Kick chat after execution |

---

## Cooldown System

The `CooldownManager` supports two levels:

- **Global cooldown** — per action, shared across all users.
- **Per-user cooldown** — per action per user (for chat commands).

```python
from kickforge_gsi.cooldown import CooldownManager

cd = CooldownManager()

# Check global cooldown
remaining = await cd.check("spawn_car")

# Trigger 30-second global cooldown
await cd.trigger("spawn_car", cooldown=30)

# Per-user cooldown
remaining = await cd.check("spawn_car", user_id=42)
await cd.trigger("spawn_car", cooldown=10, user_id=42)
```

---

## Built-in Adapters

| Adapter | Protocol | Import |
|---|---|---|
| `MinecraftRCONAdapter` | Minecraft RCON | `kickforge_gsi.adapters.minecraft` |
| `CS2GSIAdapter` | HTTP (read-only) | `kickforge_gsi.adapters.cs2_gsi` |
| `CS2RCONAdapter` | Source RCON (TCP) | `kickforge_gsi.adapters.cs2_rcon` |
| `GenericHTTPAdapter` | HTTP POST/GET | `kickforge_gsi.adapters.generic_http` |

Use `GenericHTTPAdapter` as a quick way to integrate any game with an HTTP API without writing a custom adapter class.

---

## Tips

- **Retry logic**: Add connection retries in `connect()` for flaky game servers. See `MinecraftRCONAdapter` for a reference pattern.
- **asyncio**: All methods are `async`. For blocking protocols (like raw TCP), use `asyncio.get_event_loop().run_in_executor()`.
- **State tracking**: `get_state()` should return whatever is useful for overlays and dashboards. At minimum return `{"connected": bool}`.
- **Error handling**: Never let exceptions in `execute()` crash the bridge. Log and return an empty string on failure.
