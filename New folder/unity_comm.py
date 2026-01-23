import socket
import json

class UnityClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5005, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def _connect(self):
        if self.sock:
            return
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        finally:
            self.sock = None

    def send_command(self, cmd: dict, wait_for_response: bool = False):
        payload = json.dumps(cmd, separators=(',', ':')) + "\n"
        try:
            self._connect()
            self.sock.sendall(payload.encode('utf-8'))
            if wait_for_response:
                self.sock.settimeout(self.timeout)
                response_data = self.sock.recv(4096)
                if response_data:
                    return json.loads(response_data.decode('utf-8').strip())
        except Exception:
            try:
                if self.sock:
                    self.sock.close()
            finally:
                self.sock = None
            raise
        return None

    def get_state(self):
        return self.send_command({"action": "get_state"}, wait_for_response=True)

    def move_to(self, target_name: str):
        self.send_command({"action": "move_to", "target": target_name})

    def stop(self):
        self.send_command({"action": "stop"})