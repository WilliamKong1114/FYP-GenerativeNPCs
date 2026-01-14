from unity_comm import UnityClient
import time

#1. run unity scene
#2. run python unity_movement_test.py

def run_sequence():
    client = UnityClient()
    moves = [
        ("up", 1.0),
        ("right", 1.0),
        ("down", 0.5),
        ("left", 0.5),
    ]
    for i in range(3):
        for direction, distance in moves:
            print(f"Move {direction} {distance}")
            client.send_command({"action": "move", "direction": direction, "distance": distance})
            time.sleep(0.4)

    print("Stop")
    client.stop()

if __name__ == '__main__':
	run_sequence()

