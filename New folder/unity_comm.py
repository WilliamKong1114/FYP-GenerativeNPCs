import socket
import json
import threading
import time
from agent_memory import AgentMemoryManager

class UnityClient:    
    def __init__(self, host: str = "127.0.0.1", port: int = 5005, timeout: float = 2.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._connections = {}
        self._connection_lock = threading.Lock()
        self.dialogue_cache = {}

    @staticmethod
    def _cache_key(pair_key: tuple, session_id: str = None):
        if session_id:
            return (pair_key, str(session_id))
        return pair_key

    @staticmethod
    def _canonical_pair(agent_a: str, agent_b: str):
        if not agent_a or not agent_b:
            return None
        return tuple(sorted((str(agent_a), str(agent_b))))
        
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
            sock = self._get_connection(agent_id)
            if sock is None:
                return ConnectionError(f"No connection for {agent_id}")

            try:
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
            except (BrokenPipeError, ConnectionResetError, OSError):
                self._close_connection(agent_id)
                if attempt == (1 if retry else 0):
                    raise

        return None
        
    def close(self):
        with self._connection_lock:
            for agent_id, sock in self._connections.items():
                if sock:
                    sock.close()
                    #print(f"[C] Closed connection for {agent_id}")
            self._connections.clear()

    def build_and_send(self, action: str, agent_id: str = None, target: str = None, content: str = None, display_time: float = None, wait_for_response: bool = False, **kwargs):
        cmd = {"action": action, **kwargs}
        if agent_id:
            cmd["agent"] = agent_id
        if target:  
            cmd["target"] = target
        if content:
            cmd["content"] = content
        if display_time:
            cmd["display_time"] = display_time
        return self.send_command(cmd, agent_id=agent_id, wait_for_response=wait_for_response)

    def move_to(self, target: str, content: str = None, description: str = None, agent_id: str = None, wait_for_response: bool = False):
        self.build_and_send("move_to", agent_id, target=target, content=content, description=description)
        if wait_for_response:
            return self.wait_for_arrival(agent_id, timeout=20.0)
        return True
    
    def set_chatting(self, agent_id: str = None, content: str = None, partner_id: str = None):
        kwargs = {}
        if partner_id:
            kwargs["partner"] = partner_id
        self.build_and_send("set_chatting", agent_id=agent_id, content=content, **kwargs)

    def show_dialogue(self, content: str, agent_id: str = None, display_time: float = None):
        self.build_and_send("show_dialogue", agent_id, content=content, display_time=display_time)

    def interact(self, target: str, method: str, parameters: dict = None, agent_id: str = None):
        kwargs = {"target": target, "method": method}
        if parameters:
            kwargs.update(parameters)
        return self.build_and_send("interact", agent_id, wait_for_response=True, **kwargs)

    def stop(self, agent_id: str = None):
        self.build_and_send("stop", agent_id)

    def action_recorded(self, agent_id: str, action_text: str, location: str, day: int, time_str: str, ts: float):
        kwargs = {
            "action_text": action_text,
            "location": location,
            "day": day,
            "time_str": time_str,
            "ts": ts
        }
        self.build_and_send("action_recorded", agent_id=agent_id, **kwargs)

    def update_time(self, time_str: str):
        self.build_and_send("time_update", agent_id="System", content=time_str)

    def update_dialogue(self, agent_id: str, dialogue_lines: list, agent_ids: list):
        dialogues = "\n".join(dialogue_lines)
        kwargs = {"content": dialogues}
        kwargs["agent_ids"] = agent_ids
        self.build_and_send("update_dialogue", agent_id=agent_id, **kwargs)

    def _agent_availability(self, agent_id: str, agent_executions: dict):
        data = agent_executions.get(agent_id)
        if not data:
            return {
                "status": "error",
                "agent_id": agent_id,
                "available": False,
                #"is_busy": False,
                "is_chatting": False,
                "is_reflecting": False,
                "message": "Unknown agent.",
            }

        #active_task = data.get("active_task")
        #is_task_running = bool(active_task and not active_task.done())
        #is_cooldown = time.time() < float(data.get("is_busy_until", 0) or 0)
        #is_busy = is_task_running or is_cooldown
        is_chatting = bool(data.get("is_chatting", False))
        is_reflecting = bool(data.get("is_reflecting", False))
        available = not (is_chatting or is_reflecting)

        if available:
            message = "Agent is available for interaction."
        elif is_chatting:
            message = "Agent is currently in conversation."
        elif is_reflecting:
            message = "Agent is currently reflecting."

        return {
            "status": "success",
            "agent_id": agent_id,
            "available": available,
            #"is_busy": is_busy,
            "is_chatting": is_chatting,
            "is_reflecting": is_reflecting,
            "message": message,
        }

    def send_response(self, agent_id: str, request_id: str, payload: dict):
        payload_json = json.dumps(payload, ensure_ascii=False)
        self.build_and_send(
            "user_chat",
            agent_id=agent_id,
            content=payload_json,
            request_id=request_id,
        )

    def handle_incoming_command(self, command_dict, agent_executions, interaction_manager=None):
        action = str(command_dict.get("action", "")).lower()
        agent_id = command_dict.get("agent")
        partner_id = command_dict.get("partner")
        request_id = command_dict.get("request_id")
        current_area = agent_executions.get("current_area")
        current_target = agent_executions.get("current_target")
                
        if action == "conversation_finished":
            if agent_id and agent_id in agent_executions:
                agent_executions[agent_id]["is_chatting"] = False
                agent_executions[agent_id]["is_busy_until"] = time.time() + 1

            if partner_id and partner_id in agent_executions:
                agent_executions[partner_id]["is_chatting"] = False
                agent_executions[partner_id]["is_busy_until"] = time.time() + 1
            return

        if action != "user_chat":
            return

        #target_agent = command_dict.get("target_agent") or agent_id
        session_id = command_dict.get("session_id")
        user_text = str(command_dict.get("user_text")).strip()

        if not session_id:
            availability = self._agent_availability(agent_id, agent_executions)

            if availability.get("status") != "success" or not availability.get("available", False):
                self.send_response(agent_id=agent_id, request_id=request_id, payload=availability)
                return

            try:
                payload = interaction_manager.start_conversation(agent_id, question=user_text, current_area=current_area, current_target=current_target)
                if agent_id in agent_executions:
                    agent_executions[agent_id]["is_chatting"] = True
                    agent_executions[agent_id]["is_busy_until"] = time.time() + 600
            except ValueError as e:
                payload = {
                    "status": "error",
                    "agent_id": agent_id,
                    "message": str(e),
                }

            self.send_response(agent_id=agent_id, request_id=request_id, payload=payload)
            return
        
        try:
            payload = interaction_manager.continue_conversation(session_id=session_id, user_text=user_text, current_area=current_area, current_target=current_target)
            session_agent = payload.get("agent_id")
            if session_agent in agent_executions:
                ended = bool(payload.get("ended", False))
                agent_executions[session_agent]["is_chatting"] = not ended
                agent_executions[session_agent]["is_busy_until"] = time.time() + (1 if ended else 600)
        except ValueError as e:
            payload = {
                "status": "error",
                "agent_id": agent_id,
                "message": str(e),
            }

        self.send_response(agent_id=agent_id, request_id=request_id, payload=payload)
        return

    def receive_msg(self, agent_id: str, timeout: float = 5.0):
        sock = self._get_connection(agent_id)
        if not sock: return
        
        try:
            sock.settimeout(timeout)
            data = sock.recv(1024)
            if not data: 
                print(f"[S] Receive no data from {agent_id}.")
                return

            return [msg.decode('utf-8').strip() for msg in data.split(b"\n") if msg.strip()]
        except (socket.timeout):
            return
        except Exception as e:
            print(f"[S] Error receiving message for {agent_id}: {e}")
            return

    def wait_for_conv_finish(self, agent_id: str, timeout: float = 300.0):
        start_time = time.time()
        while time.time() - start_time < timeout:
            messages = self.receive_msg(agent_id)
            if not messages:
                return False
            for msg in messages:
                if msg.startswith("{"):
                    cmd = json.loads(msg)
                    if cmd.get("action") == "conversation_finished":
                        print(f"[TCP] User finished reading. Resuming agents.")
                        return True
        return False

    def wait_for_arrival(self, agent_id: str, timeout: float = 10.0):        
        start_time = time.time()
        while time.time() - start_time < timeout:
            message = self.receive_msg(agent_id)
            if f"ARRIVED:{agent_id}" in message:
                #print(f"[TCP] {agent_id} arrived")
                return True
        return False 

    def check_for_incoming(self, agent_id: str, agent_executions: dict, interaction_manager=None):
        messages = self.receive_msg(agent_id, timeout=0.001)
        if not messages:
            return

        for msg in messages:
            try:
                if msg.startswith("{"):
                    cmd = json.loads(msg)
                    self.handle_incoming_command(cmd, agent_executions, interaction_manager=interaction_manager)
            except Exception as e:
                print(f"[TCP] Failed to handle incoming command for {agent_id}: {e}")
                continue
