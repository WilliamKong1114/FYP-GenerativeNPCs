import pytest
import socket
import json
import threading
from unittest.mock import MagicMock, patch
from unity_comm import UnityClient

class MockSocket:
    def __init__(self, response_data=b"{\"status\": \"ok\"}\n"):
        self.sent_data = b""
        self.response_data = response_data
        self.connected = True
        self.timeout = None
        self.options = {}

    def connect(self, addr):
        pass

    def sendall(self, data):
        self.sent_data += data

    def recv(self, bufsize):
        if not self.connected:
            return b""
        if self.response_data:
            chunk = self.response_data[:bufsize]
            self.response_data = self.response_data[bufsize:]
            return chunk
        return b""

    def close(self):
        self.connected = False

    def setsockopt(self, level, optname, value):
        self.options[(level, optname)] = value
        
    def settimeout(self, timeout):
        self.timeout = timeout

@pytest.fixture
def mock_socket_create():
    with patch("socket.create_connection") as mock_create:
        yield mock_create

def test_send_command_success(mock_socket_create):
    mock_sock = MockSocket(response_data=b'{"status":"success"}')
    mock_socket_create.return_value = mock_sock
    
    client = UnityClient()
    response = client.send_command({"action": "jump"}, agent_id="agent1", wait_for_response=True)
    
    # This assertion will fail if response is empty (current bug)
    assert response is not None
    if isinstance(response, str):
        response = json.loads(response)
    assert response == {"status": "success"}

def test_send_command_accumulates_data(mock_socket_create):
    pass

def test_send_command_no_wait(mock_socket_create):
    mock_sock = MockSocket()
    mock_socket_create.return_value = mock_sock
    
    client = UnityClient()
    client.send_command({"action": "walk"}, agent_id="agent1", wait_for_response=False)
    
    assert b"walk" in mock_sock.sent_data

def test_send_command_retry_on_broken_pipe(mock_socket_create):
    bad_sock = MockSocket()
    bad_sock.sendall = MagicMock(side_effect=BrokenPipeError("Pipe broken"))
    
    good_sock = MockSocket(response_data=b'{"status":"recovered"}')
    
    # Mock create_connection to return good_sock when called (for the retry)
    mock_socket_create.return_value = good_sock
    
    client = UnityClient()
    # Inject bad socket acting as "stale" connection
    client._connections["agent1"] = bad_sock
    
    response = client.send_command({"action": "retry_test"}, agent_id="agent1", wait_for_response=True)
    
    assert response == {"status": "recovered"}
    assert client._connections["agent1"] == good_sock


def test_handle_incoming_request_conversation_is_non_blocking():
    client = UnityClient()
    client.wait_for_conv_finish = MagicMock()

    agent_executions = {
        "Samson": {"is_chatting": True},
        "Jimmy": {"is_chatting": True},
    }

    cmd = {"action": "request_conversation", "agent": "Samson", "partner": "Jimmy"}
    client.handle_incoming_command(cmd, agent_executions)

    client.wait_for_conv_finish.assert_not_called()


def test_handle_incoming_request_conversation_missing_agent_is_safe():
    client = UnityClient()
    client.wait_for_conv_finish = MagicMock()

    agent_executions = {
        "Samson": {"is_chatting": True},
    }

    cmd = {"action": "request_conversation", "agent": "Samson", "partner": "Jimmy"}
    client.handle_incoming_command(cmd, agent_executions)

    client.wait_for_conv_finish.assert_not_called()


def test_handle_incoming_conversation_finished_is_non_blocking():
    client = UnityClient()
    client.wait_for_conv_finish = MagicMock()

    agent_executions = {
        "Samson": {"is_chatting": True},
    }

    cmd = {"action": "conversation_finished", "agent": "Samson"}
    client.handle_incoming_command(cmd, agent_executions)

    client.wait_for_conv_finish.assert_not_called()


def test_update_dialogue_includes_session_id(mock_socket_create):
    mock_sock = MockSocket()
    mock_socket_create.return_value = mock_sock

    client = UnityClient()
    client.update_dialogue("Samson", ["Samson: \"Hello\""], session_id="sess-123")

    payload = mock_sock.sent_data.decode("utf-8")
    assert '"action":"update_dialogue"' in payload
    assert '"session_id":"sess-123"' in payload


def test_handle_incoming_request_conversation_returns_exact_pair_dialogue():
    client = UnityClient()
    client.update_dialogue = MagicMock()

    memory_manager = MagicMock()
    memory_manager.get_recent_conversation_logs_between.return_value = [
        (
            "log-1",
            '["Samson", "Jimmy"]',
            'Samson: "Need help at workshop"; Jimmy: "Yes, I will join."',
            "Workshop",
            "2026-03-15T12:00:00",
            123456,
        )
    ]

    client.conv_manager = MagicMock(memory_manager=memory_manager)

    agent_executions = {
        "Samson": {"is_chatting": False, "is_busy_until": 0},
        "Jimmy": {"is_chatting": False, "is_busy_until": 0},
        "Lily": {"is_chatting": False, "is_busy_until": 0},
    }

    cmd = {
        "action": "request_conversation",
        "agent": "Samson",
        "partner": "Jimmy",
        "session_id": "sess-a",
    }
    client.handle_incoming_command(cmd, agent_executions)

    memory_manager.get_recent_conversation_logs_between.assert_called_once_with("Samson", "Jimmy", limit=1)
    client.update_dialogue.assert_called_once_with(
        "Samson",
        ['Samson: "Need help at workshop"', 'Jimmy: "Yes, I will join."'],
        session_id="sess-a",
    )


def test_handle_incoming_request_conversation_no_pair_log_sends_notice():
    client = UnityClient()
    client.update_dialogue = MagicMock()

    memory_manager = MagicMock()
    memory_manager.get_recent_conversation_logs_between.return_value = []
    client.conv_manager = MagicMock(memory_manager=memory_manager)

    agent_executions = {
        "Samson": {"is_chatting": False, "is_busy_until": 0},
        "Jimmy": {"is_chatting": False, "is_busy_until": 0},
    }

    cmd = {
        "action": "request_conversation",
        "agent": "Samson",
        "partner": "Jimmy",
        "session_id": "sess-empty",
    }
    client.handle_incoming_command(cmd, agent_executions)

    client.update_dialogue.assert_called_once()
    args, kwargs = client.update_dialogue.call_args
    assert args[0] == "Samson"
    assert "No recorded conversation found yet" in args[1][0]
    assert kwargs["session_id"] == "sess-empty"
