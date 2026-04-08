"""
KickGameBridge — orchestrator that wires Kick events to game actions.

Listens on the KickApp EventBus for ``kicks.gifted`` and
``chat.message.sent`` events, resolves tiers, checks cooldowns,
executes adapter commands, and sends chat responses.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Coroutine, Optional

from kickforge_core.events import ChatMessageEvent, EventBus, GiftEvent
from kickforge_gsi.adapters.base import GameAdapter
from kickforge_gsi.cooldown import CooldownManager
from kickforge_gsi.tiers import TierEngine

logger = logging.getLogger("kickforge.gsi.bridge")

SendFunc = Callable[[int, str], Coroutine[Any, Any, None]]


class KickGameBridge:
    """
    Routes Kick events to in-game actions via the tier engine.

    Usage:
        bridge = KickGameBridge(
            bus=app.bus,
            adapter=minecraft_adapter,
            tier_engine=TierEngine.from_yaml("tiers.yaml"),
            send_func=app.api.send_message,
        )
        bridge.register()          # hooks onto the event bus
        await bridge.start()       # connects adapter
        ...
        await bridge.stop()        # disconnects adapter
    """

    def __init__(
        self,
        bus: EventBus,
        adapter: GameAdapter,
        tier_engine: TierEngine,
        send_func: Optional[SendFunc] = None,
    ) -> None:
        self.bus = bus
        self.adapter = adapter
        self.tier_engine = tier_engine
        self.cooldowns = CooldownManager()
        self._send = send_func
        self._registered = False

    def register(self) -> None:
        """Register event handlers on the bus."""
        if self._registered:
            return

        @self.bus.on("kicks.gifted")
        async def _on_gift(event: GiftEvent) -> None:
            await self._handle_gift(event)

        @self.bus.on("chat.message.sent")
        async def _on_chat(event: ChatMessageEvent) -> None:
            await self._handle_chat_command(event)

        self._registered = True
        logger.info("KickGameBridge registered on event bus")

    async def start(self) -> None:
        """Connect the game adapter."""
        await self.adapter.connect()
        logger.info("KickGameBridge started (adapter=%s)", self.adapter.name)

    async def stop(self) -> None:
        """Disconnect the game adapter."""
        await self.adapter.disconnect()
        logger.info("KickGameBridge stopped")

    # ------------------------------------------------------------------
    # Gift → tier → game action
    # ------------------------------------------------------------------

    async def _handle_gift(self, event: GiftEvent) -> None:
        match = self.tier_engine.resolve(
            amount=event.kicks_amount,
            user=event.gifter_username,
        )
        if not match:
            return

        # Check cooldown (use first action name as key)
        cd_key = "|".join(match.action_names)
        remaining = await self.cooldowns.check(cd_key)
        if remaining > 0:
            logger.debug("Gift action on cooldown (%.0fs remaining)", remaining)
            return

        # Execute all commands
        for cmd in match.commands:
            try:
                await self.adapter.execute(cmd, {
                    "user": event.gifter_username,
                    "amount": event.kicks_amount,
                })
            except Exception:
                logger.exception("Adapter execute failed: %s", cmd)

        # Trigger cooldown
        if match.cooldown > 0:
            await self.cooldowns.trigger(cd_key, match.cooldown)

        # Send chat responses
        if self._send and event.broadcaster_user_id:
            for msg in match.chat_responses:
                try:
                    await self._send(event.broadcaster_user_id, msg)
                except Exception:
                    logger.exception("Failed to send chat response")

    # ------------------------------------------------------------------
    # Chat command → game action
    # ------------------------------------------------------------------

    async def _handle_chat_command(self, event: ChatMessageEvent) -> None:
        if not event.message or not event.message.startswith("!"):
            return

        cmd_word = event.message.strip().split()[0]
        cmd_def = self.tier_engine.resolve_chat_command(cmd_word)
        if not cmd_def:
            return

        sender = event.sender
        user_id = sender.user_id if sender else 0
        username = sender.username if sender else "unknown"

        # Cooldown
        remaining = await self.cooldowns.check(cmd_def.action, user_id=user_id)
        if remaining > 0:
            return

        # Resolve action from actions dict
        action_def = self.tier_engine.config.actions.get(cmd_def.action)
        if not action_def:
            return

        expanded = action_def.command.replace("{{user}}", username)
        for _ in range(action_def.repeat):
            try:
                await self.adapter.execute(expanded, {"user": username})
            except Exception:
                logger.exception("Chat command adapter execute failed")

        if cmd_def.cooldown > 0:
            await self.cooldowns.trigger(cmd_def.action, cmd_def.cooldown, user_id=user_id)

        if action_def.chat_response and self._send and event.broadcaster_user_id:
            msg = action_def.chat_response.replace("{{user}}", username)
            try:
                await self._send(event.broadcaster_user_id, msg)
            except Exception:
                logger.exception("Failed to send chat command response")
