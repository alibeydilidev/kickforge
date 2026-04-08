"""
KickForge Overlay — real-time OBS widgets powered by WebSocket.

Widgets connect to ws://localhost:8765 and receive JSON events.
Add them as OBS Browser Sources with transparent background.
"""

from kickforge_overlay.server.ws_server import OverlayServer

__all__ = ["OverlayServer"]
