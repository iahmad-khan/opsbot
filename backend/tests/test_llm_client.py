"""Tests for LLM client safety — JSON parsing and token handling."""
from __future__ import annotations

from opsbot.agent.llm import ToolCall


class TestToolCallArgs:
    def test_valid_json_parsed(self):
        tc = ToolCall({"id": "1", "type": "function", "function": {"name": "foo", "arguments": '{"key": "value"}'}})
        assert tc.args == {"key": "value"}

    def test_invalid_json_returns_empty_dict(self):
        tc = ToolCall({"id": "1", "type": "function", "function": {"name": "foo", "arguments": "not-json{{{"}})
        assert tc.args == {}

    def test_empty_arguments_returns_empty_dict(self):
        tc = ToolCall({"id": "1", "type": "function", "function": {"name": "foo", "arguments": "{}"}})
        assert tc.args == {}

    def test_dict_arguments_returned_as_is(self):
        tc = ToolCall({"id": "1", "type": "function", "function": {"name": "foo", "arguments": {"key": "value"}}})
        assert tc.args == {"key": "value"}

    def test_missing_arguments_returns_empty_dict(self):
        tc = ToolCall({"id": "1", "type": "function", "function": {"name": "foo"}})
        assert tc.args == {}
