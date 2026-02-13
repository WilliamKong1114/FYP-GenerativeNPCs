import socket
import json
import threading
from time import time

class UnityClient:    
    def __init__(self, host: str = "127.0.0.1", port: int = 5005, timeout: float = 2.0, default_agent_id: str = None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.default_agent_id = default_agent_id
        self._connections = {}
        self._connection_lock = threading.Lock()
        
    def _get_connection(self, agent_id: str):
        with self._connection_lock:
            if agent_id not in self._connections or self._connections[agent_id] is None:
                try:
                    sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    self._connections[agent_id] = sock
                    print(f"[C] Created connection for {agent_id}")
                except Exception as e:
                    print(f"[C] Failed to connect {agent_id}: {e}")
                    return None
            return self._connections[agent_id]
    
    def _close_connection(self, agent_id: str):
        with self._connection_lock:
            if agent_id in self._connections and self._connections[agent_id]:
                self._connections[agent_id].close()
                self._connections[agent_id] = None

    def send_command(self, cmd: dict, agent_id: str = None, wait_for_response: bool = False, retry: bool = True):
        payload = json.dumps(cmd, separators=(',', ':')) + "\n"
        
        for attempt in range(2 if retry else 1):
            sock = None
            sock = self._get_connection(agent_id)
            if sock is None:
                raise ConnectionError(f"No connection for {agent_id}")
            
            sock.settimeout(self.timeout)
            sock.sendall(payload.encode('utf-8'))
            response = None
            if wait_for_response:
                response_data = b""
                while True:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break       #close connection
                    response_data += chunk
                    if b"\n" in response_data:
                        break       #end of message
                if response_data:
                    response = json.loads(response_data.decode('utf-8').strip())
            return response
        
    def close(self):
        with self._connection_lock:
            for agent_id, sock in self._connections.items():
                if sock:
                    sock.close()
                    print(f"[C] Closed connection for {agent_id}")
            self._connections.clear()

    """ def get_state(self):
        return self.send_command({"action": "get_state"}, wait_for_response=True)"""

    def build_and_send(self, action: str, agent_id: str = None, target: str = None, content: str = None, wait_for_response: bool = False, **kwargs):
        cmd = {"action": action, **kwargs}
        if agent_id:
            cmd["agent"] = agent_id
        if target:
            cmd["target"] = target
        if content:
            cmd["content"] = content
        self.send_command(cmd, agent_id=agent_id, wait_for_response=wait_for_response)

    def move_to(self, target: str, content: str = None, description: str = None, agent_id: str = None, wait_for_response: bool = False):
        self.build_and_send("move_to", agent_id, target=target, content=content, description=description)
        if wait_for_response:
            return self._wait_for_arrival(agent_id, timeout=10.0)
        return True

    def show_dialogue(self, content: str, agent_id: str = None):
        self.build_and_send("show_dialogue", agent_id, content=content)

    def interact(self, target: str, method: str, parameters: dict = None, agent_id: str = None):
        kwargs = {"target": target, "method": method}
        if parameters:
            kwargs.update(parameters)
        return self.build_and_send("interact", agent_id, wait_for_response=True, **kwargs)

    def stop(self, agent_id: str = None):
        self.build_and_send("stop", agent_id)

    def _wait_for_arrival(self, agent_id: str, timeout: float = 10.0):
        sock = self._get_connection(agent_id)
        if not sock:
            return False
        
        start_time = time.time()
        buffer = b""
        while time.time() - start_time < timeout:
            try:
                sock.settimeout(1.0)  # Short timeout for polling
                chunk = sock.recv(1024)
                if not chunk:
                    break
                buffer += chunk
                messages = buffer.split(b"\n")
                for msg in messages[:-1]:  # Process complete messages
                    decoded = msg.decode('utf-8').strip()
                    if decoded == f"ARRIVED:{agent_id}":
                        return True
                buffer = messages[-1]  # Keep incomplete message
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[C] Error waiting for arrival: {e}")
                break
        return False  # Timeout or no confirmation