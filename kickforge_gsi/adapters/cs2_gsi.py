"""
CS2 Game State Integration (GSI) reader — read-only adapter.

Listens on a local HTTP port for JSON POST data from CS2's
built-in Game State Integration system.  Parses player state
and emits game events via callbacks.

Events: kill, death, bomb_planted, bomb_defused, round_start,
        round_end, mvp.

Exposes: player HP, armor, money, kills, deaths, current weapon,
         match score.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Coroutine, Optional

from fastapi import FastAPI, Request, Response

logger = logging.getLogger("kickforge.gsi.cs2_gsi")


@dataclass
class CS2PlayerState:
    """Snapshot of the local player's state from GSI data."""

    steam_id: str = ""
    name: str = ""
    team: str = ""
    health: int = 0
    armor: int = 0
    money: int = 0
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    mvps: int = 0
    current_weapon: str = ""
    round_kills: int = 0
    round_totaldmg: int = 0
    ct_score: int = 0
    t_score: int = 0


@dataclass
class CS2GameEvent:
    """A derived game event detected by comparing consecutive states."""

    event_type: str  # kill, death, bomb_planted, bomb_defused, round_start, round_end, mvp
    data: dict[str, Any] = field(default_factory=dict)


GSICallback = Callable[[CS2GameEvent], Coroutine[Any, Any, None]]


