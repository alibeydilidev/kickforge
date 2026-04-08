"""Shared fixtures for KickForge tests."""

import pytest


@pytest.fixture
def sample_chat_payload():
    return {
        "message_id": "msg-123",
        "content": "!hello world",
        "broadcaster_user_id": 99999,
        "sender": {
            "user_id": 12345,
            "username": "testuser",
            "is_subscriber": True,
            "badges": ["subscriber"],
        },
        "replied_to": None,
    }


@pytest.fixture
def sample_follow_payload():
    return {
        "username": "newfollower",
        "user_id": 67890,
        "broadcaster_user_id": 99999,
    }


@pytest.fixture
def sample_gift_payload():
    return {
        "gifter": {
            "username": "generousgifter",
            "user_id": 11111,
        },
        "amount": 50,
        "broadcaster_user_id": 99999,
    }


@pytest.fixture
def sample_sub_payload():
    return {
        "_event_type": "channel.subscription.new",
        "username": "newsub",
        "user_id": 22222,
        "broadcaster_user_id": 99999,
        "months": 1,
        "is_gift": False,
    }


@pytest.fixture
def sample_livestream_payload():
    return {
        "is_live": True,
        "title": "Playing CS2 with viewers!",
        "broadcaster_user_id": 99999,
    }
