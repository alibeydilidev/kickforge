"""Tests for kickforge_gsi.adapters.cs2_gsi module."""

import os
import tempfile

import pytest
from fastapi.testclient import TestClient

from kickforge_gsi.adapters.cs2_gsi import (
    CS2GSIAdapter,
    CS2GameEvent,
    CS2PlayerState,
)


# ---------------------------------------------------------------------------
# Sample GSI payloads
# ---------------------------------------------------------------------------

BASE_PAYLOAD = {
    "player": {
        "steamid": "76561198000000000",
        "name": "TestPlayer",
        "team": "CT",
        "state": {
            "health": 100,
            "armor": 100,
            "money": 4750,
            "round_kills": 0,
            "round_totaldmg": 0,
        },
        "match_stats": {
            "kills": 5,
            "deaths": 2,
            "assists": 1,
            "mvps": 1,
        },
        "weapons": {
            "weapon_0": {"name": "weapon_knife", "state": "holstered"},
            "weapon_1": {"name": "weapon_ak47", "state": "active"},
        },
    },
    "map": {
        "team_ct": {"score": 8},
        "team_t": {"score": 6},
    },
    "round": {"phase": "live"},
}


def _payload_with(**overrides):
    """Deep-copy base and apply overrides."""
    import copy
    p = copy.deepcopy(BASE_PAYLOAD)
    for key, val in overrides.items():
        if "." in key:
            parts = key.split(".")
            obj = p
            for part in parts[:-1]:
                obj = obj[part]
            obj[parts[-1]] = val
        else:
            p[key] = val
    return p


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestCS2PlayerStateParsing:
    def test_parse_state(self):
        adapter = CS2GSIAdapter()
        state = adapter._parse_state(BASE_PAYLOAD)
        assert state.name == "TestPlayer"
        assert state.health == 100
        assert state.armor == 100
        assert state.money == 4750
        assert state.kills == 5
        assert state.deaths == 2
        assert state.current_weapon == "weapon_ak47"
        assert state.ct_score == 8
        assert state.t_score == 6

    def test_parse_empty(self):
        adapter = CS2GSIAdapter()
        state = adapter._parse_state({})
        assert state.health == 0
        assert state.name == ""


class TestCS2EventDerivation:
    def test_kill_event(self):
        prev = CS2PlayerState(round_kills=0)
        curr = CS2PlayerState(round_kills=1, current_weapon="weapon_ak47")
        events = CS2GSIAdapter._derive_events(prev, curr, {})
        types = [e.event_type for e in events]
        assert "kill" in types

    def test_death_event(self):
        prev = CS2PlayerState(health=100)
        curr = CS2PlayerState(health=0)
        events = CS2GSIAdapter._derive_events(prev, curr, {})
        types = [e.event_type for e in events]
        assert "death" in types

    def test_mvp_event(self):
        prev = CS2PlayerState(mvps=1)
        curr = CS2PlayerState(mvps=2)
        events = CS2GSIAdapter._derive_events(prev, curr, {})
        types = [e.event_type for e in events]
        assert "mvp" in types

    def test_round_start(self):
        raw = {
            "round": {"phase": "live"},
            "previously": {"round": {"phase": "freezetime"}},
        }
        events = CS2GSIAdapter._derive_events(CS2PlayerState(), CS2PlayerState(), raw)
        types = [e.event_type for e in events]
        assert "round_start" in types

    def test_round_end(self):
        raw = {
            "round": {"phase": "over", "win_team": "CT"},
            "previously": {"round": {"phase": "live"}},
        }
        events = CS2GSIAdapter._derive_events(CS2PlayerState(), CS2PlayerState(), raw)
        types = [e.event_type for e in events]
        assert "round_end" in types
        assert events[0].data["win_team"] == "CT"

    def test_bomb_planted(self):
        raw = {
            "round": {"phase": "live", "bomb": "planted"},
            "previously": {"round": {"phase": "live", "bomb": ""}},
        }
        events = CS2GSIAdapter._derive_events(CS2PlayerState(), CS2PlayerState(), raw)
        types = [e.event_type for e in events]
        assert "bomb_planted" in types

    def test_bomb_defused(self):
        raw = {
            "round": {"phase": "live", "bomb": "defused"},
            "previously": {"round": {"phase": "live", "bomb": "planted"}},
        }
        events = CS2GSIAdapter._derive_events(CS2PlayerState(), CS2PlayerState(), raw)
        types = [e.event_type for e in events]
        assert "bomb_defused" in types

    def test_no_events(self):
        prev = CS2PlayerState(health=100, round_kills=2)
        curr = CS2PlayerState(health=100, round_kills=2)
        events = CS2GSIAdapter._derive_events(prev, curr, {})
        assert events == []


class TestCS2GSIHTTPEndpoint:
    def test_gsi_post(self):
        adapter = CS2GSIAdapter()
        received = []

        @adapter.on_event
        async def cb(event):
            received.append(event.event_type)

        client = TestClient(adapter.app)
        resp = client.post("/", json=BASE_PAYLOAD)
        assert resp.status_code == 200

    def test_state_endpoint(self):
        adapter = CS2GSIAdapter()
        client = TestClient(adapter.app)
        # Post data first
        client.post("/", json=BASE_PAYLOAD)
        resp = client.get("/state")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "TestPlayer"
        assert data["health"] == 100

    def test_invalid_json(self):
        adapter = CS2GSIAdapter()
        client = TestClient(adapter.app)
        resp = client.post("/", content=b"not json")
        assert resp.status_code == 400


class TestCS2GSIConfigGenerator:
    def test_generate(self):
        fd, path = tempfile.mkstemp(suffix=".cfg")
        os.close(fd)
        try:
            result = CS2GSIAdapter.generate_config(path, uri="http://localhost:3000")
            assert os.path.isfile(result)
            content = open(result).read()
            assert "kickforge_gsi" in content
            assert "http://localhost:3000" in content
            assert '"player_state"' in content
        finally:
            os.unlink(path)
