from skills.chroma_skill_lib import add_skill, get_best_skill, execute_skill
from unity_comm import UnityClient
from skills import place_db
import math
import time

def demo_move_to_place():
    dest = "A"
    place = place_db.get_place(dest)
    if place is None:
        #print("Place 'B' not found in DB")
        return
    
    pos = place.get("position")
    x = y = None
    parts = [p.strip() for p in pos.split(",")]
    if len(parts) >= 2:
        x, y = float(parts[0]), float(parts[1])
    if x is None or y is None:
        #print(f"Place '{dest}' has no valid position:", pos)
        return
    print(f"Moving to place '{dest}' at ({x}, {y})")

    unity = UnityClient()
    try:
        max_attempts = 50
        reached = False
        
        for attempt in range(max_attempts):
            current_pos = None
            try:
                state = unity.get_state()
                if state and "position" in state:
                    p = state["position"]
                    if isinstance(p, dict):
                        current_pos = (float(p.get("x", 0)), float(p.get("y", 0)))
                    elif isinstance(p, (list, tuple)) and len(p) >= 2:
                        current_pos = (float(p[0]), float(p[1]))
            except Exception:
                pass

            if current_pos:
                dist = math.hypot(x - current_pos[0], y - current_pos[1])
                print(f"Attempt {attempt+1}: Distance to {dest}: {dist:.2f} (at {current_pos})")
                if dist < 0.5:
                    reached = True
                    break

                step = min(0.5, dist)

                if current_pos[0] > x:
                    unity.move_left(step)
                elif current_pos[0] < x:
                    unity.move_right(step)

                if current_pos[1] > y:
                    unity.move_down(step)
                elif current_pos[1] < y:
                    unity.move_up(step)
            else:
                print(f"Attempt {attempt+1}: Position unknown.")
                return
            
            time.sleep(1.0)

        if reached:
            print(f"Reached destination {dest} at ({x}, {y})")
        else:
            print("Finished sequence (check Unity for current position)")

    finally:
        try:
            unity.close()
        except Exception:
            pass

if __name__ == "__main__":
    demo_move_to_place()
