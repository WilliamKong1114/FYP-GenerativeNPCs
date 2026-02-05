import socket
import json

class UnityClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 5005, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
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
            self.connect()
            self.sock.sendall(payload.encode('utf-8'))
            response = None
            if wait_for_response:
                self.sock.settimeout(self.timeout)
                response_data = self.sock.recv(4096)
                if response_data:
                    response = json.loads(response_data.decode('utf-8').strip())
            
            # Unity closes the connection after processing a command,
            # so we should also close our end to avoid stale socket issues.
            self.sock.close()
            self.sock = None
            return response
            
        except Exception:
            if self.sock:
                try:
                    self.sock.close()
                except:
                    pass
            self.sock = None
            raise

    def get_state(self):
        return self.send_command({"action": "get_state"}, wait_for_response=True)

    def move_to(self, target_name: str, dialogue_content: str = None, description: str = None):
        cmd = {"action": "move_to", "target": target_name, "description": description}
        if dialogue_content:
            cmd["content"] = dialogue_content
        if description:
            cmd["description"] = description
        self.send_command(cmd)

    def show_dialogue(self, emojis: str):
        self.send_command({"action": "show_dialogue", "content": emojis})

    def interact(self, target_name: str, method: str, parameters: dict = None):
        cmd = {
            "action": "interact",
            "target": target_name,
            "method": method
        }
        if parameters:
            cmd.update(parameters)
            
        self.send_command(cmd, wait_for_response=True)

    def stop(self):
        self.send_command({"action": "stop"})