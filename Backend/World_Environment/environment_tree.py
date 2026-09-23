"""Environment tree for NPC location routing.

1. **Collect candidates** — Walk the tree and gather empty leaf nodes only.
2. **Rule filters** — Cheap keyword heuristics narrow or resolve the target
    without JEV:
        - *type_1*: action mentions a home object kind (Bed, House, Hearth, Table),
        - *type_2*: action mentions a public place (Church, River, Well).
        - *type_3*: action mentions an area name or the agent's workplace.
        preferring the agent's home area and workplaces.
    When a rule leaves exactly one empty node, that node is returned and JEV is
    skipped. Otherwise the filtered candidate set is passed on.
    
3. **Usage overlap** — If rules did not pick a node, keep candidates whose
   ``usage`` label shares words with the action text.

4. **JEV disambiguation** — When multiple candidates remain, JEV
   (``typesafe/jev-1.13`` via OpenRouter, see ``Secure.jev_client``) chooses
   in two steps:
   - *Area*: group candidates by parent area; JEV picks one area from labeled
     options (``AREA_ROUTING_INSTRUCTIONS``).
   - *Object*: within that area, JEV picks one empty node from path labels
     (``OBJECT_ROUTING_INSTRUCTIONS``).
   Each JEV call receives agent context (persona, role, workplace, home_area,
   current_area) plus the action string. Requests run on a thread pool with a
   timeout; invalid or missing answers yield no target. A single-option choice
   skips the network call.
"""

import json
import os
import re
import sqlite3
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv

from Secure.jev_client import jev_choice
from World_Environment.agent_state_manager import AgentStateManager

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

AREA_ROUTING_INSTRUCTIONS = (
    "Pick exactly one area whose usage best matches the action. "
    "Workplace tasks belong at the matching shop, not a house. "
    "Home is for rest, meals, and family only."
)
OBJECT_ROUTING_INSTRUCTIONS = (
    "Pick exactly one object in this area whose usage best matches the action. "
    "ShopArea and WaitZone are for customers. Table and Storage are for workers."
)

DB_PATH = os.path.join(BASE_DIR, "Database", "places.db")
ROUTING_COUNT_PATH = os.path.join(BASE_DIR, "World_Environment", "routingCount.json")
AREA_STATE_PATH = os.path.join(BASE_DIR, "World_Environment", "area_state.json")

TYPE_1_KINDS = ("Bed", "House", "Hearth", "Table")
TYPE_2_PLACES = ("Church", "River", "Well")
ROUTE_COUNTER_KEYS = ("type_1", "type_2", "type_3", "llm", "jev")
WORKPLACE_ALIASES = {
    "forge": "Blacksmith",
    "smithy": "Blacksmith",
}

load_dotenv()

class EnvironmentNode:
    def __init__(
        self,
        name: str,
        node_type: str,
        parent: Optional["EnvironmentNode"] = None,
        uuid_str: str | None = None,
        game_object_name: str | None = None,
        state: str = "empty",
    ):
        self.name = name
        self.node_type = node_type
        self.parent = parent
        self.children: list[EnvironmentNode] = []
        self.uuid = uuid_str if uuid_str else str(uuid.uuid4())
        self.game_object_name = game_object_name
        self.state = state

    def add_child(self, child: "EnvironmentNode"):
        self.children.append(child)
        child.parent = self

    def get_path(self) -> str:
        path = []
        current = self
        while current:
            path.append(current.name)
            current = current.parent
        return "/".join(reversed(path))

    def __repr__(self):
        return f"<EnvironmentNode {self.name} ({self.node_type})>"

