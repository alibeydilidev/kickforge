"""
KickForge — CS2 Interactive Stream Example
============================================

Connects Kick gifts/chat to a CS2 community server.
Viewers can trigger in-game chaos by gifting kicks or typing commands.

Requirements:
    - A CS2 dedicated server with RCON enabled
    - pip install kickforge
    - Kick Dev credentials

Architecture:
    Kick Webhook → KickForge Core → Action Router → CS2 RCON
    CS2 GSI      → KickForge Core → OBS Overlay WebSocket
"""

import asyncio
import logging
from dataclasses import dataclass
from kickforge_core import KickApp

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

RCON_HOST = "localhost"
RCON_PORT = 27015
RCON_PASSWORD = "your_rcon_password"
CS2_PLAYER_NAME = "Yargitay"

app = KickApp(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
)

# ---------------------------------------------------------------------------
# Tier definitions — gift amount → in-game action
# ---------------------------------------------------------------------------

@dataclass
class GameAction:
    name: str
    rcon_command: str
    chat_response: str
    cooldown: int = 0  # seconds

GIFT_TIERS = {
    # Tier 1: 1-10 kicks — mild chaos
    (1, 10): [
        GameAction(
            name="chicken_army",
            rcon_command=f'sv_cheats 1; ent_create chicken; ent_create chicken; ent_create chicken; ent_create chicken; ent_create chicken; sv_cheats 0',
            chat_response="🐔 {user} spawned a chicken army!",
        ),
        GameAction(
            name="flash_drop",
            rcon_command=f'give weapon_flashbang',
            chat_response="💥 {user} dropped a flashbang gift!",
        ),
    ],
    # Tier 2: 11-50 kicks — real chaos
    (11, 50): [
        GameAction(
            name="gravity_drop",
            rcon_command='sv_gravity 200; echo "Low gravity for 10 seconds"',
            chat_response="🪐 {user} activated LOW GRAVITY for 10s!",
            cooldown=30,
        ),
        GameAction(
            name="smoke_rain",
            rcon_command='sv_cheats 1; ent_fire smokegrenade_projectile Kill; sv_cheats 0',
            chat_response="🌫️ {user} caused a smoke storm!",
        ),
    ],
    # Tier 3: 51-200 kicks — major disruption
    (51, 200): [
        GameAction(
            name="speed_boost",
            rcon_command=f'sv_maxspeed 600',
            chat_response="⚡ {user} activated HYPER SPEED!",
            cooldown=60,
        ),
    ],
    # Tier 4: 200+ kicks — legendary
    (200, 99999): [
        GameAction(
            name="god_mode_toggle",
            rcon_command=f'god',
            chat_response="👑 {user} toggled GOD MODE with {amount} kicks! LEGENDARY!",
            cooldown=120,
        ),
    ],
}

# Cooldown tracker
last_action_time: dict[str, float] = {}


def find_action(kicks: int) -> GameAction | None:
    """Find the appropriate action for the given kick amount."""
    import random
    for (min_k, max_k), actions in GIFT_TIERS.items():
        if min_k <= kicks <= max_k:
            return random.choice(actions)
    return None


async def execute_rcon(command: str) -> str:
    """Send an RCON command to the CS2 server."""
    try:
        from mcrcon import MCRcon  # works with Source RCON too
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            return mcr.command(command)
    except ImportError:
        logging.warning("mcrcon not installed — simulating RCON command: %s", command)
        return f"[SIM] {command}"
    except Exception as e:
        logging.error("RCON failed: %s", e)
        return f"[ERR] {e}"


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------

@app.on("kicks.gifted")
async def on_gift(event):
    """Route kick gifts to CS2 actions."""
    import time

    user = event.gifter_username
    amount = event.kicks_amount

    action = find_action(amount)
    if not action:
        await app.say(f"💚 Thanks for {amount} kicks, {user}!")
        return

    # Check cooldown
    now = time.time()
    if action.name in last_action_time:
        elapsed = now - last_action_time[action.name]
        if elapsed < action.cooldown:
            remaining = int(action.cooldown - elapsed)
            await app.say(f"⏳ {action.name} on cooldown — {remaining}s remaining")
            return

    # Execute the action
    last_action_time[action.name] = now
    result = await execute_rcon(action.rcon_command)
    logging.info("RCON executed: %s → %s", action.rcon_command, result)

    # Announce in chat
    msg = action.chat_response.format(user=user, amount=amount)
    await app.say(msg)


@app.on("chat.message.sent")
async def on_chat(event):
    """Handle chat commands."""
    msg = event.message.strip().lower()
    user = event.sender.username

    if msg == "!chaos":
        await app.say(
            "🎮 Chaos tiers: 1-10 kicks = mild | 11-50 = real | 51-200 = major | 200+ = LEGENDARY"
        )

    elif msg == "!gravity":
        await app.say("🪐 Current gravity can be changed with 11-50 kicks!")

    elif msg == "!stats":
        # TODO: integrate with GSI for live stats
        await app.say(f"📊 Stats tracking coming soon via KickForge GSI!")


# ---------------------------------------------------------------------------
# Reset handlers (auto-revert chaos after timeout)
# ---------------------------------------------------------------------------

async def reset_gravity():
    """Reset gravity after 10 seconds."""
    await asyncio.sleep(10)
    await execute_rcon("sv_gravity 800")
    logging.info("Gravity reset to normal")


async def reset_speed():
    """Reset speed after 15 seconds."""
    await asyncio.sleep(15)
    await execute_rcon("sv_maxspeed 250")
    logging.info("Speed reset to normal")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("""
    ┌─────────────────────────────────────────┐
    │   KickForge × CS2 Chaos Arena           │
    │                                         │
    │   Gift kicks → trigger in-game chaos    │
    │   Type !chaos for tier info             │
    └─────────────────────────────────────────┘
    """)
    app.run(port=8420)
