"""
KickForge GSI — game-to-Kick bridge for interactive streaming.

Supports Minecraft (RCON), CS2 (GSI + RCON), and any HTTP-based
game server.  The tier engine maps Kick gift amounts to in-game
actions using a simple YAML config.
"""

from kickforge_gsi.adapters.base import GameAdapter
from kickforge_gsi.adapters.minecraft import MinecraftRCONAdapter
from kickforge_gsi.adapters.cs2_gsi import CS2GSIAdapter, CS2GameEvent, CS2PlayerState
from kickforge_gsi.adapters.cs2_rcon import CS2RCONAdapter
from kickforge_gsi.adapters.generic_http import GenericHTTPAdapter
from kickforge_gsi.tiers import TierEngine, TierConfig, TierMatch, ActionDef, TierDef
from kickforge_gsi.cooldown import CooldownManager
from kickforge_gsi.bridge import KickGameBridge

__all__ = [
    "GameAdapter",
    "MinecraftRCONAdapter",
    "CS2GSIAdapter",
    "CS2GameEvent",
    "CS2PlayerState",
    "CS2RCONAdapter",
    "GenericHTTPAdapter",
    "TierEngine",
    "TierConfig",
    "TierMatch",
    "ActionDef",
    "TierDef",
    "CooldownManager",
    "KickGameBridge",
]