class EnvironmentTree:
    def __init__(self, db_path: str = DB_PATH, max_depth: int = 5):
        self.db_path = db_path
        self.max_depth = max_depth
        self.lock = threading.RLock()
        self.root: EnvironmentNode | None = None
        self.nodes: dict[str, EnvironmentNode] = {}
        self.location_cache: dict[str, list[EnvironmentNode]] = {}
        self.action_map = self.load_action_map()
        self.usage_map = self.load_usage_map()
        self._routing_timeout = 10.0
        self._routing_executor = ThreadPoolExecutor(
            max_workers=5,
            thread_name_prefix="LocationRouting",
        )
        self.routing_count_path = ROUTING_COUNT_PATH
        self.routing_count_data = self._load_routing_count()
        self.usage_counters: dict[str, int | None] = {"simulation_day": None}
        for key in ROUTE_COUNTER_KEYS:
            self.usage_counters[key] = 0

    def _load_routing_count(self) -> dict[str, int]:
        loaded = {key: 0 for key in ROUTE_COUNTER_KEYS}
        try:
            with open(self.routing_count_path, encoding="utf-8") as f:
                raw_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return loaded
        if not isinstance(raw_data, dict):
            return loaded

        for key in ROUTE_COUNTER_KEYS:
            try:
                loaded[key] = int(raw_data.get(key, 0))
            except (TypeError, ValueError):
                loaded[key] = 0
        return loaded

    def _save_routing_count(self) -> None:
        payload = {"time": datetime.now().isoformat(timespec="seconds")}
        for key in ROUTE_COUNTER_KEYS:
            payload[key] = str(self.routing_count_data.get(key, 0))
        with open(self.routing_count_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=4)

    def get_routing_count(self, key: str) -> int:
        # Shared with location-routing threads.
        with self.lock:
            return int(self.routing_count_data.get(key, 0))

    def set_routing_count(self, key: str, value: int) -> None:
        # Shared with location-routing threads; persist stays inside the lock.
        with self.lock:
            self.routing_count_data[key] = value
            self._save_routing_count()

    def get_usage_counter(self, key: str) -> int | None:
        # Shared with location-routing threads.
        with self.lock:
            value = self.usage_counters.get(key)
            if isinstance(value, int):
                return value
            return None

    def set_usage_counter(self, key: str, value: int | None) -> None:
        # Shared with location-routing threads.
        with self.lock:
            self.usage_counters[key] = value

    def _add_route_count(self, key: str) -> None:
        # One lock so the saved total and the daily tally move together.
        with self.lock:
            self.set_routing_count(key, self.get_routing_count(key) + 1)
            daily = self.get_usage_counter(key) or 0
            self.set_usage_counter(key, daily + 1)

    def refresh_usage_counters(self, simulation_day: int | None) -> None:
        if simulation_day is None:
            return

        with self.lock:
            prev_day = self.get_usage_counter("simulation_day")
            if prev_day == simulation_day:
                return
            if prev_day is not None:
                summary = " ".join(
                    f"{key}={self.get_usage_counter(key)}" for key in ROUTE_COUNTER_KEYS
                )
                print(f"[LOCATION][DAY SUMMARY] day={prev_day} {summary}")
            self.set_usage_counter("simulation_day", simulation_day)
            for key in ROUTE_COUNTER_KEYS:
                self.set_usage_counter(key, 0)

    def load_action_map(self) -> dict[str, list[str]]:
        config_path = os.path.join(BASE_DIR, "World_Environment", "action_config.json")
        mapping = {}
        with open(config_path, encoding="utf-8") as f:
            data = json.load(f)
            # Programmatic population: flatten grouped verbs into lookup keys.
            for entry in data:
                for verb in entry.get("verbs", []):
                    mapping[verb.lower()] = entry.get("targets", [])
        return mapping

    def load_usage_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        try:
            with open(AREA_STATE_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return mapping

        def walk(node: dict) -> None:
            name = node.get("name")
            usage = node.get("usage")
            if isinstance(name, str) and isinstance(usage, str) and usage.strip():
                mapping[name] = usage.strip()
            for child in node.get("children", []):
                if isinstance(child, dict):
                    walk(child)

        if isinstance(data, dict):
            walk(data)
        return mapping

    def get_conn(self):
        return sqlite3.connect(self.db_path)

    def load(self):
        with self.lock:
            conn = self.get_conn()
            cur = conn.execute(
                "SELECT uuid, name, type, parent_uuid, game_object_name, state FROM environment_tree"
            )
            rows = cur.fetchall()
            conn.close()

            self.nodes = {}
            parent_map = {}

            for r in rows:
                uid, name, ntype, pid, gname, state = r
                node = EnvironmentNode(
                    name, ntype, uuid_str=uid, game_object_name=gname, state=state
                )
                self.nodes[uid] = node
                if pid:
                    parent_map[uid] = pid

            for uid, pid in parent_map.items():
                if pid in self.nodes:
                    parent = self.nodes[pid]
                    parent.add_child(self.nodes[uid])

            potential_roots = [n for n in self.nodes.values() if n.parent is None]
            self.root = potential_roots[0] if potential_roots else None

    def save_node(self, node: EnvironmentNode):
        with self.lock:
            conn = self.get_conn()
            conn.execute(
                """
                INSERT OR REPLACE INTO environment_tree (uuid, name, type, parent_uuid, game_object_name, state)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (
                    node.uuid,
                    node.name,
                    node.node_type,
                    node.parent.uuid if node.parent else None,
                    node.game_object_name,
                    node.state,
                ),
            )
            conn.commit()
            conn.close()

    def delete_node(self, uuid_str: str):
        with self.lock:
            if uuid_str in self.nodes:
                node = self.nodes[uuid_str]
                if node.parent:
                    node.parent.children.remove(node)
                for child in node.children:
                    child.parent = None
                del self.nodes[uuid_str]

            conn = self.get_conn()
            conn.execute("DELETE FROM environment_tree WHERE uuid = ?", (uuid_str,))
            conn.commit()
            conn.close()

    def add_node(
        self,
        name: str,
        node_type: str,
        parent: EnvironmentNode | None = None,
        game_object_name: str | None = None,
        state: str = "empty",
    ) -> EnvironmentNode:
        with self.lock:
            node = EnvironmentNode(
                name, node_type, parent, game_object_name=game_object_name, state=state
            )
            if parent:
                parent.add_child(node)
            elif not self.root:
                self.root = node

            self.nodes[node.uuid] = node
            self.save_node(node)
            return node

    def find_suitable_location(
        self, action: str, agent_id: str, simulation_day: int | None = None
    ) -> list[EnvironmentNode]:
        if not self.root:
            self.load()

        self.refresh_usage_counters(simulation_day)

        agent_name = agent_id
        target = None

        if self.root:
            empty_map = self.collect_empty_candidates(self.root)
            direct, rule_map = self._apply_rule_filters(action, agent_name, empty_map)
            if direct is not None:
                target = direct
            else:
                candidate_map = self._filter_candidates_by_usage(action, rule_map)
                target = self.resolve_target_with_jev(agent_name, action, candidate_map)
            if target and target.state != "empty":
                target = None

        path: list[EnvironmentNode] = []
        current = target
        while current:
            path.append(current)
            current = current.parent
        path.reverse()

        with self.lock:
            self.location_cache[action] = path
        return path

    def _routing_state(self, agent_name: str, action: str) -> dict[str, object]:
        agent_state = AgentStateManager().get_agent_state().get(agent_name, {})
        return {
            "agent": agent_name,
            "persona": agent_state.get("persona", "Unknown"),
            "role": agent_state.get("role"),
            "workplace": agent_state.get("workplace"),
            "home_area": agent_state.get("home_area"),
            "action": action,
            "current_area": agent_state.get("current_area"),
        }

    def _node_label(self, node: EnvironmentNode) -> str:
        usage = self.usage_map.get(node.name)
        if usage:
            return f"usage: {usage}"
        parent = node.parent.name if node.parent else "World"
        return f"{node.name} in {parent} (empty)"

    def _area_name(self, node: EnvironmentNode) -> str:
        if node.parent and node.parent.name != "World":
            return node.parent.name
        return node.name

    def _area_label(self, area_name: str, nodes: list[EnvironmentNode]) -> str:
        usages: list[str] = []
        seen: set[str] = set()
        area_usage = self.usage_map.get(area_name)
        if area_usage and area_usage not in seen:
            seen.add(area_usage)
            usages.append(area_usage)
        for node in nodes:
            usage = self.usage_map.get(node.name)
            if usage and usage not in seen:
                seen.add(usage)
                usages.append(usage)
        if usages:
            return "usage: " + "; ".join(usages)
        return f"area: {area_name}"

    def _group_candidates_by_area(
        self, candidates: dict[str, EnvironmentNode]
    ) -> dict[str, dict[str, EnvironmentNode]]:
        grouped: dict[str, dict[str, EnvironmentNode]] = {}
        for path, node in candidates.items():
            grouped.setdefault(self._area_name(node), {})[path] = node
        return grouped

    def _mentions(self, action: str, keyword: str) -> bool:
        if not keyword:
            return False
        return (
            re.search(rf"\b{re.escape(keyword)}\b", action, re.IGNORECASE) is not None
        )

    def _agent_workplaces(self, agent_name: str) -> list[str]:
        agent_state = AgentStateManager().get_agent_state().get(agent_name, {})
        raw = agent_state.get("workplace")
        if not raw or not isinstance(raw, str):
            return []

        names: list[str] = []
        for part in re.split(r"[,&/]| and ", raw):
            name = part.strip()
            if not name or name.lower() == "null":
                continue
            names.append(WORKPLACE_ALIASES.get(name.lower(), name))
        return names

    def _keep_in_areas(
        self, candidates: dict[str, EnvironmentNode], areas: list[str]
    ) -> dict[str, EnvironmentNode]:
        wanted = {area.lower() for area in areas if area}
        if not wanted:
            return {}
        return {
            path: node
            for path, node in candidates.items()
            if self._area_name(node).lower() in wanted
        }

    def _keep_kind(
        self, candidates: dict[str, EnvironmentNode], kind: str
    ) -> dict[str, EnvironmentNode]:
        kind_key = kind.lower()
        return {
            path: node
            for path, node in candidates.items()
            if kind_key in node.name.lower()
        }

    def _namesake_node(
        self, candidates: dict[str, EnvironmentNode], area_name: str
    ) -> EnvironmentNode | None:
        for node in candidates.values():
            if node.name.lower() == area_name.lower() and node.state == "empty":
                return node
        return None

    def _mentions_object_kind(self, action: str) -> bool:
        return any(self._mentions(action, kind) for kind in TYPE_1_KINDS)

    def _apply_rule_filters(
        self,
        action: str,
        agent_name: str,
        candidates: dict[str, EnvironmentNode],
    ) -> tuple[EnvironmentNode | None, dict[str, EnvironmentNode]]:
        """Return (direct target, leftover candidates). Direct skips JEV."""
        for place in TYPE_2_PLACES:
            if self._mentions(action, place):
                matched = self._keep_in_areas(candidates, [place])
                if not matched:
                    matched = self._keep_kind(candidates, place)
                if matched:
                    self._add_route_count("type_2")
                    if len(matched) == 1:
                        return next(iter(matched.values())), matched
                    return None, matched

        mentioned_areas: list[str] = []
        for area in {self._area_name(node) for node in candidates.values()}:
            if self._mentions(action, area) or self._mentions(
                action, area.replace("_", " ")
            ):
                mentioned_areas.append(area)
        for workplace in self._agent_workplaces(agent_name):
            if self._mentions(action, workplace):
                mentioned_areas.append(workplace)
        unique_areas = list(dict.fromkeys(mentioned_areas))
        if unique_areas:
            matched = self._keep_in_areas(candidates, unique_areas)
            if matched:
                self._add_route_count("type_3")
                if len(unique_areas) == 1 and not self._mentions_object_kind(action):
                    namesake = self._namesake_node(matched, unique_areas[0])
                    if namesake is not None:
                        return namesake, matched
                    if len(matched) == 1:
                        return next(iter(matched.values())), matched
                return None, matched

        for kind in TYPE_1_KINDS:
            if self._mentions(action, kind):
                matched = self._keep_kind(candidates, kind)
                if matched:
                    agent_state = (
                        AgentStateManager().get_agent_state().get(agent_name, {})
                    )
                    preferred_areas = [
                        agent_state.get("home_area"),
                        *self._agent_workplaces(agent_name),
                    ]
                    preferred = self._keep_in_areas(matched, preferred_areas) or matched
                    self._add_route_count("type_1")
                    if len(preferred) == 1:
                        return next(iter(preferred.values())), preferred
                    return None, preferred

        return None, candidates

    def _filter_candidates_by_usage(
        self, action: str, candidates: dict[str, EnvironmentNode]
    ) -> dict[str, EnvironmentNode]:
        action_words = {
            word for word in re.findall(r"[a-z]+", action.lower()) if len(word) > 2
        }
        matched: dict[str, EnvironmentNode] = {}
        for path, node in candidates.items():
            usage = self.usage_map.get(node.name, "")
            usage_words = {
                word for word in re.findall(r"[a-z]+", usage.lower()) if len(word) > 2
            }
            if usage_words & action_words:
                matched[path] = node
        if matched:
            return matched
        return candidates

    def request_jev_choice(
        self,
        action: str,
        agent_name: str,
        criteria: dict[str, str],
        question_id: str,
        instructions: str,
    ) -> str | None:
        if not criteria:
            return None
        if len(criteria) == 1:
            return next(iter(criteria))

        self._add_route_count("jev")
        state = self._routing_state(agent_name, action)
        future = self._routing_executor.submit(
            jev_choice,
            state,
            question_id,
            instructions,
            criteria,
            self._routing_timeout,
        )
        try:
            return future.result(timeout=self._routing_timeout)
        except TimeoutError:
            print(f"[LOCATION][JEV] timeout for '{action}' ({question_id})")
            future.cancel()
            return None
        except Exception as exc:
            print(
                f"[LOCATION][JEV] request failed for '{action}' ({question_id}): {exc}"
            )
            return None

    def resolve_target_with_jev(
        self,
        agent_name: str,
        action: str,
        candidates: dict[str, EnvironmentNode],
    ) -> EnvironmentNode | None:
        if not candidates:
            print(f"[LOCATION][JEV] no empty candidates for '{action}'")
            return None
        if len(candidates) == 1:
            return next(iter(candidates.values()))

        by_area = self._group_candidates_by_area(candidates)
        if len(by_area) == 1:
            chosen_area = next(iter(by_area))
        else:
            area_criteria = {
                area: self._area_label(area, list(nodes.values()))
                for area, nodes in by_area.items()
            }
            chosen_area = self.request_jev_choice(
                action,
                agent_name,
                area_criteria,
                "area",
                AREA_ROUTING_INSTRUCTIONS,
            )
            if chosen_area not in by_area:
                print(f"[LOCATION][JEV] invalid area for '{action}': {chosen_area}")
                return None

        area_candidates = by_area[chosen_area]
        if len(area_candidates) == 1:
            return next(iter(area_candidates.values()))

        object_criteria = {
            path: self._node_label(node) for path, node in area_candidates.items()
        }
        chosen_path = self.request_jev_choice(
            action,
            agent_name,
            object_criteria,
            "object",
            OBJECT_ROUTING_INSTRUCTIONS,
        )
        if chosen_path not in area_candidates:
            print(f"[LOCATION][JEV] invalid object for '{action}': {chosen_path}")
            return None
        return area_candidates[chosen_path]

    def collect_empty_candidates(
        self, start_node: EnvironmentNode, max_depth: int = 5
    ) -> dict[str, EnvironmentNode]:
        output: dict[str, EnvironmentNode] = {}

        def traverse(current: EnvironmentNode, depth: int = 0):
            if depth > max_depth:
                return

            if not current.children and current.state == "empty":
                output[current.get_path()] = current
                return

            for child in current.children:
                traverse(child, depth + 1)

        with self.lock:
            traverse(start_node)
        return output

    def build_area_list(self, node: EnvironmentNode, max_depth: int = 5) -> str:
        areas = set()

        def traverse(current: EnvironmentNode, depth: int = 0):
            if depth > max_depth:
                return

            if not current.children:
                if current.parent:
                    areas.add(current.parent.name)
                else:
                    areas.add("World")
                return

            for child in current.children:
                traverse(child, depth + 1)

        with self.lock:
            traverse(node)
            formatted_output = [f"{area}" for area in sorted(list(areas))]

        return ", ".join(formatted_output)

    def get_location(self, node: EnvironmentNode) -> str:
        return node.game_object_name or node.name

# def main():
# agents_state = AgentStateManager().get_agent_state()
# agents_config = [
#     {
#         "id": name,
#         "persona": data["persona"],
#         "home_node": data["home_node"],
#         "home_area": data["home_area"],
#         "workplace": data["workplace"],
#         "role": data["role"],
#     }
#     for name, data in agents_state.items()
# ]

# agent_executions = {
#     config["id"]: {
#         "persona": config["persona"],
#         "steps": [],
#         "emojis": [],
#         "current_step": 0,
#         "is_busy_until": 0,
#         "is_chatting": False,
#         "is_reflecting": False,
#         "active_task": None,
#         "current_target": config["home_node"],
#         "current_area": config["home_area"],
#         "prev_target": None,
#         "prev_area": None,
#     }
#     for config in agents_config
# }

# _ = agent_executions

# tree = EnvironmentTree()
# tree.load()
# path_nodes = tree.find_suitable_location(
#     "Woke up at House_Wilton, checked on Heath, and lit the hearth to start breakfast preparations in the kitchen.",
#     agent_id="Wilton",
# )
# if not path_nodes:
#     print("No target found")
#     return

# target_node = path_nodes[-1]
# target_name = tree.get_location(target_node)
# print(target_name)


# if __name__ == "__main__":
#     main()
