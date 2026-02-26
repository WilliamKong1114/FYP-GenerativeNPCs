# Unity Scripts Update

## 1. UnityTcpListener.cs (PERSISTENT CONNECTION VERSION)

**ARCHITECTURE:** Maintains one persistent connection per agent for maximum performance (15+ agents).
Each agent's Python client establishes a dedicated socket that stays open, eliminating reconnection overhead.

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
    public string target;      // Target object name
    public string content;     // Dialogue content or description
    public string method;      // Interaction method name
    public string color;       // Interaction parameter
    public string description; // Action description
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

    /// <summary>
    /// Handle persistent connection for one agent - keeps reading until agent disconnects.
    /// This runs in a dedicated thread per agent, allowing true parallel command processing.
    /// </summary>
    ///

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
                        Debug.Log($"Raw received: {content}");

                        // Process each command line
                        foreach (var line in content.Split('\n'))
                        {
                            if (string.IsNullOrWhiteSpace(line)) continue;

                            try
                            {
                                var cmd = JsonUtility.FromJson<MovementCommand>(line);

                                // Detect agent ID from first command for logging
                                if (detectedAgent == "Unknown" && !string.IsNullOrEmpty(cmd.agent))
                                {
                                    detectedAgent = cmd.agent;
                                    Debug.Log($"[TCP-PERSIST] Connection {clientId} identified as agent: {detectedAgent}");
                                }

                                // Queue command for processing on Unity main thread
                                lock (queueLock)
                                {
                                    queue.Enqueue(cmd);
                                }

                                // Send acknowledgment for each command
                                byte[] ack = Encoding.UTF8.GetBytes("{\"state\":\"ok\"}\n");
                                stream.Write(ack, 0, ack.Length);
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

## 2. UnityMultiAgentDispatcher.cs (New)

Attach this to the NetworkManager object.

```csharp
using UnityEngine;

public class UnityMultiAgentDispatcher : MonoBehaviour
{
    public void HandleCommand(MovementCommand cmd)
    {
        if (string.IsNullOrEmpty(cmd.agent))
        {
            Debug.LogWarning("Command received without Agent ID");
            return;
        }

        GameObject agentObj = GameObject.Find(cmd.agent);
        if (agentObj == null)
        {
            Debug.LogError($"Agent '{cmd.agent}' not found in scene!");
            return;
        }

        SimAgent msgAgent = agentObj.GetComponent<SimAgent>();
        if (msgAgent == null)
        {
            Debug.LogError($"GameObject '{cmd.agent}' does not have a SimAgent component!");
            return;
        }

        Debug.Log($"Doing {cmd.action} by {cmd.agent}; Emoji: {cmd.content}");

        switch (cmd.action.ToLower())
        {
            case "move_to":
                Debug.Log($"[Dispatcher] Processing move_to for {cmd.agent}: target={cmd.target}, content={cmd.content}");
                msgAgent.MoveTo(cmd.target);
                msgAgent.showDialogue(cmd.content);
                break;
            case "interact":
                msgAgent.Interact(cmd.method, cmd.target, cmd.color);
                break;

            case "show_dialogue":
                msgAgent.showDialogue(cmd.content);
                break;

            case "stop":
                msgAgent.StopMotion();
                break;
        }
    }
}
```

## 3. SimAgent.cs (Replaces UnityMovementController for Agents)

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;
using System.Text.RegularExpressions;

public class SimAgent : MonoBehaviour
{
    public float moveSpeed = 2.0f;
    private Pathfinding pathfinder;
    public GameObject dialoguePanel;
    public TMP_Text emojiText;

    void Start()
    {
        pathfinder = FindObjectOfType<Pathfinding>();
        if (pathfinder == null) Debug.LogError("No Pathfinding script found in scene!");
        if (dialoguePanel != null) dialoguePanel.SetActive(false);
    }

    public void MoveTo(string targetName)
    {
        if (Environment.Instance == null)
        {
            Debug.LogError("Environment script is missing from the scene!");
            return;
        }

        Vector3 destination = Environment.Instance.GetValidPosition(targetName);

        if (destination != Vector3.zero)
        {
            List<Vector3> path = pathfinder.FindPath(transform.position, destination);

            if (path != null && path.Count > 0)
            {
                StopAllCoroutines();
                StartCoroutine(FollowPath(path));
            }
            else
            {
                // Fallback: If random point is unwalkable, try exact center
                GameObject exactTarget = GameObject.Find(targetName);
                if (exactTarget)
                {
                    path = pathfinder.FindPath(transform.position, exactTarget.transform.position);
                    if (path != null && path.Count > 0)
                    {
                        StopAllCoroutines();
                        StartCoroutine(FollowPath(path));
                    }
                }
            }
        }
    }
    public void showDialogue(string text)
    {
        if (dialoguePanel != null && emojiText != null)
        {
            string processedText = Regex.Unescape(text);
            dialoguePanel.SetActive(true);
            emojiText.text = processedText;
            StartCoroutine(HideDialogueCoroutine());
        }
    }

    private IEnumerator HideDialogueCoroutine()
    {
        yield return new WaitForSeconds(4.0f);
        if (dialoguePanel != null) dialoguePanel.SetActive(false);
    }

    IEnumerator FollowPath(List<Vector3> path)
    {
        int targetIndex = 0;
        while (targetIndex < path.Count)
        {
            Vector3 targetPos = new Vector3(path[targetIndex].x, path[targetIndex].y, transform.position.z);

            transform.position = Vector3.MoveTowards(transform.position, targetPos, moveSpeed * Time.deltaTime);
            Vector3 dir = targetPos - transform.position;

            if (dir.sqrMagnitude > 0.001f)
            {
                float angle = Mathf.Atan2(dir.y, dir.x) * Mathf.Rad2Deg;
                transform.rotation = Quaternion.AngleAxis(angle, Vector3.forward);
            }

            if (Vector2.Distance(transform.position, targetPos) < 0.1f)
            {
                targetIndex++;
            }
            yield return null;
        }
    }

    public void Interact(string method, string targetName, string color=null)
    {
        if (string.IsNullOrEmpty(targetName))
        {
            Debug.LogWarning($"[SimAgent {name}] Interaction command missing target.");
            return;
        }

        Debug.Log($"[{name}] Interacting with {targetName} via method: {method}");

        GameObject targetObj = GameObject.Find(targetName);
        if (targetObj != null)
        {
            var interactable = targetObj.GetComponent<InteractableObject>();
            if (interactable != null)
            {
                interactable.Interact(method, color);
            }
            else
            {
                Debug.LogWarning($"Object {targetName} has no InteractableObject script. Trying SendMessage.");
                targetObj.SendMessage(method, SendMessageOptions.DontRequireReceiver);
            }
        }
        else
        {
            Debug.LogError($"Target object not found: {targetName}");
        }
    }

    public void StopMotion()
    {
        StopAllCoroutines();
    }
}

```

## UnityMovementController.cs

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using TMPro;

public class UnityMovementController : MonoBehaviour
{
    public float moveSpeed = 1.0f;
    private Pathfinding pathfinder;
    private Coroutine currentMotion = null;

    public GameObject dialoguePanel;
    public TMP_Text emojiText;

    public void showDialogue(string emojis)
    {
        if (dialoguePanel != null && emojiText != null)
        {
            emojiText.text = emojis;
            dialoguePanel.SetActive(true);

            StopCoroutine(nameof(HideDialogueCoroutine));
            StartCoroutine(nameof(HideDialogueCoroutine));
        }
    }

    private System.Collections.IEnumerator HideDialogueCoroutine()
    {
        yield return new WaitForSeconds(4.0f); // Adjust duration as needed
        if (dialoguePanel != null)
        {
            dialoguePanel.SetActive(false);
        }
    }

    void Start()
    {
        pathfinder = FindObjectOfType<Pathfinding>();
        if (pathfinder == null) Debug.LogError("No Pathfinding script found in scene!");
    }
    public void MoveTo(string targetName)
    {
        GameObject targetObj = GameObject.Find(targetName);
        if (targetObj != null)
        {
            //Debug.Log($"Requesting path to {targetName}...");
            Transform interactionPoint = targetObj.transform.Find("IP"); //IntersactionPoint
            Vector3 destination = (interactionPoint != null) ? interactionPoint.position : targetObj.transform.position;
            //Debug.Log($"[Agent] Heading to: {targetName}");
            List<Vector3> path = pathfinder.FindPath(transform.position, destination);

            if (path != null && path.Count > 0)
            {
                StopAllCoroutines();
                StartCoroutine(FollowPath(path));
            }
            else
            {
                Debug.LogWarning("No path found or target is unreachable!");
            }
        }
        else
        {
            Debug.LogError($"Target '{targetName}' not found!");
        }
    }

    IEnumerator FollowPath(List<Vector3> path)
    {
        int targetIndex = 0;

        while (targetIndex < path.Count)
        {
            Vector3 targetPos = new Vector3(path[targetIndex].x, path[targetIndex].y, transform.position.z);
            transform.position = Vector3.MoveTowards(transform.position, targetPos, moveSpeed * Time.deltaTime);

            Vector3 dir = targetPos - transform.position;
            if (dir.sqrMagnitude > 0.001f)
            {
                float angle = Mathf.Atan2(dir.y, dir.x) * Mathf.Rad2Deg;
                transform.rotation = Quaternion.AngleAxis(angle, Vector3.forward);
            }

            if (Vector3.Distance(transform.position, targetPos) < 0.01f)
            {
                targetIndex++;
            }

            yield return null;
        }
    }

    void Update()
    {
        float up = Input.GetKey(KeyCode.W) || Input.GetKey(KeyCode.UpArrow) ? 1f : 0f;
        float down = Input.GetKey(KeyCode.S) || Input.GetKey(KeyCode.DownArrow) ? 1f : 0f;
        float left = Input.GetKey(KeyCode.A) || Input.GetKey(KeyCode.LeftArrow) ? 1f : 0f;
        float right = Input.GetKey(KeyCode.D) || Input.GetKey(KeyCode.RightArrow) ? 1f : 0f;

        if (up > 0f)
        {
            transform.position += transform.up * (moveSpeed * Time.deltaTime);
        }
        else if (down > 0f)
        {
            transform.position -= transform.up * (moveSpeed * Time.deltaTime);
        }

        if (right > 0f)
        {
            transform.position += transform.right * (moveSpeed * Time.deltaTime);
        }
        else if (left > 0f)
        {
            transform.position -= transform.right * (moveSpeed * Time.deltaTime);
        }
    }

    public void StopMotion()
    {
        StopAllCoroutines();
    }

    private void StartMotion(IEnumerator routine)
    {
        StopMotion();
        currentMotion = StartCoroutine(RunMotion(routine));
    }

    private IEnumerator RunMotion(IEnumerator routine)
    {
        yield return StartCoroutine(routine);
        currentMotion = null;
    }
}
```

## InteractableObject.cs

```csharp
using UnityEngine;

public class InteractableObject : MonoBehaviour
{
    public void Interact(string method, string color = null)
    {
        Debug.Log($"[InteractableObject] {name} received interaction: {method}");

        switch (method.ToLower())
        {
            case "till":
                Till();
                break;
            case "water":
                Water();
                break;
            case "harvest":
                Harvest();
                break;
            case "change_color":
                string colorName = !string.IsNullOrEmpty(color) ? color : "white";
                ChangeColor(colorName);
                break;
            default:
                Debug.LogWarning($"Unknown method '{method}' for {name}");
                break;
        }
    }

    private void ChangeColor(string colorName)
    {
        Color newColor = Color.white;
        if (colorName.ToLower() == "brown")
        {
            newColor = new Color(0.36f, 0.25f, 0.20f); // Standard dirt brown
        }
        else if (!ColorUtility.TryParseHtmlString(colorName, out newColor))
        {
            Debug.LogWarning($"Could not parse color: {colorName}, defaulting to white.");
        }

        var renderer = GetComponent<Renderer>();
        if (renderer != null)
        {
            renderer.material.color = newColor;
            Debug.Log($"{name} changed color to {colorName}");
        }
    }

    private void Till()
    {
        Debug.Log($"{name} is being tilled! (Visuals update here)");
        // e.g., Change material color to indicate tilled soil
        GetComponent<Renderer>().material.color = new Color(0.36f, 0.25f, 0.20f);
    }

    private void Water()
    {
        Debug.Log($"{name} is being watered! (Visuals update here)");
        // e.g., Change material color to darker dirt
        GetComponent<Renderer>().material.color = Color.blue;
    }

    private void Harvest()
    {
        Debug.Log($"{name} harvested!");
        Destroy(gameObject);
    }
}
```

## Pathfinding.cs

```csharp
using UnityEngine;
using System.Collections;
using System.Collections.Generic;

public class Pathfinding : MonoBehaviour
{
    Grid grid;

    void Awake()
    {
        grid = GetComponent<Grid>();
    }

    public List<Vector3> FindPath(Vector3 startPos, Vector3 targetPos)
    {
        startPos.z = 0;
        targetPos.z = 0;

        Node startNode = grid.NodeFromWorldPoint(startPos);
        Node targetNode = grid.NodeFromWorldPoint(targetPos);

        List<Vector3> waypoints = new List<Vector3>();
        if (startNode.walkable && targetNode.walkable)
        {
            List<Node> openSet = new List<Node>();
            HashSet<Node> closedSet = new HashSet<Node>();
            openSet.Add(startNode);

            while (openSet.Count > 0)
            {
                Node currentNode = openSet[0];
                for (int i = 1; i < openSet.Count; i++)
                {
                    if (openSet[i].fCost < currentNode.fCost || openSet[i].fCost == currentNode.fCost && openSet[i].hCost < currentNode.hCost)
                    {
                        currentNode = openSet[i];
                    }
                }

                openSet.Remove(currentNode);
                closedSet.Add(currentNode);

                if (currentNode == targetNode)
                {
                    List<Vector3> path = RetracePath(startNode, targetNode);

                    if (path.Count > 0)
                    {
                        path[path.Count - 1] = targetPos;
                    }
                    else if (startNode == targetNode && Vector3.Distance(startPos, targetPos) > 0.05f)
                    {
                        path.Add(targetPos);
                    }

                    return path;
                }

                foreach (Node neighbor in grid.GetNeighbors(currentNode))
                {
                    if (!neighbor.walkable || closedSet.Contains(neighbor))
                    {
                        continue;
                    }

                    int newMovementCostToNeighbor = currentNode.gCost + GetDistance(currentNode, neighbor);
                    if (newMovementCostToNeighbor < neighbor.gCost || !openSet.Contains(neighbor))
                    {
                        neighbor.gCost = newMovementCostToNeighbor;
                        neighbor.hCost = GetDistance(neighbor, targetNode);
                        neighbor.parent = currentNode;

                        if (!openSet.Contains(neighbor))
                            openSet.Add(neighbor);
                    }
                }
            }
        }
        return new List<Vector3>();
    }

    List<Vector3> RetracePath(Node startNode, Node endNode)
    {
        List<Node> path = new List<Node>();
        Node currentNode = endNode;

        while (currentNode != startNode)
        {
            path.Add(currentNode);
            currentNode = currentNode.parent;
        }
        path.Reverse();

        List<Vector3> waypoints = new List<Vector3>();
        foreach (Node n in path) waypoints.Add(n.worldPosition);
        return waypoints;
    }

    int GetDistance(Node nodeA, Node nodeB)
    {
        int dstX = Mathf.Abs(nodeA.gridX - nodeB.gridX);
        int dstY = Mathf.Abs(nodeA.gridY - nodeB.gridY);

        if (dstX > dstY)
            return 14 * dstY + 10 * (dstX - dstY);
        return 14 * dstX + 10 * (dstY - dstX);
    }
}
```

## Grid.cs

```csharp
using UnityEngine;
using System.Collections.Generic;

public class Grid : MonoBehaviour
{
    public LayerMask unwalkableMask;
    public Vector2 gridWorldSize;
    public float nodeRadius;
    public bool visuliseGrid = true;
    Node[,] grid;

    float nodeDiameter;
    int gridSizeX, gridSizeY;

    void Awake()
    {
        nodeDiameter = nodeRadius * 2;
        gridSizeX = Mathf.RoundToInt(gridWorldSize.x / nodeDiameter);
        gridSizeY = Mathf.RoundToInt(gridWorldSize.y / nodeDiameter);
        CreateGrid();
    }

    public int MaxSize
    {
        get { return gridSizeX * gridSizeY; }
    }

    void CreateGrid()
    {
        grid = new Node[gridSizeX, gridSizeY];
        // In 2D, bottom left is: pos - Right*width/2 - Up*height/2
        Vector3 worldBottomLeft = transform.position - Vector3.right * gridWorldSize.x / 2 - Vector3.up * gridWorldSize.y / 2;

        for (int x = 0; x < gridSizeX; x++)
        {
            for (int y = 0; y < gridSizeY; y++)
            {
                Vector3 worldPoint = worldBottomLeft + Vector3.right * (x * nodeDiameter + nodeRadius) + Vector3.up * (y * nodeDiameter + nodeRadius);

                bool walkable = !(Physics2D.OverlapCircle(worldPoint, nodeRadius, unwalkableMask));
                grid[x, y] = new Node(walkable, worldPoint, x, y);
            }
        }
    }

    public List<Node> GetNeighbors(Node node)
    {
        List<Node> neighbors = new List<Node>();

        for (int x = -1; x <= 1; x++)
        {
            for (int y = -1; y <= 1; y++)
            {
                if (x == 0 && y == 0) continue;

                int checkX = node.gridX + x;
                int checkY = node.gridY + y;

                if (checkX >= 0 && checkX < gridSizeX && checkY >= 0 && checkY < gridSizeY)
                {
                    neighbors.Add(grid[checkX, checkY]);
                }
            }
        }
        return neighbors;
    }

    public Node NodeFromWorldPoint(Vector3 worldPosition)
    {
        float percentX = (worldPosition.x + gridWorldSize.x / 2) / gridWorldSize.x;
        float percentY = (worldPosition.y + gridWorldSize.y / 2) / gridWorldSize.y; // Use Y for height
        percentX = Mathf.Clamp01(percentX);
        percentY = Mathf.Clamp01(percentY);

        int x = Mathf.RoundToInt((gridSizeX - 1) * percentX);
        int y = Mathf.RoundToInt((gridSizeY - 1) * percentY);
        return grid[x, y];
    }

    void OnDrawGizmos()
    {
        Gizmos.DrawWireCube(transform.position, new Vector3(gridWorldSize.x, gridWorldSize.y, 1));

        if (grid == null)
        {
            // Only calculate if visualized explicitly check on
            if (visuliseGrid)
            {
                float d = nodeRadius * 2;
                int xCount = Mathf.RoundToInt(gridWorldSize.x / d);
                int yCount = Mathf.RoundToInt(gridWorldSize.y / d);
                // Safety check to avoid zero division or massive loop
                if (d <= 0.01f) return;

                Vector3 bottomLeft = transform.position - Vector3.right * gridWorldSize.x / 2 - Vector3.up * gridWorldSize.y / 2;

                for (int x = 0; x < xCount; x++)
                {
                    for (int y = 0; y < yCount; y++)
                    {
                        Vector3 worldPoint = bottomLeft + Vector3.right * (x * d + nodeRadius) + Vector3.up * (y * d + nodeRadius);
                        // Can skip physics for quicker viz if needed, or keep it
                        bool walkable = !(Physics2D.OverlapCircle(worldPoint, nodeRadius, unwalkableMask));
                        Gizmos.color = walkable ? Color.white : Color.red;
                        Gizmos.DrawCube(worldPoint, Vector3.one * (d - 0.1f));
                    }
                }
            }
        }
        else
        {
            // Grid is not null (Play Mode)
            foreach (Node n in grid)
            {
                if (n == null) continue; // Safety check
                Gizmos.color = n.walkable ? Color.white : Color.red;
                Gizmos.DrawCube(n.worldPosition, Vector3.one * (nodeDiameter - .1f));
            }
        }
    }
}
```

## Node.cs

```csharp
using UnityEngine;

public class Node
{
    public bool walkable;
    public Vector3 worldPosition;
    public int gridX;
    public int gridY;

    public int gCost;
    public int hCost;
    public Node parent;

    public Node(bool _walkable, Vector3 _worldPos, int _gridX, int _gridY)
    {
        walkable = _walkable;
        worldPosition = _worldPos;
        gridX = _gridX;
        gridY = _gridY;
    }

    public int fCost
    {
        get { return gCost + hCost; }
    }
}
```

## SimulationStarter.cs

```csharp
using UnityEngine;
using UnityEngine.Networking;
using System.Collections;
using System.Text;
using System.Collections.Generic;

public class SimulationStarter : MonoBehaviour
{
    public static SimulationStarter Instance;
    public string lastConversationLog = "No conversation recorded.";

    [System.Serializable]
    public class ConversationResponse { public List<string> dialogue; }

    [Header("Backend Configuration")]
    // Ensure this matches the port in your python debug_server.py (usually 8080 or 8000)
    public string backendUrl = "http://localhost:8080";

    void Awake()
    {
        // Singleton pattern: vital for Editor scripts to find this instance
        if (Instance == null)
        {
            Instance = this;
            DontDestroyOnLoad(gameObject); // Optional: keeps it alive if you change scenes
        }
        else
        {
            Destroy(gameObject);
        }
    }

    void Start()
    {
        // Optional: Ping the server to see if it's alive when game starts
        StartCoroutine(HealthCheck());
    }

    /// <summary>
    /// Checks if the Python server is running.
    /// </summary>
    IEnumerator HealthCheck()
    {
        using (UnityWebRequest request = UnityWebRequest.Get(backendUrl + "/health"))
        {
            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                Debug.Log($"[SimStarter] Backend Connected: {request.downloadHandler.text}");
            }
            else
            {
                Debug.LogWarning($"[SimStarter] Could not reach backend at {backendUrl}. Is 'debug_server.py' running?");
            }
        }
    }

    /// <summary>
    /// Calculates dialogue between two agents via Python LLM.
    /// </summary>
    public IEnumerator RequestConversation(string initiator, string receiver, string initLoc, string recLoc, string context = "Casual chat")
    {
        string url = $"{backendUrl}/generate_conversation";

        // Create clean JSON payload
        ConversationRequest payload = new ConversationRequest
        {
            initiator = initiator,
            receiver = receiver,
            initLoc = initLoc,
            recLoc = recLoc,
            context = context
        };

        string json = JsonUtility.ToJson(payload);

        using (UnityWebRequest request = new UnityWebRequest(url, "POST"))
        {
            byte[] bodyRaw = Encoding.UTF8.GetBytes(json);
            request.uploadHandler = new UploadHandlerRaw(bodyRaw);
            request.downloadHandler = new DownloadHandlerBuffer();
            request.SetRequestHeader("Content-Type", "application/json");

            Debug.Log($"[SimStarter] Requesting conversation between {initiator} and {receiver}...");

            yield return request.SendWebRequest();

            if (request.result == UnityWebRequest.Result.Success)
            {
                string responseJson = request.downloadHandler.text;
                //Debug.Log($"[SimStarter] Conversation Generated: {responseJson}");

                try
                {
                    ConversationResponse resp = JsonUtility.FromJson<ConversationResponse>(responseJson);
                    if (resp != null && resp.dialogue != null)
                    {
                        lastConversationLog = string.Join("\n", resp.dialogue);
                    }
                }
                catch
                {
                    lastConversationLog = "Error parsing dialogue: " + responseJson;
                }

                // TODO: Here you would parse the responseJson into a C# object
                // and pass it to your Dialogue UI to display the bubbles.
                // Example: DialogueManager.Instance.ShowDialogue(responseJson);
            }
            else
            {
                Debug.LogError($"[SimStarter] Conversation Request Failed: {request.error}\nResponse: {request.downloadHandler.text}");
            }
        }
    }
}

[System.Serializable]
public class ConversationRequest
{
    public string initiator;
    public string receiver;
    public string initLoc;
    public string recLoc;
    public string context;
}

```

## DebugControlPanel.cs

```csharp
using UnityEngine;
using UnityEditor;
using System.Collections.Generic;
using System.Linq;

public class DebugControlPanel : EditorWindow
{
    private Vector2 scrollPos;
    private GUIStyle wrapperStyle;

    [System.Serializable]
    public class AgentEntry
    {
        public string id;
        public bool isSelected;
        public int locationIndex;
    }

    private List<AgentEntry> agentList = new List<AgentEntry>
    {
        new AgentEntry { id = "Samson", isSelected = false },
        new AgentEntry { id = "Jimmy", isSelected = false }
    };

    private string newAgentName = "NewAgent";
    private string[] locations = new string[] {
        "House_Samson", "House_Jimmy", "Workshop", "River", "Garden", "TownSquare"
    };

    [MenuItem("FYP/Debug Control Panel")]
    public static void ShowWindow() => GetWindow<DebugControlPanel>("Debug Controls");

    void OnGUI()
    {
        if (wrapperStyle == null)
        {
            wrapperStyle = new GUIStyle(EditorStyles.label);
            wrapperStyle.wordWrap = true;
            wrapperStyle.richText = true;
        }

        GUILayout.Label("Agent Manager", EditorStyles.boldLabel);
        DrawAgentList();

        EditorGUILayout.Space();
        GUILayout.Label("Group Actions", EditorStyles.boldLabel);

        DrawGroupActions();

        EditorGUILayout.Space();
        GUILayout.Label("Dialogue Log", EditorStyles.boldLabel);

        EditorGUILayout.BeginVertical("box");
        scrollPos = EditorGUILayout.BeginScrollView(scrollPos, GUILayout.Height(150));

        string logText = (SimulationStarter.Instance != null) ?
                         SimulationStarter.Instance.lastConversationLog :
                         "NO LOG YET.";

        GUILayout.Label(logText, wrapperStyle, GUILayout.ExpandHeight(true));
        //EditorGUILayout.TextArea(logText, GUILayout.ExpandHeight(true));

        EditorGUILayout.EndScrollView();

        if (GUILayout.Button("Clear Log"))
        {
            if (SimulationStarter.Instance != null) SimulationStarter.Instance.lastConversationLog = "";
        }
        EditorGUILayout.EndVertical();
    }

    void DrawAgentList()
    {
        EditorGUILayout.BeginVertical("box");
        GUILayout.Label("Agents", EditorStyles.boldLabel);

        for (int i = 0; i < agentList.Count; i++)
        {
            EditorGUILayout.BeginHorizontal();

            agentList[i].isSelected = EditorGUILayout.Toggle(agentList[i].isSelected, GUILayout.Width(20));
            agentList[i].id = EditorGUILayout.TextField(agentList[i].id, GUILayout.Width(50));
            agentList[i].locationIndex = EditorGUILayout.Popup(agentList[i].locationIndex, locations);
            if (GUILayout.Button("TP", GUILayout.Width(35)))
            {
                MoveAgent(agentList[i].id, locations[agentList[i].locationIndex]);
            }

            GUI.backgroundColor = Color.red;
            if (GUILayout.Button("X", GUILayout.Width(25)))
            {
                bool ok = EditorUtility.DisplayDialog(
                    "Delete agent?", //title
                    $"Remove {agentList[i].id} from the list?", //msg
                    "Yes", "No");

                if (ok)
                {
                    agentList.RemoveAt(i);
                    EditorGUILayout.EndHorizontal();
                    break;
                }
            }
            GUI.backgroundColor = Color.white;
            EditorGUILayout.EndHorizontal();
        }

        EditorGUILayout.Space();
        EditorGUILayout.BeginHorizontal();
        newAgentName = EditorGUILayout.TextField(newAgentName);
        if (GUILayout.Button("Add Agent", GUILayout.Width(80)))
        {
            agentList.Add(new AgentEntry { id = newAgentName, isSelected = true });
            newAgentName = "Agent_" + (agentList.Count + 1);
        }
        EditorGUILayout.EndHorizontal();

        EditorGUILayout.EndVertical();
    }

    void DrawGroupActions()
    {
        if (!Application.isPlaying)
        {
            EditorGUILayout.HelpBox("Enter Play Mode to trigger actions.", MessageType.Info);
            return;
        }

        EditorGUILayout.BeginHorizontal();

        // Count selected
        var selectedAgents = agentList.Where(a => a.isSelected).ToList();
        string buttonText = $"Interact ({selectedAgents.Count})";

        if (GUILayout.Button(buttonText, GUILayout.Height(30)))
        {
            if (selectedAgents.Count < 2)
            {
                Debug.LogWarning("[Debug] Select at least 2 agents to start a conversation.");
            }
            else
            {
                TriggerConversation(selectedAgents[0], selectedAgents[1]);
            }
        }

        if (GUILayout.Button("Teleport All Selected", GUILayout.Height(30)))
        {
            foreach (var agent in selectedAgents)
            {
                MoveAgent(agent.id, locations[agent.locationIndex]);
            }
        }

        EditorGUILayout.EndHorizontal();
    }

    void MoveAgent(string agentId, string targetName)
    {
        GameObject agentObj = GameObject.Find(agentId);
        GameObject targetObj = GameObject.Find(targetName);

        if (targetObj == null)
        {
            Transform placeParent = GameObject.Find("Place")?.transform;
            if (placeParent != null)
            {
                Transform t = placeParent.Find(targetName);
                if (t != null) targetObj = t.gameObject;
            }
        }

        if (agentObj && targetObj)
        {
            agentObj.GetComponent<SimAgent>().MoveTo(targetName);
            Debug.Log($"[Debug] Teleported {agentId} to {targetName}");
        }
        else
        {
            Debug.LogError($"[Debug] Move Failed: Could not find '{agentId}' or '{targetName}'");
        }
    }

    void TriggerConversation(AgentEntry initiator, AgentEntry receiver)
    {
        if (SimulationStarter.Instance != null)
        {
            string initLoc = locations[initiator.locationIndex];
            string recLoc = locations[receiver.locationIndex];
            SimulationStarter.Instance.StartCoroutine(
                SimulationStarter.Instance.RequestConversation(initiator.id, receiver.id, initLoc, recLoc, "Meeting triggered by Debug Panel")
            );
        }
        else
        {
            Debug.LogError("[Debug] SimulationStarter instance not found in scene.");
        }
    }
}
```

## Environment.cs

```csharp
using UnityEngine;
using System.Collections.Generic;

public class Environment : MonoBehaviour
{
    public static Environment Instance;

    // Configurable radius for all interaction points
    public float globalInteractionRadius = 1.0f;

    // Cache of IP positions to avoid GameObject.Find every frame
    private Dictionary<string, Vector3> interactionPoints = new Dictionary<string, Vector3>();

    void Awake()
    {
        if (Instance == null) Instance = this;
        else Destroy(gameObject);

        RefreshInteractionPoints();
    }

    // Call this if objects are added dynamically
    public void RefreshInteractionPoints()
    {
        interactionPoints.Clear();

        // Find all GameObjects in scene (approach can be optimized with Tags if scene is huge)
        GameObject[] allObjects = FindObjectsOfType<GameObject>();

        foreach (var obj in allObjects)
        {
            // Logic: If object has a specific child named 'IP', store that position
            Transform ipChild = obj.transform.Find("IP");
            if (ipChild != null)
            {
                interactionPoints[obj.name] = ipChild.position;
            }
            // Optional: Also store the object's own position if no IP child exists
            else if (obj.GetComponent<InteractableObject>() != null)
            {
                interactionPoints[obj.name] = obj.transform.position;
            }
        }
    }

    public Vector3 GetValidPosition(string targetName)
    {
        if (interactionPoints.ContainsKey(targetName))
        {
            Vector3 center = interactionPoints[targetName];

            // Get random point within circle to prevent exact overlap
            Vector2 randomOffset = Random.insideUnitCircle * globalInteractionRadius;
            return center + new Vector3(randomOffset.x, randomOffset.y, 0);
        }

        Debug.LogWarning($"Target '{targetName}' or its IP not found in Environment cache.");
        return Vector3.zero; // Indicator of failure
    }
}
```
