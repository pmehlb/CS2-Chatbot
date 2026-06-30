# tests/test_base_contract.py
import asyncio
import os
import sys

# Make the application package layout (src/) importable when run from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from areas.base import ChatArea


def test_chatarea_does_not_consume_events_by_default():
    assert ChatArea.consumes_events is False


def test_generate_event_returns_none_by_default():
    area = ChatArea()
    result = asyncio.run(area.generate_event(object(), object()))
    assert result is None
