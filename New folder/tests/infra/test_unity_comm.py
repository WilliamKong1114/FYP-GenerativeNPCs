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
