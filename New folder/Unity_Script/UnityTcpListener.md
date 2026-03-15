```csharp

using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using System.Collections.Generic;
using UnityEngine;

[Serializable]
public class MovementCommand
{
    public string action;      // "move_to", "interact", "show_dialogue", "stop"
    public string agent;       // "Samson", "Jimmy", etc. (REQUIRED for multi-agent)
    public string partner;
    public string target;      // Target object name
    public string content;     // Dialogue content or description
    public string method;      // Interaction method name
    public string color;       // Interaction parameter
    public string description; // Action description
    public string display_time;
    public string session_id;
}

public class UnityTcpListener : MonoBehaviour
{
    public int port = 5005;
    public UnityMultiAgentDispatcher dispatcher;

    private TcpListener listener;
    private Thread listenerThread;
    private readonly Queue<MovementCommand> queue = new Queue<MovementCommand>();
    private readonly object queueLock = new object();
    private bool running = false;

    // Track persistent client connections (one per agent)
    private readonly List<Thread> clientThreads = new List<Thread>();
    private int activeClients = 0;
    private readonly object clientCountLock = new object();

    void Start()
    {
        Application.runInBackground = true;
        if (dispatcher == null)
        {
            dispatcher = GetComponent<UnityMultiAgentDispatcher>();
        }
        StartListener();
    }

    void OnDestroy()
    {
        StopListener();
    }

    void Update()
    {
        int processedCount = 0;
        int maxPerFrame = 50; // Process up to 50 commands per frame

        while (processedCount < maxPerFrame)
        {
            MovementCommand cmd = null;
            lock (queueLock)
            {
                if (queue.Count > 0)
                    cmd = queue.Dequeue();
                else
                    break; // Queue empty
            }

            if (cmd != null && dispatcher != null)
            {
                Debug.Log($"TCP Received cmd: {cmd.content}");
                dispatcher.HandleCommand(cmd);
            }
            processedCount++;
        }
    }

    void StartListener()
    {
        running = true;
        try
        {
            listener = new TcpListener(IPAddress.Any, port);
            listener.Start();
            listenerThread = new Thread(AcceptClientsLoop) { IsBackground = true };
            listenerThread.Start();
            Debug.Log($"[TCP-PERSIST] Listener started on port {port} - Ready for persistent agent connections");
        }
        catch (Exception ex)
        {
            Debug.LogError($"[TCP-PERSIST] Failed to start: {ex}");
        }
    }

    void StopListener()
    {
        running = false;
        try { listener?.Stop(); } catch { }
    }

    void AcceptClientsLoop()
    {
        while (running)
        {
            try
            {
                if (!listener.Pending())
                {
                    Thread.Sleep(10);
                    continue;
                }

                // Accept new agent connection
                TcpClient client = listener.AcceptTcpClient();
                client.NoDelay = true; // Disable Nagle's algorithm for low latency

                // Spawn dedicated thread for this agent's persistent connection
                Thread clientThread = new Thread(() => HandlePersistentClient(client))
                {
                    IsBackground = true,
                    Name = $"AgentConnection-{DateTime.Now.Ticks}"
                };

                lock (clientCountLock)
                {
                    activeClients++;
                    clientThreads.Add(clientThread);
                }

                clientThread.Start();
                Debug.Log($"[TCP-PERSIST] New agent connected. Active agents: {activeClients}");
            }
            catch (Exception ex)
            {
                if (running) Debug.LogWarning($"[TCP-PERSIST] Accept error: {ex.Message}");
                Thread.Sleep(100);
            }
        }
    }

    private static readonly Dictionary<string, NetworkStream> agentStreams = new Dictionary<string, NetworkStream>();
    private static readonly object streamLock = new object();

    public static void SendToAgent(string agentName, string message)
    {
        lock (streamLock)
        {
            if (agentStreams.TryGetValue(agentName, out NetworkStream stream) && stream.CanWrite)
            {
                try
                {
                    byte[] data = Encoding.UTF8.GetBytes(message + "\n");
                    stream.Write(data, 0, data.Length);
                }
                catch (Exception ex)
                {
                    Debug.LogWarning($"[TCP] Failed to send to {agentName}: {ex.Message}");
                }
            }
        }
    }

    void HandlePersistentClient(TcpClient client)
    {
        string clientId = client.Client.RemoteEndPoint.ToString();
        string detectedAgent = "Unknown";
        Debug.Log($"[TCP-PERSIST] Agent connection handler started for {clientId}");

        try
        {
            using (client)
            using (var stream = client.GetStream())
            {
                byte[] buffer = new byte[8192];

                // Keep reading commands from this agent's persistent connection
                while (running && client.Connected)
                {
                    try
                    {
                        // Read command (blocking, but on dedicated thread per agent)
                        int bytesRead = stream.Read(buffer, 0, buffer.Length);

                        if (bytesRead == 0)
                        {
                            // Agent disconnected gracefully
                            Debug.Log($"[TCP-PERSIST] Agent {detectedAgent} ({clientId}) disconnected");
                            break;
                        }

                        string content = Encoding.UTF8.GetString(buffer, 0, bytesRead).Trim();

                        // Process each command line
                        foreach (var line in content.Split('\n'))
                        {
                            if (string.IsNullOrWhiteSpace(line)) continue;

                            try
                            {
                                var cmd = JsonUtility.FromJson<MovementCommand>(line);
                                if (detectedAgent == "Unknown" && !string.IsNullOrEmpty(cmd.agent))
                                {
                                    detectedAgent = cmd.agent;
                                    lock (streamLock) { agentStreams[detectedAgent] = stream; }
                                    Debug.Log($"[TCP-PERSIST] Connection {clientId} identified as agent: {detectedAgent}");
                                }

                                // Queue command for processing on Unity main thread
                                lock (queueLock)
                                {
                                    queue.Enqueue(cmd);
                                }

                                // Send acknowledgment for each command
                                //byte[] ack = Encoding.UTF8.GetBytes("{\"state\":\"ok\"}\n");
                                //stream.Write(ack, 0, ack.Length);
                            }
                            catch (Exception ex)
                            {
                                Debug.LogWarning($"[TCP-PERSIST] Parse error from {detectedAgent}: {ex.Message}");
                            }
                        }
                    }
                    catch (System.IO.IOException)
                    {
                        // Connection lost
                        Debug.Log($"[TCP-PERSIST] Agent {detectedAgent} ({clientId}) connection lost");
                        break;
                    }
                }
            }
        }
        catch (Exception ex)
        {
            Debug.LogWarning($"[TCP-PERSIST] Agent {detectedAgent} ({clientId}) error: {ex.Message}");
        }
        finally
        {
            lock (clientCountLock)
            {
                activeClients--;
            }
            Debug.Log($"[TCP-PERSIST] Agent {detectedAgent} handler stopped. Active agents: {activeClients}");
        }
    }
}

```
