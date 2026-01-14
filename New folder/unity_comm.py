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

    def send_command(self, cmd: dict):
        payload = json.dumps(cmd, separators=(',', ':')) + "\n"
        try:
            self._connect()
            self.sock.sendall(payload.encode('utf-8'))
        except Exception:
            try:
                if self.sock:
                    self.sock.close()
            finally:
                self.sock = None
            raise

    def move_forward(self, distance: float = 1.0):
        self.send_command({"action": "move", "direction": "forward", "distance": float(distance)})

    def move_backward(self, distance: float = 1.0):
        self.send_command({"action": "move", "direction": "backward", "distance": float(distance)})

    def stop(self):
        self.send_command({"action": "stop"})
