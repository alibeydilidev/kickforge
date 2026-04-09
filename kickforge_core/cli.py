"""KickForge CLI — quick-start commands."""

from __future__ import annotations

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="kickforge",
        description="KickForge — interactive streaming toolkit for Kick.com",
    )
    sub = parser.add_subparsers(dest="command")

    # kickforge init
    init_cmd = sub.add_parser("init", help="Create a starter bot project")
    init_cmd.add_argument("name", nargs="?", default="my-kick-bot", help="Project folder name")

    # kickforge run
    run_cmd = sub.add_parser("run", help="Run a KickForge app")
    run_cmd.add_argument("file", help="Python file to run")
    run_cmd.add_argument("--port", type=int, default=8420, help="Webhook port")

    # kickforge check
    sub.add_parser("check", help="Verify Kick API credentials")

    # kickforge auth
    auth_cmd = sub.add_parser(
        "auth",
        help="OAuth user-token flow (one-time, for chat sending)",
    )
    auth_cmd.add_argument(
        "--port", type=int, default=8421, help="Local OAuth callback port (default 8421)"
    )
    auth_cmd.add_argument(
        "--no-browser", action="store_true", help="Don't auto-open the browser"
    )

    args = parser.parse_args()

    if args.command == "init":
        _init_project(args.name)
    elif args.command == "check":
        _check_credentials()
    elif args.command == "run":
        _run_app(args.file, args.port)
    elif args.command == "auth":
        _auth_flow(port=args.port, open_browser=not args.no_browser)
    else:
        parser.print_help()


def _init_project(name: str) -> None:
    """Scaffold a new KickForge bot project."""
    import os

    os.makedirs(name, exist_ok=True)

    # Create config
    config_content = """# KickForge configuration
# Get your credentials at https://kick.com/settings/developer

kick:
  client_id: "YOUR_CLIENT_ID"
  client_secret: "YOUR_CLIENT_SECRET"
  channel: "YOUR_CHANNEL_SLUG"

webhook:
  port: 8420
  path: "/webhook"

bot:
  prefix: "!"
  commands:
    schedule:
      response: "Stream schedule: Mon-Wed-Fri at 9PM"
      cooldown: 30
    socials:
      response: "Follow me everywhere: linktr.ee/yourchannel"
      cooldown: 60

  timed_messages:
    - message: "Don't forget to follow! Type !schedule for stream times."
      interval: 900

  moderation:
    max_caps_percent: 70
    blocked_words: []
    links_allowed: false
    link_whitelist: ["kick.com", "youtube.com"]
"""
    with open(os.path.join(name, "config.yaml"), "w") as f:
        f.write(config_content)

    # Create main bot file
    bot_content = '''"""My KickForge bot — edit this file to customize!"""

import yaml
from kickforge_core import KickApp

# Load config
with open("config.yaml") as f:
    config = yaml.safe_load(f)

app = KickApp(
    client_id=config["kick"]["client_id"],
    client_secret=config["kick"]["client_secret"],
)


@app.on("chat.message.sent")
async def on_chat(event):
    """Handle chat messages and commands."""
    msg = event.message.strip()
    username = event.sender.username

    # Simple command handler
    if msg.startswith("!"):
        cmd = msg.split()[0][1:].lower()
        commands = config.get("bot", {}).get("commands", {})
        if cmd in commands:
            await app.say(commands[cmd]["response"])

    # Welcome new chatters
    elif "hello" in msg.lower() or "selam" in msg.lower():
        await app.say(f"Welcome {username}! Type !schedule for stream times.")


@app.on("channel.followed")
async def on_follow(event):
    """Welcome new followers."""
    await app.say(f"Welcome to the family, {event.follower_username}! 🎉")


@app.on("kicks.gifted")
async def on_gift(event):
    """Thank gifters."""
    await app.say(
        f"🔥 {event.gifter_username} just sent {event.kicks_amount} kicks! Thank you!"
    )


@app.on("channel.subscription.new")
async def on_sub(event):
    """Celebrate new subscribers."""
    await app.say(
        f"⭐ {event.subscriber_username} just subscribed! Welcome to the squad!"
    )


if __name__ == "__main__":
    app.run(port=config["webhook"]["port"])
'''
    with open(os.path.join(name, "bot.py"), "w") as f:
        f.write(bot_content)

    # Create .gitignore
    gitignore = """__pycache__/
*.pyc
.env
config.yaml
"""
    with open(os.path.join(name, ".gitignore"), "w") as f:
        f.write(gitignore)

    print(f"""
✅ KickForge project created: ./{name}/

   Files:
     config.yaml   — your Kick credentials & bot settings
     bot.py        — main bot logic (edit this!)
     .gitignore    — keeps secrets out of git

   Next steps:
     1. cd {name}
     2. Edit config.yaml with your Kick Dev credentials
     3. python bot.py
     4. Expose your webhook with: ngrok http 8420

   Docs: https://kickforge.dev/docs
""")


