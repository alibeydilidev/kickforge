"""
YAML-driven tier engine.

Maps gift amounts to in-game actions using a tiered configuration
file.  Supports template variables (``{{user}}``, ``{{amount}}``),
repeat counts, and chat response templates.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

logger = logging.getLogger("kickforge.gsi.tiers")


@dataclass
class ActionDef:
    """A single game action from the config."""

    name: str
    command: str
    repeat: int = 1
    chat_response: str = ""


@dataclass
class TierDef:
    """A tier range that maps gift amounts to actions."""

    range_min: int
    range_max: int
    actions: list[str]
    cooldown: float = 0.0


@dataclass
class ChatCommandDef:
    """A chat-triggered game command (e.g. ``!spawn``)."""

    command: str
    action: str
    cooldown: float = 0.0
    permission: str = "everyone"


@dataclass
class TierConfig:
    """Full parsed tier configuration."""

    game: str = ""
    actions: dict[str, ActionDef] = field(default_factory=dict)
    tiers: list[TierDef] = field(default_factory=list)
    chat_commands: dict[str, ChatCommandDef] = field(default_factory=dict)


class TierEngine:
    """
    Resolves gift amounts → game actions using a YAML tier config.

    Usage:
        engine = TierEngine.from_yaml("tiers.yaml")
        result = engine.resolve(amount=25, user="alice")
        # result.actions, result.commands, result.chat_responses
    """

    def __init__(self, config: TierConfig) -> None:
        self.config = config

    @classmethod
    def from_yaml(cls, path: str) -> TierEngine:
        """Load tier config from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)
        return cls(parse_tier_config(data))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TierEngine:
        """Load tier config from a dict (useful for testing)."""
        return cls(parse_tier_config(data))

    def resolve(
        self,
        amount: int,
        user: str = "",
    ) -> Optional[TierMatch]:
        """
        Find the matching tier for a gift amount and expand actions.

        Returns None if no tier matches.
        """
        for tier in self.config.tiers:
            if tier.range_min <= amount <= tier.range_max:
                commands: list[str] = []
                chat_responses: list[str] = []

                for action_name in tier.actions:
                    action_def = self.config.actions.get(action_name)
                    if not action_def:
                        logger.warning("Unknown action '%s' in tier config", action_name)
                        continue
                    expanded = _expand_template(action_def.command, user=user, amount=amount)
                    for _ in range(action_def.repeat):
                        commands.append(expanded)
                    if action_def.chat_response:
                        chat_responses.append(
                            _expand_template(action_def.chat_response, user=user, amount=amount)
                        )

                return TierMatch(
                    tier=tier,
                    action_names=list(tier.actions),
                    commands=commands,
                    chat_responses=chat_responses,
                    cooldown=tier.cooldown,
                )

        return None

    def resolve_chat_command(self, cmd: str) -> Optional[ChatCommandDef]:
        """Look up a chat command (e.g. "!spawn")."""
        return self.config.chat_commands.get(cmd)


@dataclass
class TierMatch:
    """Result of resolving a gift amount against tiers."""

    tier: TierDef
    action_names: list[str]
    commands: list[str]
    chat_responses: list[str]
    cooldown: float = 0.0


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

def parse_tier_config(data: dict[str, Any]) -> TierConfig:
    """Parse a YAML-loaded dict into a TierConfig."""
    actions: dict[str, ActionDef] = {}
    for name, adef in data.get("actions", {}).items():
        actions[name] = ActionDef(
            name=name,
            command=adef.get("command", ""),
            repeat=adef.get("repeat", 1),
            chat_response=adef.get("chat_response", ""),
        )

    tiers: list[TierDef] = []
    for tdef in data.get("tiers", []):
        r = tdef.get("range", [0, 0])
        tiers.append(TierDef(
            range_min=r[0],
            range_max=r[1],
            actions=tdef.get("actions", []),
            cooldown=tdef.get("cooldown", 0.0),
        ))

    chat_commands: dict[str, ChatCommandDef] = {}
    for cmd, cdef in data.get("chat_commands", {}).items():
        chat_commands[cmd] = ChatCommandDef(
            command=cmd,
            action=cdef.get("action", ""),
            cooldown=cdef.get("cooldown", 0.0),
            permission=cdef.get("permission", "everyone"),
        )

    return TierConfig(
        game=data.get("game", ""),
        actions=actions,
        tiers=tiers,
        chat_commands=chat_commands,
    )


def _expand_template(template: str, user: str = "", amount: int = 0) -> str:
    """Replace ``{{user}}`` and ``{{amount}}`` in a template string."""
    result = template.replace("{{user}}", user)
    result = result.replace("{{amount}}", str(amount))
    return result
