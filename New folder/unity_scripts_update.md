# Unity Scripts Update

To enable the "Execute Plan" functionality where the agent moves to specific locations (Table, Bed, Land, etc.), you need to update your Unity scripts to support Pathfinding (NavMesh) and the new `move_to` command.

## 1. UnityTcpListener.cs

Update the `HandleCommand` method to support the `move_to` action.

```csharp
using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Generic;
using UnityEngine;

[Serializable]
public class MovementCommand {
    public string action;
    public string direction;
    public float distance;
    public float angle;
    public string target; // The name of the object (e.g., "Table", "Bed")
}

public class UnityTcpListener : MonoBehaviour {
    public int port = 5005;
    public UnityMovementController movementController;

    private TcpListener listener;
    private Thread listenerThread;
    private readonly Queue<MovementCommand> queue = new Queue<MovementCommand>();
    private readonly object queueLock = new object();
    private bool running = false;

    void Start() {
        if (movementController == null) {
            movementController = GetComponent<UnityMovementController>();
        }
        StartListener();
    }

    void OnDestroy() {
        StopListener();
    }

    void Update() {
        MovementCommand cmd = null;
        lock (queueLock) {
            if (queue.Count > 0) cmd = queue.Dequeue();
        }
        if (cmd != null) {
            HandleCommand(cmd);
        }
    }

    void HandleCommand(MovementCommand cmd) {
        if (cmd == null || string.IsNullOrEmpty(cmd.action)) return;

        var controller = movementController;
        if (controller == null) return;

        switch (cmd.action.ToLower()) {
            case "move_to":
                // New logic for named target movement
                controller.MoveTo(cmd.target);
                break;
            case "move":
                if (!string.IsNullOrEmpty(cmd.direction)) {
                    var d = cmd.direction.ToLower();
                    if (d.StartsWith("f")) controller.MoveForward(cmd.distance);
                    else if (d.StartsWith("b")) controller.MoveBackward(cmd.distance);
                    else if (d.StartsWith("u")) controller.MoveUp(cmd.distance);
                    else if (d.StartsWith("d")) controller.MoveDown(cmd.distance);
                    else if (d.StartsWith("r")) controller.MoveRight(cmd.distance);
                    else if (d.StartsWith("l")) controller.MoveLeft(cmd.distance);
                }
                break;
            case "turn":
                controller.Turn(cmd.angle);
                break;
            case "stop":
                controller.StopMotion();
                break;
        }
    }

    // Connect/Disconnect logic remains similar to your existing code
    void StartListener() {
        running = true;
        try {
            listener = new TcpListener(IPAddress.Any, port); // Listen on all interfaces
            listener.Start();
            listenerThread = new Thread(ListenLoop) { IsBackground = true };
            listenerThread.Start();
            Debug.Log($"TCP listener started on port {port}");
        } catch (Exception ex) {
            Debug.LogError($"Failed to start TCP listener: {ex}");
        }
    }

    void StopListener() {
        running = false;
        try { listener?.Stop(); } catch {}
    }

    void ListenLoop() {
        while (running) {
            try {
                if (!listener.Pending()) { Thread.Sleep(10); continue; }
                using (TcpClient client = listener.AcceptTcpClient()) {
                    using (var stream = client.GetStream()) {
                        byte[] buffer = new byte[1024];
                        int bytesRead = stream.Read(buffer, 0, buffer.Length);
                        if (bytesRead > 0) {
                            string content = Encoding.UTF8.GetString(buffer, 0, bytesRead).Trim();
                            // Handle multiple commands in one packet if necessary
                            foreach(var line in content.Split('\n')) {
                                if(string.IsNullOrWhiteSpace(line)) continue;
                                try {
                                    var cmd = JsonUtility.FromJson<MovementCommand>(line);
                                    lock (queueLock) { queue.Enqueue(cmd); }
                                } catch (Exception ex) { Debug.LogWarning(ex); }
                            }
                        }
                        // Send simple ack
                        byte[] ack = Encoding.UTF8.GetBytes("{\"status\":\"ok\"}");
                        stream.Write(ack, 0, ack.Length);
                    }
                }
            } catch (Exception) { Thread.Sleep(100); }
        }
    }
}
```

## 2. UnityMovementController.cs

We will update this to use `NavMeshAgent` for intelligent pathfinding to the targets.

**Prerequisites:**

1.  Add a `NavMeshAgent` component to your Agent GameObject in Unity.
2.  Bake a NavMesh for your scene (Window > AI > Navigation).
3.  Ensure your target objects (Table, Bed, Land) have Colliders.

```csharp
using System.Collections;
using UnityEngine;
using UnityEngine.AI; // Required for NavMeshAgent

public class UnityMovementController : MonoBehaviour
{
    [Header("Movement")]
    public float moveSpeed = 3.5f;

    [Header("References")]
    private NavMeshAgent agent;

    void Start()
    {
        agent = GetComponent<NavMeshAgent>();
        if (agent == null) {
            Debug.LogError("UnityMovementController requires a NavMeshAgent component!");
            // Fallback if needed, or add one dynamically
            // agent = gameObject.AddComponent<NavMeshAgent>();
        } else {
            agent.speed = moveSpeed;
        }
    }

    // --- New Method for Paper Implementation ---
    public void MoveTo(string targetName) {
        if (agent == null) return;

        // 1. Find the GameObject by name
        GameObject targetObj = GameObject.Find(targetName);

        if (targetObj != null) {
            Debug.Log($"Pathfinding to: {targetName} at {targetObj.transform.position}");

            // 2. Set Destination
            agent.isStopped = false;
            agent.SetDestination(targetObj.transform.position);
        } else {
            Debug.LogError($"Target '{targetName}' not found in the scene! Ensure GameObject name matches.");
        }
    }
    // -------------------------------------------

    public void StopMotion() {
        if(agent) agent.isStopped = true;
        StopAllCoroutines();
    }

    // ... Keep existing direct movement methods (MoveForward, etc.) if needed for manual control
    // But for the Generative Agents paper logic, MoveTo is the primary interaction.

    public void Turn(float angle) {
         transform.Rotate(0, angle, 0);
    }

    // Legacy support wrappers
    public void MoveForward(float d) => transform.position += transform.forward * d;
    public void MoveBackward(float d) => transform.position -= transform.forward * d;
    public void MoveUp(float d) => transform.position += transform.up * d;
    public void MoveDown(float d) => transform.position -= transform.up * d;
    public void MoveRight(float d) => transform.position += transform.right * d;
    public void MoveLeft(float d) => transform.position -= transform.right * d;
}
```

## Unity Setup Steps

1.  **NavMesh**: Go to `Window > AI > Navigation` (or the AI Navigation package in newer Unity versions). Mark your floors/grounds as "Navigation Static" and click **Bake**.
2.  **Agent**: Select your Character/Agent GameObject.
    - Add Component -> `NavMesh Agent`.
    - Add Component -> `UnityTcpListener`.
    - Add Component -> `UnityMovementController`.
3.  **Environment**: Ensure your target objects are named exactly as they are in the Python Environment Tree:
    - "Table"
    - "Bed"
    - "Land"
    - "Workshop"
