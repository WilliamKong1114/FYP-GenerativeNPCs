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
    public string target; // optional target id or component name
}

/// <summary>
/// TCP listener that accepts newline-delimited JSON commands and dispatches
/// them to a target `UnityMovementController` (or any other component).
/// Attach to a GameObject and set `movementController` via Inspector or leave
/// null to auto-find on the same GameObject.
/// </summary>
public class UnityTcpListener : MonoBehaviour {
    public int port = 5005;
    public UnityMovementController movementController; // assign in Inspector or will auto-find

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
        // Process queued commands on main thread
        MovementCommand cmd = null;
        lock (queueLock) {
            if (queue.Count > 0) cmd = queue.Dequeue();
        }
        if (cmd != null) {
            HandleCommand(cmd);
        }
    }

    void StartListener() {
        running = true;
        try {
            listener = new TcpListener(IPAddress.Loopback, port);
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
        try { listenerThread?.Join(100); } catch {}
    }

    void ListenLoop() {
        try {
            while (running) {
                if (!listener.Pending()) {
                    Thread.Sleep(10);
                    continue;
                }
                using (TcpClient client = listener.AcceptTcpClient()) {
                    using (var stream = client.GetStream()) {
                        var reader = new System.IO.StreamReader(stream, Encoding.UTF8);
                        string line;
                        while (running && (line = reader.ReadLine()) != null) {
                            try {
                                var cmd = JsonUtility.FromJson<MovementCommand>(line);
                                lock (queueLock) {
                                    queue.Enqueue(cmd);
                                }
                            } catch (Exception ex) {
                                Debug.LogWarning("Failed to parse command: " + ex);
                            }
                        }
                    }
                }
            }
        } catch (Exception ex) {
            Debug.LogWarning("Listener loop stopped: " + ex);
        }
    }

    void HandleCommand(MovementCommand cmd) {
        if (cmd == null || string.IsNullOrEmpty(cmd.action)) return;

        // Optionally route by cmd.target here if you manage multiple agents
        var controller = movementController;
        if (controller == null) {
            Debug.LogWarning("No UnityMovementController assigned or found");
            return;
        }

        switch (cmd.action.ToLower()) {
            case "move":
                if (!string.IsNullOrEmpty(cmd.direction)) {
                    var d = cmd.direction.ToLower();
                    if (d.StartsWith("f") || d == "forward") {
                        controller.MoveForward(cmd.distance);
                    } else if (d.StartsWith("b") || d == "back" || d == "backward") {
                        controller.MoveBackward(cmd.distance);
                    } else if (d.StartsWith("u") || d == "up") {
                        controller.MoveUp(cmd.distance);
                    } else if (d.StartsWith("d") || d == "down") {
                        controller.MoveDown(cmd.distance);
                    } else if (d.StartsWith("r") || d == "right") {
                        controller.MoveRight(cmd.distance);
                    } else if (d.StartsWith("l") || d == "left") {
                        controller.MoveLeft(cmd.distance);
                    } else {
                        Debug.LogWarning($"Unhandled move direction: {cmd.direction}");
                    }
                }
                break;
            case "turn":
                controller.Turn(cmd.angle);
                break;
            case "stop":
                controller.StopMotion();
                break;
            default:
                Debug.Log($"Unknown action: {cmd.action}");
                break;
        }
    }
}