def _check_credentials() -> None:
    """Quick credential verification."""
    import asyncio
    import os

    try:
        import yaml

        if os.path.exists("config.yaml"):
            with open("config.yaml") as f:
                config = yaml.safe_load(f)
            client_id = config.get("kick", {}).get("client_id", "")
            client_secret = config.get("kick", {}).get("client_secret", "")
        else:
            client_id = os.getenv("KICK_CLIENT_ID", "")
            client_secret = os.getenv("KICK_CLIENT_SECRET", "")

        if not client_id or client_id == "YOUR_CLIENT_ID":
            print("❌ No credentials found. Edit config.yaml or set KICK_CLIENT_ID env var.")
            return

        from kickforge_core.auth import KickAuth

        auth = KickAuth(client_id=client_id, client_secret=client_secret)

        async def verify():
            try:
                token = await auth.get_app_token()
                print(f"✅ Credentials valid! Token obtained (first 20 chars): {token[:20]}...")
            except Exception as e:
                print(f"❌ Auth failed: {e}")
            finally:
                await auth.close()

        asyncio.run(verify())

    except ImportError:
        print("❌ Missing dependency: pip install pyyaml")


def _run_app(file: str, port: int) -> None:
    """Run a KickForge app file."""
    import subprocess

    subprocess.run([sys.executable, file], check=False)


def _auth_flow(port: int = 8421, open_browser: bool = True) -> None:
    """
    Run the OAuth authorization-code flow to obtain a user access token.

    Reads KICK_CLIENT_ID and KICK_CLIENT_SECRET from .env, spins up a
    local callback server on ``port``, opens the user's browser, and
    saves the resulting token to ~/.kickforge/tokens.json.
    """
    import asyncio
    import os

    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    client_id = os.getenv("KICK_CLIENT_ID", "")
    client_secret = os.getenv("KICK_CLIENT_SECRET", "")

    if not client_id or not client_secret:
        print("Error: KICK_CLIENT_ID and KICK_CLIENT_SECRET must be set in your .env file.")
        print("Get them at https://kick.com/settings/developer")
        sys.exit(1)

    from kickforge_core.auth import KickAuth, TOKEN_FILE
    from kickforge_core.oauth_server import OAuthServer

    auth = KickAuth(client_id=client_id, client_secret=client_secret)
    server = OAuthServer(auth=auth, port=port)

    print("=" * 60)
    print("KickForge OAuth Flow")
    print("=" * 60)
    print(f"Callback URL: {server.redirect_uri}")
    print()
    print("IMPORTANT: This callback URL must be registered in your")
    print("Kick Developer App at https://kick.com/settings/developer")
    print("under 'Redirect URIs'.")
    print("=" * 60)

    async def run() -> None:
        try:
            success = await server.run(open_browser=open_browser)
        finally:
            await auth.close()

        if success:
            print()
            print(f"Token saved to {TOKEN_FILE}")
            print("Your bot can now send chat messages.")
            print()
            print("Next: python examples/minimal_bot.py")
        else:
            print()
            print(f"OAuth failed: {server.error}")
            sys.exit(1)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(1)


if __name__ == "__main__":
    main()
