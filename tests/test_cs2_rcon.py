"""Tests for kickforge_gsi.adapters.cs2_rcon packet encoding/decoding."""

import struct

import pytest

from kickforge_gsi.adapters.cs2_rcon import (
    _pack_rcon_packet,
    _unpack_rcon_packet,
    SERVERDATA_AUTH,
    SERVERDATA_EXECCOMMAND,
    SERVERDATA_RESPONSE_VALUE,
)


def _strip_size_prefix(packet: bytes) -> bytes:
    """Remove the 4-byte size prefix, returning the inner data."""
    return packet[4:]


class TestRCONPackets:
    def test_pack_and_unpack_roundtrip(self):
        packet = _pack_rcon_packet(1, SERVERDATA_EXECCOMMAND, "status")
        inner = _strip_size_prefix(packet)
        rid, ptype, body = _unpack_rcon_packet(inner)
        assert rid == 1
        assert ptype == SERVERDATA_EXECCOMMAND
        assert body == "status"

    def test_pack_auth_packet(self):
        packet = _pack_rcon_packet(42, SERVERDATA_AUTH, "mypassword")
        inner = _strip_size_prefix(packet)
        rid, ptype, body = _unpack_rcon_packet(inner)
        assert rid == 42
        assert ptype == SERVERDATA_AUTH
        assert body == "mypassword"

    def test_pack_empty_body(self):
        packet = _pack_rcon_packet(1, SERVERDATA_RESPONSE_VALUE, "")
        inner = _strip_size_prefix(packet)
        rid, ptype, body = _unpack_rcon_packet(inner)
        assert rid == 1
        assert body == ""

    def test_unpack_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            _unpack_rcon_packet(b"\x00\x00")

    def test_packet_structure(self):
        """Verify little-endian int32 framing."""
        packet = _pack_rcon_packet(7, SERVERDATA_EXECCOMMAND, "say hello")
        # First 4 bytes: size (little-endian int32)
        size = struct.unpack("<i", packet[0:4])[0]
        # Next 4 bytes: request_id
        rid = struct.unpack("<i", packet[4:8])[0]
        # Next 4 bytes: type
        ptype = struct.unpack("<i", packet[8:12])[0]
        assert rid == 7
        assert ptype == SERVERDATA_EXECCOMMAND
        # Body starts at byte 12
        body = packet[12:].rstrip(b"\x00")
        assert body == b"say hello"
        # Size should be id(4) + type(4) + body + 2 null terminators
        assert size == 4 + 4 + len(b"say hello") + 2

    def test_unicode_body(self):
        packet = _pack_rcon_packet(1, SERVERDATA_EXECCOMMAND, "say merhaba")
        inner = _strip_size_prefix(packet)
        rid, ptype, body = _unpack_rcon_packet(inner)
        assert body == "say merhaba"

    def test_size_prefix_correctness(self):
        """Size field should equal length of everything after it."""
        packet = _pack_rcon_packet(1, SERVERDATA_EXECCOMMAND, "test")
        (size,) = struct.unpack("<i", packet[:4])
        assert size == len(packet) - 4
