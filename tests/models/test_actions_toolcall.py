from unittest.mock import MagicMock

import pytest

from mr_deed import Tool
from mr_deed.exceptions import FormatError
from mr_deed.models.utils.actions_toolcall import (
    BASH_TOOL,
    format_toolcall_observation_messages,
    parse_toolcall_actions,
    tool_schema,
)
from mr_deed.models.utils.actions_toolcall_response import parse_toolcall_actions_response
from mr_deed.models.utils.actions_toolcall_response import tool_schema as response_tool_schema

ADD_TOOL = Tool(
    "add",
    "Add two numbers",
    {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]},
    lambda args: {"output": str(args["a"] + args["b"])},
)


def _tool_call(name: str, arguments: str, call_id: str = "call_1"):
    tool_call = MagicMock()
    tool_call.function.name = name
    tool_call.function.arguments = arguments
    tool_call.id = call_id
    return tool_call


class TestParseToolcallActions:
    def test_empty_tool_calls_raises_format_error(self):
        with pytest.raises(FormatError) as exc_info:
            parse_toolcall_actions([], format_error_template="{{ error }}")
        assert "No tool calls found" in exc_info.value.messages[0]["content"]

    def test_none_tool_calls_raises_format_error(self):
        with pytest.raises(FormatError) as exc_info:
            parse_toolcall_actions(None, format_error_template="{{ error }}")
        assert "No tool calls found" in exc_info.value.messages[0]["content"]

    def test_template_kwargs_exposed_to_format_error_template(self):
        template = "{% if finish_reason == 'length' %}cut off{% else %}{{ error }}{% endif %}"
        # no-tool-call path
        with pytest.raises(FormatError) as exc:
            parse_toolcall_actions([], format_error_template=template, template_kwargs={"finish_reason": "length"})
        assert exc.value.messages[0]["content"] == "cut off"
        # bad-arguments path
        bad = MagicMock()
        bad.function.name = "bash"
        bad.function.arguments = "{not json"
        bad.id = "call_1"
        with pytest.raises(FormatError) as exc:
            parse_toolcall_actions([bad], format_error_template=template, template_kwargs={"finish_reason": "length"})
        assert exc.value.messages[0]["content"] == "cut off"

    def test_valid_bash_tool_call(self):
        tool_call = MagicMock()
        tool_call.function.name = "bash"
        tool_call.function.arguments = '{"command": "echo hello"}'
        tool_call.id = "call_123"
        assert parse_toolcall_actions([tool_call], format_error_template="{{ error }}") == [
            {
                "name": "bash",
                "arguments": {"command": "echo hello"},
                "command": "echo hello",
                "tool_call_id": "call_123",
            }
        ]

    def test_multiple_valid_tool_calls(self):
        calls = []
        for i in range(3):
            tc = MagicMock()
            tc.function.name = "bash"
            tc.function.arguments = f'{{"command": "cmd{i}"}}'
            tc.id = f"call_{i}"
            calls.append(tc)
        result = parse_toolcall_actions(calls, format_error_template="{{ error }}")
        assert len(result) == 3
        assert result[0] == {
            "name": "bash",
            "arguments": {"command": "cmd0"},
            "command": "cmd0",
            "tool_call_id": "call_0",
        }
        assert result[2] == {
            "name": "bash",
            "arguments": {"command": "cmd2"},
            "command": "cmd2",
            "tool_call_id": "call_2",
        }

    def test_unknown_tool_raises_format_error(self):
        tool_call = MagicMock()
        tool_call.function.name = "unknown_tool"
        tool_call.function.arguments = '{"command": "test"}'
        tool_call.id = "call_1"
        with pytest.raises(FormatError) as exc_info:
            parse_toolcall_actions([tool_call], format_error_template="{{ error }}")
        assert "Unknown tool 'unknown_tool'" in exc_info.value.messages[0]["content"]

    def test_invalid_json_raises_format_error(self):
        tool_call = MagicMock()
        tool_call.function.name = "bash"
        tool_call.function.arguments = "not valid json"
        tool_call.id = "call_1"
        with pytest.raises(FormatError) as exc_info:
            parse_toolcall_actions([tool_call], format_error_template="{{ error }}")
        assert "Error parsing tool call arguments" in exc_info.value.messages[0]["content"]

    def test_missing_command_raises_format_error(self):
        tool_call = MagicMock()
        tool_call.function.name = "bash"
        tool_call.function.arguments = '{"other_arg": "value"}'
        tool_call.id = "call_1"
        with pytest.raises(FormatError) as exc_info:
            parse_toolcall_actions([tool_call], format_error_template="{{ error }}")
        assert "Missing 'command' argument" in exc_info.value.messages[0]["content"]


