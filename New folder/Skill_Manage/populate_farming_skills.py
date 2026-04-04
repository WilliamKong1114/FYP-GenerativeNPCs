import sys
import os
from Skill_Manage.chroma_skill_lib import add_skill
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

def populate():
    print("Populating Farming Skills...")

    code_move = """
target = params.get("target_name")
if not target:
    raise ValueError("Target name is required for MoveTo skill")
unity.move_to(target)
result = True
"""
    add_skill(
        name="MoveTo",
        description="Move the agent to a specific target object or area by name.",
        code=code_move
    )
    print(" - Added 'MoveTo'")

    code_wait = """
import time
duration = float(params.get("duration", 2.0))
time.sleep(duration)
result = True
"""
    add_skill(
        name="Wait",
        description="Pause execution for a specified duration in seconds.",
        code=code_wait
    )
    print(" - Added 'Wait'")

    code_color = """
target = params.get("target_name")
color = params.get("color", "brown")
if not target:
    raise ValueError("Target name is required for ChangeColor skill")
unity.interact(target, "change_color", {"color": color})
result = True
"""
    add_skill(
        name="ChangeColor",
        description="Change the color of a specific target object.",
        code=code_color
    )
    print(" - Added 'ChangeColor'")

    code_till = """
import time

base_name = params.get("base_name", "Dirt")
count = int(params.get("count", 12))
tilled_color = params.get("color", "brown")
stay_duration = float(params.get("stay_duration", 2.0))

targets = []
for i in range(1, count + 1):
    targets.append(f"{base_name} ({i})")

print(f"Starting Tilling Task for {count} blocks...")

for target in targets:
    unity.move_to(target)
    time.sleep(stay_duration)
    unity.interact(target, "change_color", {"color": tilled_color})
    print(f" - Tilled {target}")

print("Tilling complete.")
result = True
"""
    add_skill(
        name="TillLand",
        description="Till all dirt blocks in the Land by walking through them, waiting, and changing their color.",
        code=code_till
    )
    print(" - Added 'TillLand'")
    print("Done.")

if __name__ == "__main__":
    populate()