class CS2GSIAdapter:
    """
    Read-only adapter that receives CS2 Game State Integration data.

    Usage:
        adapter = CS2GSIAdapter(port=3000)

        @adapter.on_event
        async def handle(event: CS2GameEvent):
            print(event.event_type, event.data)

        await adapter.connect()   # starts the HTTP listener
        await adapter.disconnect() # stops it
    """

    name = "cs2_gsi"

    def __init__(self, port: int = 3000, host: str = "127.0.0.1") -> None:
        self.port = port
        self.host = host
        self._state = CS2PlayerState()
        self._prev_state = CS2PlayerState()
        self._callbacks: list[GSICallback] = []
        self._raw: dict[str, Any] = {}
        self._server_task: Optional[asyncio.Task[None]] = None
        self._connected = False

        self.app = FastAPI(title="CS2 GSI Receiver", docs_url=None, redoc_url=None)
        self._setup_routes()

    def on_event(self, func: GSICallback) -> GSICallback:
        """Decorator to register a game-event callback."""
        self._callbacks.append(func)
        return func

    # ------------------------------------------------------------------
    # FastAPI routes
    # ------------------------------------------------------------------

    def _setup_routes(self) -> None:
        @self.app.post("/")
        async def gsi_post(request: Request) -> Response:
            body = await request.body()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                return Response(status_code=400)
            await self._process(data)
            return Response(status_code=200)

        @self.app.get("/state")
        async def get_state_http() -> dict[str, Any]:
            return await self.get_state()

    # ------------------------------------------------------------------
    # State processing & event derivation
    # ------------------------------------------------------------------

    async def _process(self, data: dict[str, Any]) -> None:
        self._raw = data
        self._prev_state = self._state
        self._state = self._parse_state(data)
        events = self._derive_events(self._prev_state, self._state, data)
        for ev in events:
            await self._dispatch(ev)

    @staticmethod
    def _parse_state(data: dict[str, Any]) -> CS2PlayerState:
        player = data.get("player", {})
        state = player.get("state", {})
        match_stats = player.get("match_stats", {})
        weapons = player.get("weapons", {})
        map_data = data.get("map", {})
        team_ct = map_data.get("team_ct", {})
        team_t = map_data.get("team_t", {})

        # Find active weapon
        current_weapon = ""
        for w in weapons.values():
            if isinstance(w, dict) and w.get("state") == "active":
                current_weapon = w.get("name", "")
                break

        return CS2PlayerState(
            steam_id=player.get("steamid", ""),
            name=player.get("name", ""),
            team=player.get("team", ""),
            health=state.get("health", 0),
            armor=state.get("armor", 0),
            money=state.get("money", 0),
            kills=match_stats.get("kills", 0),
            deaths=match_stats.get("deaths", 0),
            assists=match_stats.get("assists", 0),
            mvps=match_stats.get("mvps", 0),
            round_kills=state.get("round_kills", 0),
            round_totaldmg=state.get("round_totaldmg", 0),
            current_weapon=current_weapon,
            ct_score=team_ct.get("score", 0),
            t_score=team_t.get("score", 0),
        )

    @staticmethod
    def _derive_events(
        prev: CS2PlayerState, curr: CS2PlayerState, raw: dict[str, Any]
    ) -> list[CS2GameEvent]:
        events: list[CS2GameEvent] = []

        # Kill detection
        if curr.round_kills > prev.round_kills:
            events.append(CS2GameEvent(
                event_type="kill",
                data={"kills_this_round": curr.round_kills, "weapon": curr.current_weapon},
            ))

        # Death detection
        if curr.health == 0 and prev.health > 0:
            events.append(CS2GameEvent(event_type="death", data={}))

        # MVP
        if curr.mvps > prev.mvps:
            events.append(CS2GameEvent(event_type="mvp", data={"total_mvps": curr.mvps}))

        # Round phase from raw data
        round_data = raw.get("round", {})
        phase = round_data.get("phase", "")
        prev_round = raw.get("previously", {}).get("round", {})
        prev_phase = prev_round.get("phase", "")

        if phase == "live" and prev_phase in ("freezetime", ""):
            events.append(CS2GameEvent(event_type="round_start", data={
                "ct_score": curr.ct_score, "t_score": curr.t_score,
            }))
        if phase == "over" and prev_phase == "live":
            win_team = round_data.get("win_team", "")
            events.append(CS2GameEvent(event_type="round_end", data={
                "win_team": win_team,
                "ct_score": curr.ct_score, "t_score": curr.t_score,
            }))

        # Bomb
        bomb = round_data.get("bomb", "")
        prev_bomb = prev_round.get("bomb", "")
        if bomb == "planted" and prev_bomb != "planted":
            events.append(CS2GameEvent(event_type="bomb_planted", data={}))
        if bomb == "defused" and prev_bomb != "defused":
            events.append(CS2GameEvent(event_type="bomb_defused", data={}))

        return events

    async def _dispatch(self, event: CS2GameEvent) -> None:
        for cb in self._callbacks:
            try:
                await cb(event)
            except Exception:
                logger.exception("GSI callback raised for event %s", event.event_type)

    # ------------------------------------------------------------------
    # GameAdapter interface
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the GSI HTTP listener."""
        import uvicorn

        config = uvicorn.Config(
            self.app, host=self.host, port=self.port,
            log_level="warning", access_log=False,
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        self._connected = True
        logger.info("CS2 GSI listener started on %s:%d", self.host, self.port)

    async def get_state(self) -> dict[str, Any]:
        """Return the latest player state as a dict."""
        s = self._state
        return {
            "steam_id": s.steam_id,
            "name": s.name,
            "team": s.team,
            "health": s.health,
            "armor": s.armor,
            "money": s.money,
            "kills": s.kills,
            "deaths": s.deaths,
            "assists": s.assists,
            "mvps": s.mvps,
            "current_weapon": s.current_weapon,
            "round_kills": s.round_kills,
            "ct_score": s.ct_score,
            "t_score": s.t_score,
        }

    async def disconnect(self) -> None:
        """Stop the GSI listener."""
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None
        self._connected = False
        logger.info("CS2 GSI listener stopped")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ------------------------------------------------------------------
    # Config file generator
    # ------------------------------------------------------------------

    @staticmethod
    def generate_config(
        output_path: str | Path,
        uri: str = "http://127.0.0.1:3000",
        auth_token: str = "kickforge",
        timeout: float = 5.0,
        buffer: float = 0.1,
        throttle: float = 0.5,
    ) -> Path:
        """
        Generate a ``gamestate_integration_kickforge.cfg`` for CS2.

        Place the output file in:
            <CS2>/game/csgo/cfg/gamestate_integration_kickforge.cfg

        Returns:
            The path the config was written to.
        """
        content = f'''"kickforge_gsi"
{{
    "uri"           "{uri}"
    "timeout"       "{timeout}"
    "buffer"        "{buffer}"
    "throttle"      "{throttle}"
    "auth"
    {{
        "token"     "{auth_token}"
    }}
    "data"
    {{
        "provider"      "1"
        "map"           "1"
        "round"         "1"
        "player_id"     "1"
        "player_state"  "1"
        "player_weapons" "1"
        "player_match_stats" "1"
        "bomb"          "1"
    }}
}}
'''
        path = Path(output_path)
        path.write_text(content)
        logger.info("CS2 GSI config written to %s", path)
        return path