class TestFormatToolcallObservationMessages:
    def test_basic_formatting(self):
        actions = [{"command": "echo test", "tool_call_id": "call_1"}]
        outputs = [{"output": "test output", "returncode": 0}]
        result = format_toolcall_observation_messages(
            actions=actions, outputs=outputs, observation_template="{{ output.output }}"
        )
        assert len(result) == 1
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "call_1"
        assert result[0]["content"] == "test output"
        assert result[0]["extra"]["returncode"] == 0

    def test_multiple_outputs(self):
        actions = [
            {"command": "cmd1", "tool_call_id": "call_1"},
            {"command": "cmd2", "tool_call_id": "call_2"},
        ]
        outputs = [{"output": "out1", "returncode": 0}, {"output": "out2", "returncode": 1}]
        result = format_toolcall_observation_messages(
            actions=actions, outputs=outputs, observation_template="{{ output.output }}"
        )
        assert len(result) == 2
        assert result[0]["tool_call_id"] == "call_1"
        assert result[0]["content"] == "out1"
        assert result[1]["tool_call_id"] == "call_2"
        assert result[1]["content"] == "out2"

    def test_with_template_vars(self):
        actions = [{"command": "test", "tool_call_id": "call_1"}]
        outputs = [{"output": "result", "returncode": 0}]
        result = format_toolcall_observation_messages(
            actions=actions,
            outputs=outputs,
            observation_template="{{ output.output }} - {{ custom_var }}",
            template_vars={"custom_var": "extra_info"},
        )
        assert result[0]["content"] == "result - extra_info"

    def test_exception_info_in_extra(self):
        actions = [{"command": "test", "tool_call_id": "call_1"}]
        outputs = [{"output": "", "returncode": 1, "exception_info": "Error occurred", "extra": {"detail": "more"}}]
        result = format_toolcall_observation_messages(
            actions=actions, outputs=outputs, observation_template="{{ output.output }}"
        )
        assert result[0]["extra"]["exception_info"] == "Error occurred"
        assert result[0]["extra"]["detail"] == "more"


class TestBashTool:
    def test_bash_tool_structure(self):
        assert BASH_TOOL["type"] == "function"
        assert BASH_TOOL["function"]["name"] == "bash"
        assert "command" in BASH_TOOL["function"]["parameters"]["properties"]
        assert "command" in BASH_TOOL["function"]["parameters"]["required"]


class TestHostTools:
    def test_tool_schemas(self):
        assert tool_schema(ADD_TOOL) == {
            "type": "function",
            "function": {"name": "add", "description": "Add two numbers", "parameters": ADD_TOOL.parameters},
        }
        assert response_tool_schema(ADD_TOOL) == {
            "type": "function",
            "name": "add",
            "description": "Add two numbers",
            "parameters": ADD_TOOL.parameters,
        }

    def test_host_tool_call_is_parsed_with_name_and_arguments(self):
        expected = [{"name": "add", "arguments": {"a": 1, "b": 2}, "tool_call_id": "call_1"}]
        tool_call = _tool_call("add", '{"a": 1, "b": 2}')
        assert parse_toolcall_actions([tool_call], format_error_template="{{ error }}", tools=[ADD_TOOL]) == expected
        item = {"type": "function_call", "call_id": "call_1", "name": "add", "arguments": '{"a": 1, "b": 2}'}
        assert (
            parse_toolcall_actions_response([item], format_error_template="{{ error }}", tools=[ADD_TOOL]) == expected
        )

    def test_tool_arguments_may_be_called_name_or_tool_call_id(self):
        """Regression test: arguments must not share a namespace with the action's own keys."""
        tool = Tool("create", "Create", {"type": "object", "properties": {"name": {"type": "string"}}}, lambda a: a)
        tool_call = _tool_call("create", '{"name": "engineer", "tool_call_id": "x"}', call_id="c1")
        assert parse_toolcall_actions([tool_call], format_error_template="{{ error }}", tools=[tool]) == [
            {"name": "create", "arguments": {"name": "engineer", "tool_call_id": "x"}, "tool_call_id": "c1"}
        ]

    def test_host_tool_is_unknown_unless_registered(self):
        with pytest.raises(FormatError) as exc:
            parse_toolcall_actions([_tool_call("add", '{"a": 1, "b": 2}')], format_error_template="{{ error }}")
        assert "Unknown tool 'add'" in exc.value.messages[0]["content"]

    @pytest.mark.parametrize(
        ("arguments", "error"),
        [
            ('{"a": 1}', "Missing 'b' argument in add tool call."),
            ("{}", "Missing 'a', 'b' argument in add tool call."),
            ("[1, 2]", "Tool call arguments must be a JSON object.Missing 'a', 'b' argument in add tool call."),
        ],
    )
    def test_invalid_host_tool_arguments_raise_format_error(self, arguments, error):
        with pytest.raises(FormatError) as exc:
            parse_toolcall_actions(
                [_tool_call("add", arguments)], format_error_template="{{ error }}", tools=[ADD_TOOL]
            )
        assert exc.value.messages[0]["content"] == error
        item = {"type": "function_call", "call_id": "call_1", "name": "add", "arguments": arguments}
        with pytest.raises(FormatError) as exc:
            parse_toolcall_actions_response([item], format_error_template="{{ error }}", tools=[ADD_TOOL])
        assert exc.value.messages[0]["content"][0]["text"] == error
