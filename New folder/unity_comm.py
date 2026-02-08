import socket
import json
import threading

class UnityClient:
    """Persistent connection version - maintains one socket per agent"""
    
    def __init__(self, host: str = "127.0.0.1", port: int = 5005, timeout: float = 2.0, default_agent_id: str = None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.default_agent_id = default_agent_id
        self._connections = {}
        self._connection_lock = threading.Lock()
        
    def _get_connection(self, agent_id: str):
        """Get or create a persistent connection for this agent"""
        with self._connection_lock:
            if agent_id not in self._connections or self._connections[agent_id] is None:
                try:
                    sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)  # Disable Nagle's algorithm
                    self._connections[agent_id] = sock
                    print(f"[PERSIST] Created connection for {agent_id}")
                except Exception as e:
                    print(f"[PERSIST] Failed to connect {agent_id}: {e}")
                    return None
            return self._connections[agent_id]
    
    def _close_connection(self, agent_id: str):
        """Close connection for specific agent"""
        with self._connection_lock:
            if agent_id in self._connections and self._connections[agent_id]:
                try:
                    self._connections[agent_id].close()
                except:
                    pass
                self._connections[agent_id] = None

    def send_command(self, cmd: dict, agent_id: str = None, wait_for_response: bool = False, retry: bool = True):
        """Send command using persistent connection"""
        # Fallback to 'Global' if no agent_id or default_agent_id is provided
        selected_agent_id = agent_id or self.default_agent_id or "Global"
        
        payload = json.dumps(cmd, separators=(',', ':')) + "\n"
        
        try:
            sock = self._get_connection(selected_agent_id)
            if sock is None:
                raise ConnectionError(f"No connection for {selected_agent_id}")
            
            sock.sendall(payload.encode('utf-8'))
            
            response = None
            if wait_for_response:
                sock.settimeout(self.timeout)
                response_data = sock.recv(4096)
                if response_data:
                    response = json.loads(response_data.decode('utf-8').strip())
            
            return response
            
        except (ConnectionError, BrokenPipeError, socket.error) as e:
            print(f"[PERSIST] Connection error for {selected_agent_id}: {e}")
            # Unity closes the connection after processing a command if not using persistent version,
            # but even in persistent version, network issues can occur.
            self._close_connection(selected_agent_id)
            
            # Retry once on connection failure
            if retry:
                return self.send_command(cmd, agent_id, wait_for_response, retry=False)
            raise

    def close(self):
        """Close all persistent connections"""
        with self._connection_lock:
            for agent_id, sock in self._connections.items():
                if sock:
                    try:
                        sock.close()
                        print(f"[PERSIST] Closed connection for {agent_id}")
                    except:
                        pass
            self._connections.clear()

    # Maintain same API as original UnityClient
    def get_state(self):
        return self.send_command({"action": "get_state"}, wait_for_response=True)

    def move_to(self, target_name: str, dialogue_content: str = None, description: str = None, agent_id: str = None):
        selected_agent_id = agent_id or self.default_agent_id
        cmd = {"action": "move_to", "target": target_name}
        if selected_agent_id:
            cmd["agent"] = selected_agent_id
        if dialogue_content:
            cmd["content"] = dialogue_content
        if description:
            cmd["description"] = description
        self.send_command(cmd, agent_id=selected_agent_id)

    def show_dialogue(self, emojis: str, agent_id: str = None):
        selected_agent_id = agent_id or self.default_agent_id
        cmd = {"action": "show_dialogue", "content": emojis}
        if selected_agent_id:
            cmd["agent"] = selected_agent_id
        self.send_command(cmd, agent_id=selected_agent_id)

    def interact(self, target_name: str, method: str, parameters: dict = None, agent_id: str = None):
        selected_agent_id = agent_id or self.default_agent_id
        cmd = {
            "action": "interact",
            "target": target_name,
            "method": method
        }
        if selected_agent_id:
            cmd["agent"] = selected_agent_id
        if parameters:
            cmd.update(parameters)
        self.send_command(cmd, agent_id=selected_agent_id, wait_for_response=True)

    def stop(self, agent_id: str = None):
        selected_agent_id = agent_id or self.default_agent_id
        cmd = {"action": "stop"}
        if selected_agent_id:
            cmd["agent"] = selected_agent_id
        self.send_command(cmd, agent_id=selected_agent_id)
