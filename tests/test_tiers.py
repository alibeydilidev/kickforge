"""Tests for kickforge_gsi.tiers module."""

import os
import tempfile

import pytest

from kickforge_gsi.tiers import (
    TierEngine,
    TierConfig,
    ActionDef,
    TierDef,
    TierMatch,
    parse_tier_config,
    _expand_template,
)


SAMPLE_CONFIG = {
    "game": "minecraft",
    "actions": {
        "chicken_army": {
            "command": "summon chicken ~ ~2 ~ {CustomName:'\"{{user}}\"'}",
            "repeat": 5,
            "chat_response": "{{user}} spawned a chicken army!",
        },
        "creeper_wave": {
            "command": "summon creeper ~ ~5 ~",
            "repeat": 3,
            "chat_response": "{{user}} unleashed creepers!",
        },
        "ender_dragon": {
            "command": "summon ender_dragon ~ ~20 ~",
            "repeat": 1,
            "chat_response": "{{user}} SUMMONED THE ENDER DRAGON! ({{amount}} kicks)",
        },
        "random_mob": {
            "command": "summon zombie ~ ~2 ~",
            "repeat": 1,
            "chat_response": "{{user}} spawned a zombie!",
        },
    },
    "tiers": [
        {"range": [1, 10], "actions": ["chicken_army"], "cooldown": 10},
        {"range": [11, 50], "actions": ["creeper_wave"], "cooldown": 30},
        {"range": [200, 99999], "actions": ["ender_dragon"], "cooldown": 120},
    ],
    "chat_commands": {
        "!spawn": {
            "action": "random_mob",
            "cooldown": 30,
            "permission": "everyone",
        }
    },
}


class TestExpandTemplate:
    def test_user(self):
        assert _expand_template("hello {{user}}", user="alice") == "hello alice"

    def test_amount(self):
        assert _expand_template("{{amount}} kicks", amount=42) == "42 kicks"

    def test_both(self):
        r = _expand_template("{{user}} sent {{amount}}", user="bob", amount=100)
        assert r == "bob sent 100"

    def test_no_vars(self):
        assert _expand_template("plain text") == "plain text"


class TestParseTierConfig:
    def test_parse(self):
        cfg = parse_tier_config(SAMPLE_CONFIG)
        assert cfg.game == "minecraft"
        assert "chicken_army" in cfg.actions
        assert len(cfg.tiers) == 3
        assert "!spawn" in cfg.chat_commands

    def test_action_fields(self):
        cfg = parse_tier_config(SAMPLE_CONFIG)
        ca = cfg.actions["chicken_army"]
        assert ca.repeat == 5
        assert "{{user}}" in ca.command

    def test_tier_range(self):
        cfg = parse_tier_config(SAMPLE_CONFIG)
        t = cfg.tiers[0]
        assert t.range_min == 1
        assert t.range_max == 10

    def test_empty_config(self):
        cfg = parse_tier_config({})
        assert cfg.game == ""
        assert cfg.actions == {}
        assert cfg.tiers == []


class TestTierEngine:
    @pytest.fixture
    def engine(self):
        return TierEngine.from_dict(SAMPLE_CONFIG)

    def test_resolve_low_tier(self, engine):
        match = engine.resolve(amount=5, user="alice")
        assert match is not None
        assert "chicken_army" in match.action_names
        assert len(match.commands) == 5  # repeat=5
        assert "alice" in match.commands[0]
        assert "alice spawned a chicken army!" in match.chat_responses

    def test_resolve_mid_tier(self, engine):
        match = engine.resolve(amount=25, user="bob")
        assert match is not None
        assert "creeper_wave" in match.action_names
        assert len(match.commands) == 3  # repeat=3

    def test_resolve_high_tier(self, engine):
        match = engine.resolve(amount=500, user="whale")
        assert match is not None
        assert "ender_dragon" in match.action_names
        assert "500 kicks" in match.chat_responses[0]

    def test_resolve_no_match(self, engine):
        # Gap between 50 and 200 has no tier
        match = engine.resolve(amount=100, user="alice")
        assert match is None

    def test_resolve_boundary(self, engine):
        match = engine.resolve(amount=1, user="x")
        assert match is not None
        match = engine.resolve(amount=10, user="x")
        assert match is not None

    def test_resolve_chat_command(self, engine):
        cmd = engine.resolve_chat_command("!spawn")
        assert cmd is not None
        assert cmd.action == "random_mob"
        assert cmd.cooldown == 30

    def test_resolve_unknown_chat_command(self, engine):
        assert engine.resolve_chat_command("!unknown") is None

    def test_from_yaml(self):
        fd, path = tempfile.mkstemp(suffix=".yaml")
        os.close(fd)
        try:
            import yaml
            with open(path, "w") as f:
                yaml.dump(SAMPLE_CONFIG, f)
            engine = TierEngine.from_yaml(path)
            match = engine.resolve(amount=5, user="test")
            assert match is not None
        finally:
            os.unlink(path)

    def test_cooldown_value(self, engine):
        match = engine.resolve(amount=5, user="x")
        assert match is not None
        assert match.cooldown == 10.0
